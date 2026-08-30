from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def _patch_converter_symbols(mode: str) -> None:
    import ui.tools.converter_page as converter

    if mode in {"title_ascii", "all_ascii"}:
        original_label = converter.QLabel

        def patched_label(*args: Any, **kwargs: Any):
            if args and isinstance(args[0], str):
                text = args[0].replace("→", "->")
                args = (text, *args[1:])
            return original_label(*args, **kwargs)

        converter.QLabel = patched_label

    if mode in {"collapse_ascii", "all_ascii"}:
        def ascii_apply_state(self: Any) -> None:
            self.header_button.setChecked(self._expanded)
            arrow = "v" if self._expanded else ">"
            suffix = f"   {self._suffix}" if self._suffix else ""
            self.header_button.setText(f"{arrow}  {self._title}{suffix}")
            self.body.setVisible(self._expanded)

        converter.ConverterCollapsibleSection._apply_state = ascii_apply_state


def _child(mode: str) -> int:
    from app.application import create_application

    app = create_application(sys.argv)
    _patch_converter_symbols(mode)

    import ui.pages.media_tools_page as module

    original_stack = module.QStackedWidget
    add_events: list[dict[str, Any]] = []

    class TimedStack(original_stack):
        def addWidget(self, widget):  # noqa: N802
            started = perf_counter()
            result = super().addWidget(widget)
            add_events.append(
                {
                    "widget_type": type(widget).__name__,
                    "duration_ms": _elapsed_ms(started),
                }
            )
            return result

    module.QStackedWidget = TimedStack

    constructor_times: dict[str, float] = {}
    original_classes = {
        "converter": module.ConverterPage,
        "thumbnail": module.ThumbnailPage,
        "snapshot": module.SnapshotPage,
        "subtitle": module.SubtitlePage,
    }

    def timed_class(name: str, base):
        class Timed(base):
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                started = perf_counter()
                super().__init__(*args, **kwargs)
                constructor_times[name] = _elapsed_ms(started)

        Timed.__name__ = base.__name__
        return Timed

    module.ConverterPage = timed_class("converter", original_classes["converter"])
    module.ThumbnailPage = timed_class("thumbnail", original_classes["thumbnail"])
    module.SnapshotPage = timed_class("snapshot", original_classes["snapshot"])
    module.SubtitlePage = timed_class("subtitle", original_classes["subtitle"])

    page = None
    started = perf_counter()
    try:
        page = module.MediaToolsPage()
        total_ms = _elapsed_ms(started)
        payload = {
            "mode": mode,
            "media_tools_ms": total_ms,
            "constructors": constructor_times,
            "stack_add_events": add_events,
        }
        print("RRV_MEDIA_GLYPH_RESULT=" + json.dumps(payload, ensure_ascii=False))
    finally:
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _extract(stdout: str) -> dict[str, Any]:
    prefix = "RRV_MEDIA_GLYPH_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    raise RuntimeError("Profiler child result was not found.\n" + stdout)


def _parent() -> int:
    modes = (
        ("original", "현재 특수문자 그대로"),
        ("title_ascii", "제목 → 만 -> 로 교체"),
        ("collapse_ascii", "접기 ▼/▶ 만 ASCII로 교체"),
        ("all_ascii", "→ + ▼/▶ 모두 ASCII로 교체"),
    )
    results: list[dict[str, Any]] = []

    print("RR-V media tools glyph cold-start probe")
    print("Each variant runs in a fresh Python process.")
    print("Product code is not modified by this experiment.\n")

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    for mode, label in modes:
        print(f"[{mode}] {label}")
        command = [sys.executable, str(SELF), "--child", mode]
        completed = subprocess.run(
            command,
            cwd=str(ROOT),
            env=env,
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if completed.stdout:
            print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
        if completed.stderr:
            print(completed.stderr, file=sys.stderr, end="" if completed.stderr.endswith("\n") else "\n")
        if completed.returncode != 0:
            print(f"Child failed: mode={mode}, code={completed.returncode}")
            return completed.returncode
        result = _extract(completed.stdout)
        result["label"] = label
        results.append(result)
        print()

    print("Media tools glyph cold-start comparison")
    print("=" * 108)
    print(
        f"{'variant':<18} {'MediaTools':>12} {'Converter ctor':>15} "
        f"{'1st stack add':>15} {'slowest stack add':>18}"
    )
    print("-" * 108)
    for result in results:
        constructors = result.get("constructors") or {}
        events = result.get("stack_add_events") or []
        first_add = float(events[0]["duration_ms"]) if events else 0.0
        slowest_add = max((float(item["duration_ms"]) for item in events), default=0.0)
        print(
            f"{result['mode']:<18} "
            f"{float(result['media_tools_ms']):12.3f} "
            f"{float(constructors.get('converter', 0.0)):15.3f} "
            f"{first_add:15.3f} "
            f"{slowest_add:18.3f}"
        )
    print("=" * 108)

    original = next(item for item in results if item["mode"] == "original")
    all_ascii = next(item for item in results if item["mode"] == "all_ascii")
    saving = float(original["media_tools_ms"]) - float(all_ascii["media_tools_ms"])
    print(f"Original -> all ASCII MediaTools saving: {saving:.3f} ms")
    if saving >= 1000.0:
        print("Verdict: converter Unicode arrows trigger most of the media-tools cold-start cost.")
    else:
        print("Verdict: these converter arrows are not the main media-tools cold-start cause.")
    print("Profiler only: no conversion, download, or Installer is started.")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _child(sys.argv[2])
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
