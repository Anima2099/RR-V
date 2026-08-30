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
    from PySide6.QtWidgets import (
        QButtonGroup,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
    from ui.widgets.download_task_list import DownloadTaskList

    original_stack = module.QStackedWidget
    events: list[dict[str, Any]] = []
    stack_counter = {"value": 0}

    class TimedStack(original_stack):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            stack_counter["value"] += 1
            self._profile_id = stack_counter["value"]

        def addWidget(self, widget: QWidget) -> int:  # noqa: N802
            started = perf_counter()
            result = super().addWidget(widget)
            events.append(
                {
                    "stack_id": self._profile_id,
                    "widget_type": type(widget).__name__,
                    "object_name": widget.objectName(),
                    "duration_ms": _ms(started),
                }
            )
            return result

    module.QStackedWidget = TimedStack

    def create_list_page(self: Any) -> QWidget:
        page = QWidget()
        page.setObjectName(f"profileFilter_{mode}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # Members expected later by DownloadPage.__init__ and _refresh_list_state.
        self.count_label = QLabel()
        self.change_all_paths_button = QPushButton()
        self.clear_completed_button = QPushButton()
        self.start_all_button = QPushButton()
        self.failed_filter_button = QPushButton("실패 0")
        self.retry_all_failed_button = QPushButton("재시도")
        self.export_txt_button = QPushButton("TXT")
        self.list_filter_group = QButtonGroup(self)
        self.all_filter_button = QPushButton("전체")

        self.list_filter_bar = QWidget()
        row = QHBoxLayout(self.list_filter_bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        def add_label() -> None:
            label = QLabel("보기")
            label.setObjectName("mutedText")
            row.addWidget(label)

        def configure_all(*, checked: bool = True) -> None:
            self.all_filter_button = QPushButton("전체")
            self.all_filter_button.setObjectName("queueFilterButton")
            self.all_filter_button.setCheckable(True)
            if checked:
                self.all_filter_button.setChecked(True)
            self.all_filter_button.setToolTip("다운로드 목록의 모든 작업 보기")
            row.addWidget(self.all_filter_button)

        def configure_failed() -> None:
            self.failed_filter_button = QPushButton("실패 0")
            self.failed_filter_button.setObjectName("queueFilterButton")
            self.failed_filter_button.setCheckable(True)
            self.failed_filter_button.setToolTip("실패한 작업만 모아서 보기")
            row.addWidget(self.failed_filter_button)

        def configure_export() -> None:
            self.export_txt_button = QPushButton("TXT 내보내기")
            self.export_txt_button.setObjectName("queueRetryButton")
            self.export_txt_button.setToolTip(
                "현재 다운로드 목록을 제목과 원본 주소가 포함된 TXT 파일로 저장"
            )
            row.addWidget(self.export_txt_button)

        def configure_retry(text: str = "↻ 실패 작업 모두 재시도") -> None:
            self.retry_all_failed_button = QPushButton(text)
            self.retry_all_failed_button.setObjectName("queueRetryButton")
            self.retry_all_failed_button.setToolTip(
                "실패한 작업을 다시 대기 상태로 돌리고 재시도합니다."
            )
            row.addWidget(self.retry_all_failed_button)

        if mode == "label":
            add_label()
        elif mode == "all_plain":
            add_label()
            self.all_filter_button = QPushButton("전체")
            row.addWidget(self.all_filter_button)
        elif mode == "all_checkable":
            add_label()
            configure_all(checked=False)
        elif mode == "all_checked":
            add_label()
            configure_all(checked=True)
        elif mode == "two_checkable":
            add_label()
            configure_all()
            configure_failed()
        elif mode == "grouped":
            add_label()
            configure_all()
            configure_failed()
            self.list_filter_group = QButtonGroup(self)
            self.list_filter_group.setExclusive(True)
            self.list_filter_group.addButton(self.all_filter_button)
            self.list_filter_group.addButton(self.failed_filter_button)
        elif mode == "export":
            add_label()
            configure_export()
        elif mode == "retry_ascii":
            add_label()
            configure_retry("실패 작업 모두 재시도")
        elif mode == "retry_arrow":
            add_label()
            configure_retry()
        elif mode in {"full_visible", "full_hidden"}:
            add_label()
            configure_all()
            configure_failed()
            self.list_filter_group = QButtonGroup(self)
            self.list_filter_group.setExclusive(True)
            self.list_filter_group.addButton(self.all_filter_button)
            self.list_filter_group.addButton(self.failed_filter_button)
            row.addStretch()
            configure_export()
            configure_retry()
            if mode == "full_hidden":
                self.list_filter_bar.hide()

        layout.addWidget(self.list_filter_bar)

        # Lightweight list members so DownloadPage can finish initialization.
        self.list_stack = QStackedWidget()
        empty = QWidget()
        self.list_stack.addWidget(empty)
        self.empty_list_card = empty
        self.scroll_area = QScrollArea()
        self.task_list = DownloadTaskList([])
        return page

    module.DownloadPage._create_list_page = create_list_page
    module.DownloadPage._install_txt_drop_support = lambda self: None

    page = None
    started = perf_counter()
    try:
        page = module.DownloadPage()
        total_ms = _ms(started)
        workspace = [event for event in events if event["stack_id"] == 1]
        first_ms = float(workspace[0]["duration_ms"]) if workspace else 0.0
        payload = {
            "mode": mode,
            "download_page_ms": total_ms,
            "workspace_first_add_ms": first_ms,
            "filter_visible_after_init": bool(
                page.list_filter_bar.isVisibleTo(page)
                if page is not None
                else False
            ),
        }
        print("RRV_FILTER_COMPONENT_RESULT=" + json.dumps(payload, ensure_ascii=False))
    finally:
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _extract(stdout: str) -> dict[str, Any]:
    prefix = "RRV_FILTER_COMPONENT_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    raise RuntimeError("Profiler child result was not found.\n" + stdout)


def _parent() -> int:
    modes = (
        ("label", "보기 QLabel만"),
        ("all_plain", "전체 일반 버튼"),
        ("all_checkable", "전체 checkable"),
        ("all_checked", "전체 checkable + checked"),
        ("two_checkable", "전체 + 실패 checkable"),
        ("grouped", "두 필터 + QButtonGroup"),
        ("export", "TXT 내보내기 버튼"),
        ("retry_ascii", "재시도 버튼 · 화살표 없음"),
        ("retry_arrow", "재시도 버튼 · ↻ 포함"),
        ("full_visible", "원본 필터 바 · 보이는 상태"),
        ("full_hidden", "원본 필터 바 · attach 전 hide"),
    )
    results: list[dict[str, Any]] = []

    print("RR-V filter bar cold-start probe")
    print("Each variant runs in a fresh Python process.")
    print("Product code is not modified by this experiment.\n")

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

    print("Filter bar cold-start comparison")
    print("=" * 88)
    print(f"{'variant':<18} {'DownloadPage':>14} {'workspace first add':>20}")
    print("-" * 88)
    for result in results:
        print(
            f"{result['mode']:<18} "
            f"{float(result['download_page_ms']):14.3f} "
            f"{float(result['workspace_first_add_ms']):20.3f}"
        )
    print("=" * 88)

    visible = next(item for item in results if item["mode"] == "full_visible")
    hidden = next(item for item in results if item["mode"] == "full_hidden")
    saving = float(visible["workspace_first_add_ms"]) - float(hidden["workspace_first_add_ms"])
    print(f"Visible -> hidden workspace add saving: {saving:.3f} ms")
    if saving >= 1000.0:
        print("Verdict: hiding the empty filter bar before attachment avoids most startup cost.")
    else:
        print("Verdict: the filter bar remains expensive even when hidden; inspect the component rows above.")
    print("Profiler only: no download or Installer was started.")
    return 0


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _child(sys.argv[2])
    return _parent()


if __name__ == "__main__":
    raise SystemExit(main())
