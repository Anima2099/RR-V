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
    from PySide6.QtCore import QSize, Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import (
        QButtonGroup,
        QHBoxLayout,
        QLabel,
        QPushButton,
        QScrollArea,
        QStackedWidget,
        QSizePolicy,
        QToolButton,
        QVBoxLayout,
        QWidget,
    )
    from app.paths import COLLAPSE_ICON_PATH, EXPAND_ICON_PATH, FOLDER_ICON_PATH
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

    include_header = mode in {
        "header",
        "header_filter",
        "header_empty",
        "header_filter_empty",
        "exact_all",
    }
    include_filter = mode in {
        "filter",
        "header_filter",
        "filter_empty",
        "header_filter_empty",
        "exact_all",
    }
    include_empty = mode in {
        "empty_nowrap",
        "empty_wrap",
        "header_empty",
        "filter_empty",
        "header_filter_empty",
        "exact_all",
    }
    empty_wrap = mode != "empty_nowrap"
    include_scroll = mode == "exact_all"

    def create_variant(self: Any) -> QWidget:
        if mode == "full":
            return original_create_list_page(self)

        page = QWidget()
        page.setObjectName(f"profileComponents_{mode}")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        # DownloadPage.__init__ later reads these controls in _refresh_list_state().
        # Reduced modes replace omitted controls with lightweight equivalents.
        self.count_label = QLabel()
        self.count_label.setObjectName("mutedText")
        self.change_all_paths_button = QPushButton()
        self.clear_completed_button = QPushButton()
        self.start_all_button = QPushButton()
        self.failed_filter_button = QPushButton()
        self.retry_all_failed_button = QPushButton()
        self.export_txt_button = QPushButton()
        self.list_filter_bar = QWidget()

        if include_header:
            list_header = QHBoxLayout()
            list_header.setSpacing(10)

            list_title = QLabel("다운로드 목록")
            list_title.setObjectName("sectionTitle")

            self.add_video_button = QPushButton("+ 영상 추가")
            self.add_video_button.setObjectName("secondaryButton")
            self.add_video_button.setToolTip("일반 보기로 돌아가 영상 주소를 입력")
            self.add_video_button.clicked.connect(self._show_video_input)
            self.add_video_button.hide()

            self.open_download_folder_button = QToolButton()
            self.open_download_folder_button.setObjectName("headerIconButton")
            self.open_download_folder_button.setFixedSize(42, 42)
            self.open_download_folder_button.setIcon(QIcon(str(FOLDER_ICON_PATH)))
            self.open_download_folder_button.setIconSize(QSize(22, 22))
            self.open_download_folder_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.open_download_folder_button.setToolTip("기본 다운로드 폴더 열기")
            self.open_download_folder_button.clicked.connect(self._open_default_download_folder)

            self.change_all_paths_button = QPushButton("↓ 저장 위치 일괄 변경")
            self.change_all_paths_button.setObjectName("secondaryButton")
            self.change_all_paths_button.setToolTip(
                "현재 다운로드 목록에서 아직 다운로드를 시작하지 않은 작업들의 저장 위치를 한 번에 변경합니다."
            )
            self.change_all_paths_button.clicked.connect(self._change_all_task_save_paths)

            self.clear_completed_button = QPushButton("완료 삭제")
            self.clear_completed_button.setObjectName("secondaryButton")
            self.clear_completed_button.setToolTip(
                "완료된 항목을 목록에서 모두 제거합니다. 다운로드 파일은 삭제하지 않습니다."
            )
            self.clear_completed_button.clicked.connect(self._remove_completed_tasks)

            self.start_all_button = QPushButton("다운로드 시작")
            self.start_all_button.setObjectName("secondaryButton")
            self.start_all_button.setToolTip("대기 중인 영상을 목록 순서대로 모두 다운로드")
            self.start_all_button.clicked.connect(self._start_first_queued)

            self.focus_mode_button = QToolButton()
            self.focus_mode_button.setObjectName("headerIconButton")
            self.focus_mode_button.setFixedSize(42, 42)
            self.focus_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
            self.focus_mode_button.clicked.connect(self._toggle_focus_mode)
            if self._focus_mode:
                self.focus_mode_button.setIcon(QIcon(str(COLLAPSE_ICON_PATH)))
                self.focus_mode_button.setToolTip("원래 화면으로 돌아가기")
            else:
                self.focus_mode_button.setIcon(QIcon(str(EXPAND_ICON_PATH)))
                self.focus_mode_button.setToolTip("다운로드 목록 크게 보기")
            self.focus_mode_button.setIconSize(QSize(22, 22))

            list_header.addWidget(list_title)
            list_header.addWidget(self.count_label)
            list_header.addStretch()
            list_header.addWidget(self.add_video_button)
            list_header.addWidget(self.open_download_folder_button)
            list_header.addWidget(self.change_all_paths_button)
            list_header.addWidget(self.clear_completed_button)
            list_header.addWidget(self.start_all_button)
            list_header.addWidget(self.focus_mode_button)
            layout.addLayout(list_header)

        if include_filter:
            self.list_filter_bar = QWidget()
            filter_row = QHBoxLayout(self.list_filter_bar)
            filter_row.setContentsMargins(0, 0, 0, 0)
            filter_row.setSpacing(8)

            filter_label = QLabel("보기")
            filter_label.setObjectName("mutedText")

            self.list_filter_group = QButtonGroup(self)
            self.list_filter_group.setExclusive(True)

            self.all_filter_button = QPushButton("전체")
            self.all_filter_button.setObjectName("queueFilterButton")
            self.all_filter_button.setCheckable(True)
            self.all_filter_button.setChecked(True)
            self.all_filter_button.setToolTip("다운로드 목록의 모든 작업 보기")
            self.all_filter_button.clicked.connect(lambda: self._set_list_filter("all"))

            self.failed_filter_button = QPushButton("실패 0")
            self.failed_filter_button.setObjectName("queueFilterButton")
            self.failed_filter_button.setCheckable(True)
            self.failed_filter_button.setToolTip("실패한 작업만 모아서 보기")
            self.failed_filter_button.clicked.connect(lambda: self._set_list_filter("failed"))

            self.list_filter_group.addButton(self.all_filter_button)
            self.list_filter_group.addButton(self.failed_filter_button)

            self.retry_all_failed_button = QPushButton("↻ 실패 작업 모두 재시도")
            self.retry_all_failed_button.setObjectName("queueRetryButton")
            self.retry_all_failed_button.setToolTip("실패한 작업을 다시 대기 상태로 돌리고 재시도합니다.")
            self.retry_all_failed_button.clicked.connect(self._retry_all_failed_tasks)

            self.export_txt_button = QPushButton("TXT 내보내기")
            self.export_txt_button.setObjectName("queueRetryButton")
            self.export_txt_button.setToolTip("현재 다운로드 목록을 제목과 원본 주소가 포함된 TXT 파일로 저장")
            self.export_txt_button.clicked.connect(self._show_txt_export_menu)

            filter_row.addWidget(filter_label)
            filter_row.addWidget(self.all_filter_button)
            filter_row.addWidget(self.failed_filter_button)
            filter_row.addStretch()
            filter_row.addWidget(self.export_txt_button)
            filter_row.addWidget(self.retry_all_failed_button)
            layout.addWidget(self.list_filter_bar)

        self.list_stack = QStackedWidget()
        self.list_stack.setMinimumHeight(80)

        if include_empty:
            empty_card, empty_layout = module.create_card()
            empty_card.setMinimumHeight(90)

            empty_title = QLabel("아직 추가된 영상이 없음")
            empty_title.setObjectName("emptyTitle")
            empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)

            empty_description = QLabel(
                "영상 주소 입력 후 정보 확인, 빠른 추가 또는 일괄 추가를 사용할 수 있습니다.\n"
                "URL이 들어 있는 TXT 파일은 이 화면에 바로 드롭할 수 있습니다."
            )
            empty_description.setObjectName("emptyDescription")
            empty_description.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty_description.setWordWrap(empty_wrap)

            empty_layout.addStretch()
            empty_layout.addWidget(empty_title)
            empty_layout.addWidget(empty_description)
            empty_layout.addStretch()
        else:
            empty_card = QWidget()
            empty_card.setObjectName("profileSimpleEmpty")

        self.empty_list_card = empty_card
        self.list_stack.addWidget(empty_card)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )
        self.task_list = DownloadTaskList([])
        self.scroll_area.setWidget(self.task_list)

        if include_scroll:
            self.list_stack.addWidget(self.scroll_area)

        layout.addWidget(self.list_stack, 1)
        return page

    module.DownloadPage._create_list_page = create_variant
    if mode != "full":
        module.DownloadPage._install_txt_drop_support = lambda self: None

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
            "all_events": add_events,
        }
        print("RRV_LIST_COMPONENT_RESULT=" + json.dumps(payload, ensure_ascii=False))
    finally:
        if page is not None:
            page.deleteLater()
        app.processEvents()
        app.quit()
    return 0


