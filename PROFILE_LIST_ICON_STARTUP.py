from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from time import perf_counter
from typing import Any


ROOT = Path(__file__).resolve().parent
SELF = Path(__file__).resolve()


def _ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def _child(mode: str) -> int:
    from app.application import create_application

    app = create_application(sys.argv)

    import ui.pages.download_page as module
    from PySide6.QtGui import QIcon as RealQIcon
    from app.paths import COLLAPSE_ICON_PATH, EXPAND_ICON_PATH, FOLDER_ICON_PATH

    original_stack = module.QStackedWidget
    original_qicon = module.QIcon
    add_events: list[dict[str, Any]] = []
    stack_counter = {"value": 0}

    class TimedStack(original_stack):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            stack_counter["value"] += 1
            self._rrv_profile_stack_id = stack_counter["value"]

        def addWidget(self, widget):  # noqa: N802
            started = perf_counter()
            result = super().addWidget(widget)
            add_events.append(
                {
                    "stack_id": self._rrv_profile_stack_id,
                    "widget_type": type(widget).__name__,
                    "object_name": widget.objectName(),
                    "duration_ms": _ms(started),
                }
            )
            return result

    module.QStackedWidget = TimedStack

    header_paths = {
        str(FOLDER_ICON_PATH.resolve()).casefold(): "folder",
        str(EXPAND_ICON_PATH.resolve()).casefold(): "expand",
        str(COLLAPSE_ICON_PATH.resolve()).casefold(): "collapse",
    }

    if mode in {"preload_all", "preload_folder", "preload_focus"}:
        paths = []
        if mode in {"preload_all", "preload_folder"}:
            paths.append(FOLDER_ICON_PATH)
        if mode in {"preload_all", "preload_focus"}:
            paths.extend((EXPAND_ICON_PATH, COLLAPSE_ICON_PATH))
        preload_started = perf_counter()
        for path in paths:
            RealQIcon(str(path)).pixmap(22, 22)
        preload_ms = _ms(preload_started)
    else:
        preload_ms = 0.0

    if mode in {"null_all", "null_folder", "null_focus"}:
        def profiled_qicon(value: Any = None) -> RealQIcon:
            raw = str(value or "")
            try:
                key = str(Path(raw).resolve()).casefold() if raw else ""
            except OSError:
                key = raw.casefold()
            label = header_paths.get(key, "")
            suppress = (
                mode == "null_all"
                or (mode == "null_folder" and label == "folder")
                or (mode == "null_focus" and label in {"expand", "collapse"})
            )
            if suppress:
                return RealQIcon()
            return RealQIcon(raw) if raw else RealQIcon()

        module.QIcon = profiled_qicon  # type: ignore[assignment]

    page = None
    started = perf_counter()
    try:
        page = module.DownloadPage()
        total_ms = _ms(started)
        workspace_events = [event for event in add_events if event["stack_id"] == 1]
        first_workspace_ms = (
            float(workspace_events[0]["duration_ms"]) if workspace_events else 0.0
        )
        payload = {
            "mode": mode,
            "download_page_ms": total_ms,
            "workspace_first_add_ms": first_workspace_ms,
            "preload_ms": preload_ms,
            "all_events": add_events,
        }
        print("RRV_LIST_ICON_RESULT=" + json.dumps(payload, ensure_ascii=False))
    finally:
        module.QIcon = original_qicon
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _extract(stdout: str) -> dict[str, Any]:
    prefix = "RRV_LIST_ICON_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    raise RuntimeError("Profiler child result was not found.\n" + stdout)


def _parent() -> int:
    modes = (
        ("original", "현재 원본"),
        ("preload_folder", "folder.svg만 미리 렌더"),
        ("preload_focus", "expand/collapse만 미리 렌더"),
        ("preload_all", "헤더 SVG 3개 모두 미리 렌더"),
        ("null_folder", "folder 아이콘만 제거"),
        ("null_focus", "expand/collapse 아이콘만 제거"),
        ("null_all", "헤더 SVG 3개 모두 제거"),
    )
    results: list[dict[str, Any]] = []

    print("RR-V download header icon cold-start probe")
    print("Each variant runs in a fresh Python process.")
    print("RR-V product code is not modified by this experiment.\n")

    for mode, label in modes:
        print(f"[{mode}] {label}")
        completed = subprocess.run(
            [sys.executable, str(SELF), "--child", mode],
            cwd=str(ROOT),
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
            return completed.returncode
        result = _extract(completed.stdout)
        result["label"] = label
        results.append(result)
        print()

    print("Download header icon cold-start comparison")
    print("=" * 92)
    print(f"{'variant':<18} {'DownloadPage':>14} {'workspace first add':>20} {'explicit preload':>18}")
    print("-" * 92)
    for result in results:
        print(
            f"{result['mode']:<18} "
            f"{float(result['download_page_ms']):14.3f} "
            f"{float(result['workspace_first_add_ms']):20.3f} "
            f"{float(result['preload_ms']):18.3f}"
        )
    print("=" * 92)

    original = next(item for item in results if item["mode"] == "original")
    for mode in ("preload_all", "null_all"):
        candidate = next(item for item in results if item["mode"] == mode)
        saving = float(original["workspace_first_add_ms"]) - float(candidate["workspace_first_add_ms"])
        print(f"original -> {mode} workspace add saving: {saving:.3f} ms")
    print("Profiler only: no download or Installer was started.")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _child(sys.argv[2])
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
