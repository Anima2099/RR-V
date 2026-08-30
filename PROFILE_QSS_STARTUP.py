from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


RESULT_PREFIX = "RRV_QSS_PROBE_RESULT="
CASES = (
    ("full", "현재 RR-V 전체 QSS"),
    ("none", "QSS 제거 · Fusion 유지"),
    ("minimal", "최소 QSS · Fusion 유지"),
)


def _ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def _child(mode: str) -> int:
    from app.application import create_application

    app = create_application([sys.argv[0]])

    if mode == "none":
        app.setStyleSheet("")
    elif mode == "minimal":
        app.setStyleSheet("QWidget {}")
    elif mode != "full":
        raise SystemExit(f"Unknown mode: {mode}")

    import ui.pages.download_page as module

    original_stacked_widget = module.QStackedWidget
    stack_counter = {"value": 0}
    add_events: list[dict[str, Any]] = []

    class TimedStackedWidget(original_stacked_widget):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            stack_counter["value"] += 1
            self._rrv_probe_stack_id = stack_counter["value"]

        def addWidget(self, widget: Any) -> int:  # noqa: N802 - Qt API name
            started = perf_counter()
            result = super().addWidget(widget)
            elapsed = _ms(started)
            add_events.append(
                {
                    "stack_id": self._rrv_probe_stack_id,
                    "widget_type": type(widget).__name__,
                    "object_name": str(widget.objectName() or ""),
                    "duration_ms": elapsed,
                }
            )
            return result

    module.QStackedWidget = TimedStackedWidget

    page = None
    started = perf_counter()
    try:
        page = module.DownloadPage()
        total_ms = _ms(started)
        app.processEvents()

        result = {
            "mode": mode,
            "stylesheet_chars": len(app.styleSheet()),
            "download_page_ms": total_ms,
            "stack_add_events": add_events,
            "task_count": len(getattr(page, "tasks", ()) or ()),
        }
        print(RESULT_PREFIX + json.dumps(result, ensure_ascii=False))
    finally:
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _run_case(script: Path, mode: str, label: str) -> dict[str, Any]:
    print(f"\n[{mode.upper()}] {label}")
    print("=" * 78)
    completed = subprocess.run(
        [sys.executable, str(script), "--child", mode],
        cwd=str(script.parent),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    if completed.stdout:
        print(completed.stdout.rstrip())
    if completed.stderr:
        print(completed.stderr.rstrip())

    if completed.returncode != 0:
        raise RuntimeError(f"{mode} case failed with exit code {completed.returncode}")

    marker_line = next(
        (
            line
            for line in reversed(completed.stdout.splitlines())
            if line.startswith(RESULT_PREFIX)
        ),
        "",
    )
    if not marker_line:
        raise RuntimeError(f"{mode} case did not return a probe result")
    return json.loads(marker_line[len(RESULT_PREFIX):])


def _largest_add_event(result: dict[str, Any]) -> dict[str, Any]:
    events = list(result.get("stack_add_events") or [])
    if not events:
        return {}
    return max(events, key=lambda item: float(item.get("duration_ms", 0.0) or 0.0))


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _child(sys.argv[2])

    script = Path(__file__).resolve()
    print("RR-V QSS startup comparison probe")
    print("Each case runs in a fresh Python process.")
    print("Fusion style and RR-V font/palette stay enabled in all cases.")
    print("No download or Installer is started.")

    results: list[tuple[str, str, dict[str, Any]]] = []
    for mode, label in CASES:
        results.append((mode, label, _run_case(script, mode, label)))

    print("\nQSS cold-start comparison")
    print("=" * 92)
    print(
        f"{'case':<12} {'QSS chars':>10} {'DownloadPage':>15} "
        f"{'slowest addWidget':>18}  target"
    )
    print("-" * 92)

    for mode, label, result in results:
        event = _largest_add_event(result)
        duration = float(event.get("duration_ms", 0.0) or 0.0)
        target = (
            f"stack#{event.get('stack_id', '?')} -> {event.get('widget_type', '?')}"
            if event
            else "no event"
        )
        print(
            f"{mode:<12} {int(result.get('stylesheet_chars', 0)):>10} "
            f"{float(result.get('download_page_ms', 0.0)):>12.3f} ms "
            f"{duration:>15.3f} ms  {target}"
        )

    print("=" * 92)

    by_mode = {mode: result for mode, _label, result in results}
    full_ms = float(by_mode["full"].get("download_page_ms", 0.0) or 0.0)
    none_ms = float(by_mode["none"].get("download_page_ms", 0.0) or 0.0)
    minimal_ms = float(by_mode["minimal"].get("download_page_ms", 0.0) or 0.0)

    full_add = float(_largest_add_event(by_mode["full"]).get("duration_ms", 0.0) or 0.0)
    none_add = float(_largest_add_event(by_mode["none"]).get("duration_ms", 0.0) or 0.0)
    minimal_add = float(_largest_add_event(by_mode["minimal"]).get("duration_ms", 0.0) or 0.0)

    print(f"Full QSS -> no QSS DownloadPage saving: {max(0.0, full_ms - none_ms):.3f} ms")
    print(f"Full QSS -> no QSS slowest addWidget saving: {max(0.0, full_add - none_add):.3f} ms")

    if full_add >= 500.0 and none_add <= full_add * 0.25 and minimal_add <= full_add * 0.25:
        verdict = "Strong QSS signature: full RR-V stylesheet is the dominant addWidget/startup cost."
    elif full_add >= 500.0 and none_add >= full_add * 0.70:
        verdict = "QSS is not the main cause: the heavy addWidget cost remains without the stylesheet."
    elif full_ms >= 500.0 and none_ms <= full_ms * 0.40 and minimal_ms <= full_ms * 0.40:
        verdict = "Strong stylesheet-related startup signature, though cost is not isolated to one addWidget call."
    else:
        verdict = "Mixed result: compare the three addWidget event lists before changing product code."

    print(f"Verdict: {verdict}")
    print("Profiler only: RR-V product code was not modified by this experiment.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
