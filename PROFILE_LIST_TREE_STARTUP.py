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
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
    from ui.widgets.download_task_list import DownloadTaskList

    original_create_list_page = module.DownloadPage._create_list_page
    original_stack = module.QStackedWidget
    add_events: list[dict[str, Any]] = []
    stack_counter = {"value": 0}

    class TimedStack(original_stack):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            stack_counter["value"] += 1
            self._rrv_profile_stack_id = stack_counter["value"]

        def addWidget(self, widget: QWidget) -> int:  # noqa: N802
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

    def create_variant(self: Any) -> QWidget:
        if mode == "full":
            return original_create_list_page(self)

        page = QWidget()
        page.setObjectName(f"profileList_{mode}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # DownloadPage.__init__ later expects these members to exist. The profiler
        # supplies lightweight equivalents when a variant omits the real controls.
        self.count_label = QLabel()
        self.change_all_paths_button = QPushButton()
        self.clear_completed_button = QPushButton()
        self.start_all_button = QPushButton()
        self.failed_filter_button = QPushButton()
        self.retry_all_failed_button = QPushButton()
        self.export_txt_button = QPushButton()
        self.list_filter_bar = QWidget()

        if mode == "empty":
            self.list_stack = QStackedWidget()
            empty = QWidget()
            self.list_stack.addWidget(empty)
            self.empty_list_card = empty
            self.scroll_area = QScrollArea()
            self.task_list = DownloadTaskList([])
            return page

        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(0, 0, 0, 0)
        header_layout.addWidget(QLabel("다운로드 목록"))
        header_layout.addWidget(self.count_label)
        header_layout.addStretch()
        header_layout.addWidget(self.change_all_paths_button)
        header_layout.addWidget(self.clear_completed_button)
        header_layout.addWidget(self.start_all_button)
        layout.addWidget(header)

        if mode == "header":
            self.list_stack = QStackedWidget()
            empty = QWidget()
            self.list_stack.addWidget(empty)
            self.empty_list_card = empty
            self.scroll_area = QScrollArea()
            self.task_list = DownloadTaskList([])
            return page

        self.list_stack = QStackedWidget()
        self.list_stack.setMinimumHeight(80)
        empty_card = QWidget()
        empty_layout = QVBoxLayout(empty_card)
        empty_layout.addWidget(QLabel("아직 추가된 영상이 없음"))
        self.empty_list_card = empty_card
        self.list_stack.addWidget(empty_card)

        if mode == "empty_card":
            self.scroll_area = QScrollArea()
            self.task_list = DownloadTaskList([])
            layout.addWidget(self.list_stack, 1)
            return page

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        if mode == "scroll_empty":
            scroll_child = QWidget()
            self.scroll_area.setWidget(scroll_child)
            self.task_list = DownloadTaskList([])
        else:
            self.task_list = DownloadTaskList([])
            self.scroll_area.setWidget(self.task_list)

        self.list_stack.addWidget(self.scroll_area)
        layout.addWidget(self.list_stack, 1)
        return page

    module.DownloadPage._create_list_page = create_variant

    # The reduced variants omit the real TXT drop-target controls. Keep the test
    # focused on widget-tree attachment rather than synthetic missing members.
    if mode != "full":
        module.DownloadPage._install_txt_drop_support = lambda self: None

    page = None
    started = perf_counter()
    try:
        page = module.DownloadPage()
        total_ms = _ms(started)
        workspace_events = [event for event in add_events if event["stack_id"] == 1]
        slowest = max(add_events, key=lambda item: item["duration_ms"], default=None)
        payload = {
            "mode": mode,
            "download_page_ms": total_ms,
            "workspace_events": workspace_events,
            "slowest_event": slowest,
            "all_events": add_events,
        }
        print("RRV_LIST_TREE_RESULT=" + json.dumps(payload, ensure_ascii=False))
    finally:
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _extract(stdout: str) -> dict[str, Any]:
    prefix = "RRV_LIST_TREE_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    raise RuntimeError("Profiler child result was not found.\n" + stdout)


def _parent() -> int:
    modes = (
        ("empty", "빈 list_page"),
        ("header", "헤더/버튼"),
        ("empty_card", "빈 목록 카드"),
        ("scroll_empty", "QScrollArea + 빈 QWidget"),
        ("task_list", "QScrollArea + DownloadTaskList"),
        ("full", "원본 전체 list_page"),
    )
    results: list[dict[str, Any]] = []

    print("RR-V list subtree cold-start probe")
    print("Each variant runs in a fresh Python process.")
    print("Product code is not modified by this experiment.\n")

    for mode, label in modes:
        print(f"[{mode}] {label}")
        command = [sys.executable, str(SELF), "--child", mode]
        completed = subprocess.run(
            command,
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
            print(f"Child failed: mode={mode}, code={completed.returncode}")
            return completed.returncode
        result = _extract(completed.stdout)
        result["label"] = label
        results.append(result)
        print()

    print("List subtree cold-start comparison")
    print("=" * 92)
    print(f"{'variant':<16} {'DownloadPage':>14} {'workspace first add':>20} {'slowest addWidget':>20}")
    print("-" * 92)
    for result in results:
        workspace = result.get("workspace_events") or []
        first_workspace = float(workspace[0]["duration_ms"]) if workspace else 0.0
        slowest = result.get("slowest_event") or {}
        slowest_ms = float(slowest.get("duration_ms", 0.0))
        print(
            f"{result['mode']:<16} "
            f"{float(result['download_page_ms']):14.3f} "
            f"{first_workspace:20.3f} "
            f"{slowest_ms:20.3f}"
        )
    print("=" * 92)

    baseline = next(item for item in results if item["mode"] == "empty")
    full = next(item for item in results if item["mode"] == "full")
    print(
        "Full - empty DownloadPage delta: "
        f"{float(full['download_page_ms']) - float(baseline['download_page_ms']):.3f} ms"
    )
    print("Profiler only: no download or Installer was started.")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _child(sys.argv[2])
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