def _extract(stdout: str) -> dict[str, Any]:
    prefix = "RRV_LIST_COMPONENT_RESULT="
    for line in reversed(stdout.splitlines()):
        if line.startswith(prefix):
            return json.loads(line[len(prefix):])
    raise RuntimeError("Profiler child result was not found.\n" + stdout)


def _parent() -> int:
    modes = (
        ("base", "최소 호환 구조"),
        ("header", "정확한 원본 헤더"),
        ("filter", "정확한 원본 필터 바"),
        ("empty_nowrap", "정확한 빈 카드 · wordWrap 없음"),
        ("empty_wrap", "정확한 빈 카드 · wordWrap 있음"),
        ("header_filter", "원본 헤더 + 필터"),
        ("header_empty", "원본 헤더 + 빈 카드"),
        ("filter_empty", "원본 필터 + 빈 카드"),
        ("header_filter_empty", "헤더 + 필터 + 빈 카드"),
        ("exact_all", "헤더 + 필터 + 빈 카드 + 실제 목록 영역"),
        ("full", "원본 _create_list_page 그대로"),
    )
    results: list[dict[str, Any]] = []

    print("RR-V exact list component cold-start probe")
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
            print(f"Child failed: mode={mode}, code={completed.returncode}")
            return completed.returncode
        result = _extract(completed.stdout)
        result["label"] = label
        results.append(result)
        print()

    print("Exact list component cold-start comparison")
    print("=" * 86)
    print(f"{'variant':<22} {'DownloadPage':>16} {'workspace first add':>22}")
    print("-" * 86)
    for result in results:
        print(
            f"{result['mode']:<22} "
            f"{float(result['download_page_ms']):16.3f} "
            f"{float(result['workspace_first_add_ms']):22.3f}"
        )
    print("=" * 86)

    baseline = next(item for item in results if item["mode"] == "base")
    full = next(item for item in results if item["mode"] == "full")
    print(
        "Full - base DownloadPage delta: "
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
