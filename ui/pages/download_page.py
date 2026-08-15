from __future__ import annotations

from collections import deque
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from PySide6.QtCore import QEvent, QSize, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon, QResizeEvent
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.download_log import write_download_event
from app.download_preferences import load_download_preferences
from app.general_preferences import (
    load_general_preferences,
    resolved_download_directory,
)
from app.queue_store import QueueLoadResult, load_queue, save_queue
from app.notifications import play_completion_sound
from app.paths import (
    COLLAPSE_ICON_PATH,
    EXPAND_ICON_PATH,
    FOLDER_ICON_PATH,
)
from app.performance_log import write_performance
from app.url_list_io import (
    extract_urls as extract_url_list,
    format_download_list,
    merge_urls,
    probable_collection_urls,
    read_text_file,
    write_text_file,
)
from controllers.download_controller import DownloadController
from core.batch_entry import BatchEntry
from core.download_task import DownloadStatus, DownloadTask
from core.media_info import MediaInfo
from ui.dialogs.batch_add_dialog import BatchAddDialog
from ui.dialogs.duplicate_url_dialog import (
    DuplicateChoice,
    ask_duplicate_choice,
)
from ui.dialogs.subtitle_selection_dialog import default_subtitle_selection
from ui.dialogs.warm_dialogs import show_warm_message
from ui.widgets.common import create_card
from ui.widgets.download_task_list import DownloadTaskList
from ui.widgets.preview_panel import PreviewPanel
from ui.widgets.toast_message import ToastMessage
from workers.subtitle_recovery_worker import SubtitleRecoveryWorker
from workers.thumbnail_recovery_worker import ThumbnailRecoveryWorker


class DownloadPage(QWidget):
    LIST_PAGE = 0
    EDITOR_PAGE = 1

    def __init__(self) -> None:
        super().__init__()

        self.toast = ToastMessage(self)
        self._queue_save_timer = QTimer(self)
        self._queue_save_timer.setSingleShot(True)
        self._queue_save_timer.timeout.connect(self._save_queue_now)
        self._queue_save_error_shown = False
        self._suspend_queue_save = True

        self._queue_load_result = QueueLoadResult(tasks=[])
        general_preferences = load_general_preferences()
        if general_preferences.restore_queue_on_start:
            self._queue_load_result = load_queue()
            restored_tasks = self._queue_load_result.tasks
            if not general_preferences.keep_completed_tasks:
                restored_tasks = [
                    task
                    for task in restored_tasks
                    if task.status is not DownloadStatus.COMPLETED
                ]
            self.tasks = restored_tasks
        else:
            self.tasks = []

        current_folder = str(resolved_download_directory())
        for restored_task in self.tasks:
            if not restored_task.save_path:
                restored_task.save_path = current_folder

        self._focus_mode = False
        self._list_filter = "all"
        self._current_media_info: MediaInfo | None = None
        self._current_thumbnail_data = b""

        self._analysis_mode = "idle"
        self._preview_abandoned = False
        self._active_quick_task_id = ""
        self._quick_queue: deque[tuple[str, str]] = deque()
        self._external_auto_download_task_ids: set[str] = set()
        self._queue_running = False
        self._queue_waiting_for_analysis = False
        self._queue_had_success = False
        self._queue_had_failure = False

        self._thumbnail_recovery_worker: ThumbnailRecoveryWorker | None = None
        self._thumbnail_recovery_task_id = ""
        self._thumbnail_recovery_original_status: DownloadStatus | None = None
        self._thumbnail_recovery_original_phase = ""
        self._thumbnail_recovery_was_thumbnail_failure = False

        self._subtitle_recovery_worker: SubtitleRecoveryWorker | None = None
        self._subtitle_recovery_task_id = ""
        self._subtitle_recovery_original_status: DownloadStatus | None = None
        self._subtitle_recovery_original_phase = ""
        self._subtitle_recovery_was_subtitle_failure = False

        self.controller = DownloadController(self)
        self.controller.analysis_started.connect(self._analysis_started)
        self.controller.analysis_status_changed.connect(
            self._analysis_status_changed
        )
        self.controller.analysis_succeeded.connect(self._analysis_succeeded)
        self.controller.analysis_failed.connect(self._analysis_failed)
        self.controller.analysis_cancelled.connect(self._analysis_cancelled)
        self.controller.analysis_finished.connect(self._analysis_finished)
        self.controller.download_started.connect(self._download_started)
        self.controller.download_process_started.connect(
            self._download_process_started
        )
        self.controller.download_phase_changed.connect(
            self._download_phase_changed
        )
        self.controller.download_progress_changed.connect(
            self._download_progress_changed
        )
        self.controller.download_succeeded.connect(self._download_succeeded)
        self.controller.download_failed.connect(self._download_failed)
        self.controller.download_cancelled.connect(self._download_cancelled)
        self.controller.download_finished.connect(self._download_finished)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(28, 24, 28, 24)
        main_layout.setSpacing(18)

        title = QLabel("다운로드")
        title.setObjectName("pageTitle")

        subtitle = QLabel(
            "영상 주소 확인, 빠른 추가 또는 일괄 추가로 대기열 구성 · URL TXT 파일은 이 페이지에 드롭"
        )
        subtitle.setObjectName("bodyText")
        subtitle.setWordWrap(True)
        main_layout.addWidget(title)
        main_layout.addWidget(subtitle)

        # URL 입력은 항상 작게 유지한다.
        self.url_card, url_card_layout = create_card()
        self.url_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Maximum,
        )

        input_title = QLabel("영상 주소")
        input_title.setObjectName("sectionTitle")

        input_row = QHBoxLayout()
        input_row.setSpacing(10)

        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText(
            "YouTube 또는 지원되는 사이트의 영상 주소를 입력하세요"
        )
        self.url_input.setClearButtonEnabled(True)
        self.url_input.returnPressed.connect(self._analyze_url)
        self.url_input.textEdited.connect(self._url_edited)

        self.analyze_button = QPushButton("정보 확인")
        self.analyze_button.setObjectName("primaryButton")
        self.analyze_button.setMinimumWidth(130)
        self.analyze_button.setToolTip("영상 정보와 이번 영상의 설정을 확인")
        self.analyze_button.clicked.connect(self._analyze_url)

        self.batch_add_button = QPushButton("일괄 추가")
        self.batch_add_button.setObjectName("secondaryButton")
        self.batch_add_button.setMinimumWidth(112)
        self.batch_add_button.setToolTip("재생목록 또는 여러 영상 주소를 한꺼번에 추가")
        self.batch_add_button.clicked.connect(self._open_batch_add_dialog)

        self.quick_add_button = QPushButton("빠른 추가")
        self.quick_add_button.setObjectName("quickAddTextButton")
        self.quick_add_button.setFixedWidth(100)
        self.quick_add_button.setFixedHeight(46)
        self.quick_add_button.setToolTip("기본 프리셋으로 목록에 바로 추가")
        self.quick_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.quick_add_button.clicked.connect(self._quick_add_url)

        input_row.addWidget(self.url_input, 1)
        input_row.addWidget(self.analyze_button)
        input_row.addWidget(self.batch_add_button)
        input_row.addWidget(self.quick_add_button)
        url_card_layout.addWidget(input_title)
        url_card_layout.addLayout(input_row)
        main_layout.addWidget(self.url_card)

        # 목록 화면과 정보 편집 화면은 같은 공간을 번갈아 사용한다.
        self.workspace_stack = QStackedWidget()
        self.list_page = self._create_list_page()
        self.editor_page = self._create_editor_page()
        self.workspace_stack.addWidget(self.list_page)
        self.workspace_stack.addWidget(self.editor_page)
        main_layout.addWidget(self.workspace_stack, 1)
        self._install_txt_drop_support()

        self._show_list_page()
        self._refresh_list_state()
        self._suspend_queue_save = False
        if self.tasks or self._queue_load_result.restored_from_backup:
            self._schedule_queue_save(700)
        QTimer.singleShot(450, self._show_queue_restore_message)
        QTimer.singleShot(700, self._resume_restored_analyses)

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------

    def _create_list_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        list_header = QHBoxLayout()
        list_header.setSpacing(10)

        list_title = QLabel("다운로드 목록")
        list_title.setObjectName("sectionTitle")

        self.count_label = QLabel()
        self.count_label.setObjectName("mutedText")

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
        self.open_download_folder_button.setCursor(
            Qt.CursorShape.PointingHandCursor
        )
        self.open_download_folder_button.setToolTip(
            "기본 다운로드 폴더 열기"
        )
        self.open_download_folder_button.clicked.connect(
            self._open_default_download_folder
        )

        self.change_all_paths_button = QPushButton("↓ 저장 위치 일괄 변경")
        self.change_all_paths_button.setObjectName("secondaryButton")
        self.change_all_paths_button.setToolTip(
            "현재 다운로드 목록에서 아직 다운로드를 시작하지 않은 작업들의 저장 위치를 한 번에 변경합니다."
        )
        self.change_all_paths_button.clicked.connect(
            self._change_all_task_save_paths
        )

        self.clear_completed_button = QPushButton("완료 삭제")
        self.clear_completed_button.setObjectName("secondaryButton")
        self.clear_completed_button.setToolTip(
            "완료된 항목을 목록에서 모두 제거합니다. 다운로드 파일은 삭제하지 않습니다."
        )
        self.clear_completed_button.clicked.connect(
            self._remove_completed_tasks
        )

        self.start_all_button = QPushButton("다운로드 시작")
        self.start_all_button.setObjectName("secondaryButton")
        self.start_all_button.setToolTip(
            "대기 중인 영상을 목록 순서대로 모두 다운로드"
        )
        self.start_all_button.clicked.connect(self._start_first_queued)

        self.focus_mode_button = QToolButton()
        self.focus_mode_button.setObjectName("headerIconButton")
        self.focus_mode_button.setFixedSize(42, 42)
        self.focus_mode_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.focus_mode_button.clicked.connect(self._toggle_focus_mode)
        self._update_focus_button()

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
        self.all_filter_button.clicked.connect(
            lambda: self._set_list_filter("all")
        )

        self.failed_filter_button = QPushButton("실패 0")
        self.failed_filter_button.setObjectName("queueFilterButton")
        self.failed_filter_button.setCheckable(True)
        self.failed_filter_button.setToolTip("실패한 작업만 모아서 보기")
        self.failed_filter_button.clicked.connect(
            lambda: self._set_list_filter("failed")
        )

        self.list_filter_group.addButton(self.all_filter_button)
        self.list_filter_group.addButton(self.failed_filter_button)

        self.retry_all_failed_button = QPushButton("↻ 실패 작업 모두 재시도")
        self.retry_all_failed_button.setObjectName("queueRetryButton")
        self.retry_all_failed_button.setToolTip(
            "실패한 작업을 다시 대기 상태로 돌리고 재시도합니다."
        )
        self.retry_all_failed_button.clicked.connect(
            self._retry_all_failed_tasks
        )

        self.export_txt_button = QPushButton("TXT 내보내기")
        self.export_txt_button.setObjectName("queueRetryButton")
        self.export_txt_button.setToolTip(
            "현재 다운로드 목록을 제목과 원본 주소가 포함된 TXT 파일로 저장"
        )
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

        empty_card, empty_layout = create_card()
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
        empty_description.setWordWrap(True)

        empty_layout.addStretch()
        empty_layout.addWidget(empty_title)
        empty_layout.addWidget(empty_description)
        empty_layout.addStretch()

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.scroll_area.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

        self.task_list = DownloadTaskList(self.tasks)
        self.task_list.task_removed.connect(self._task_removed)
        self.task_list.order_changed.connect(self._order_changed)
        self.task_list.message_requested.connect(self.toast.show_message)
        self.task_list.card_expanded.connect(self._scroll_to_expanded_card)
        self.task_list.retry_requested.connect(self._retry_task)
        self.task_list.stop_requested.connect(self._stop_task)
        self.task_list.path_changed.connect(self._task_path_changed)
        self.task_list.thumbnail_recovery_requested.connect(
            self._recover_task_thumbnail
        )
        self.task_list.subtitle_recovery_requested.connect(
            self._recover_task_subtitle
        )
        self.scroll_area.setWidget(self.task_list)

        self.empty_list_card = empty_card
        self.list_stack.addWidget(empty_card)
        self.list_stack.addWidget(self.scroll_area)
        layout.addWidget(self.list_stack, 1)
        return page

    def _create_editor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("영상 정보와 다운로드 설정")
        title.setObjectName("sectionTitle")

        back_button = QPushButton("목록으로 돌아가기")
        back_button.setObjectName("secondaryButton")
        back_button.clicked.connect(self._back_to_list)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(back_button)
        layout.addLayout(header)

        self.preview_panel = PreviewPanel()
        self.preview_panel.cancel_requested.connect(self._back_to_list)
        self.preview_panel.task_requested.connect(self._create_task_from_preview)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.preview_scroll.setWidget(self.preview_panel)
        layout.addWidget(self.preview_scroll, 1)
        return page

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self.toast.reposition()

    @property
    def has_active_download(self) -> bool:
        return (
            self.controller.is_downloading
            or self._queue_running
            or self._recovery_running()
        )

    def shutdown(self) -> None:
        active_task_id = self.controller.active_download_task_id
        self._queue_running = False
        self._queue_waiting_for_analysis = False

        recovery_worker = self._thumbnail_recovery_worker
        if recovery_worker is not None and recovery_worker.isRunning():
            recovery_worker.cancel()
            recovery_worker.wait(5000)

        subtitle_recovery_worker = self._subtitle_recovery_worker
        if subtitle_recovery_worker is not None and subtitle_recovery_worker.isRunning():
            subtitle_recovery_worker.cancel()
            subtitle_recovery_worker.wait(5000)

        self.controller.shutdown()

        task = self._task_by_id(active_task_id) if active_task_id else None
        if task is not None and task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }:
            task.status = DownloadStatus.STOPPED
            task.speed = "-"
            task.eta = "-"
            task.process_id = 0
            task.phase_message = (
                "프로그램 종료로 중지됨 · 재시도 시 이어받기 시도"
            )
        self._save_queue_now()

    # ------------------------------------------------------------------
    # URL 입력과 분석 요청
    # ------------------------------------------------------------------

    def _resolve_input_url(self) -> str:
        url = self.url_input.text().strip()
        if url:
            return url

        url = self._url_from_clipboard()
        if url:
            self.url_input.setText(url)
            return url

        self.toast.show_message("클립보드에서 영상 주소 없음")
        self.url_input.setFocus()
        return ""

    def _analyze_url(self) -> None:
        url = self._resolve_input_url()
        if not url:
            return

        if self.controller.is_analyzing:
            self.toast.show_message(
                "현재 다른 영상 정보를 확인 중입니다. 잠시 후 다시 시도해 주세요."
            )
            return

        self._analysis_mode = "preview"
        self._preview_abandoned = False
        self._current_media_info = None
        self._current_thumbnail_data = b""
        self.preview_panel.set_loading()
        self.workspace_stack.setCurrentIndex(self.EDITOR_PAGE)
        self.controller.analyze(url, f"preview-{uuid4()}")

    def _quick_add_url(self) -> None:
        url = self._resolve_input_url()
        if not url:
            return

        task = self._create_quick_placeholder(url)
        self._quick_queue.append((task.task_id, url))
        self.url_input.clear()
        self._show_list_page()
        self.toast.show_message("기본 프리셋으로 목록에 추가하고 정보를 확인합니다.")
        QTimer.singleShot(0, self.url_input.setFocus)
        self._start_next_quick_request()

    def enqueue_external_urls(
        self,
        urls: object,
        *,
        auto_download: bool = False,
    ) -> int:
        """외부 URL을 기존 빠른 추가 큐에 연결한다.

        브라우저 확장의 자동 다운로드 옵션이 켜진 요청만 task id를 표시해 두고,
        정보 분석이 성공한 순간 기존 순차 대기열을 시작한다.
        """
        if not isinstance(urls, (list, tuple)):
            return 0

        normalized = extract_url_list(
            "\n".join(str(url) for url in urls)
        )
        if not normalized:
            self.toast.show_message("외부에서 유효한 영상 주소를 찾지 못했습니다.")
            return 0

        collection_urls = probable_collection_urls(normalized)
        collection_keys = {url.casefold() for url in collection_urls}
        direct_urls = [
            url for url in normalized
            if url.casefold() not in collection_keys
        ]

        added_count = 0
        for url in direct_urls:
            task = self._create_quick_placeholder(
                url,
                refresh_state=False,
            )
            self._quick_queue.append((task.task_id, url))
            if auto_download:
                self._external_auto_download_task_ids.add(task.task_id)
            added_count += 1

        if added_count:
            self._show_list_page()
            self._refresh_list_state()
            write_download_event(
                "external.urls_added",
                count=added_count,
                collection_skipped=len(collection_urls),
                auto_download=bool(auto_download),
            )
            QTimer.singleShot(0, self._start_next_quick_request)

        if collection_urls and added_count:
            action_text = (
                "분석 후 자동 다운로드합니다."
                if auto_download
                else "다운로드 목록에 추가했습니다."
            )
            self.toast.show_message(
                f"외부 영상 {added_count}개를 추가했습니다. {action_text} "
                f"재생목록/채널 주소 {len(collection_urls)}개는 목록 확인이 필요해 건너뛰었습니다."
            )
        elif collection_urls:
            self.toast.show_message(
                "재생목록/채널 주소는 외부 빠른 추가로 넣지 않았습니다. "
                "일괄 추가의 목록 확인을 사용해 주세요."
            )
        elif auto_download:
            self.toast.show_message(
                f"외부 영상 {added_count}개를 추가했습니다. 분석 후 자동 다운로드합니다."
            )
        else:
            self.toast.show_message(
                f"외부 영상 {added_count}개를 기본 프리셋으로 추가했습니다."
            )

        return added_count

    def _install_txt_drop_support(self) -> None:
        # 내부 작업 카드 Drag & Drop은 그대로 두고, 외부 TXT 파일만 먼저 가로챈다.
        targets = (
            self.url_card,
            self.url_input,
            self.workspace_stack,
            self.list_page,
            self.list_stack,
            self.empty_list_card,
            self.scroll_area,
            self.scroll_area.viewport(),
            self.task_list,
        )
        self._txt_drop_targets = []
        for target in targets:
            if target is None or target in self._txt_drop_targets:
                continue
            target.setAcceptDrops(True)
            target.installEventFilter(self)
            self._txt_drop_targets.append(target)

    def eventFilter(self, watched, event) -> bool:  # type: ignore[no-untyped-def]
        event_type = event.type()
        if event_type in (QEvent.Type.DragEnter, QEvent.Type.DragMove):
            paths = self._txt_paths(event.mimeData())
            if paths:
                event.acceptProposedAction()
                return True
        elif event_type == QEvent.Type.Drop:
            paths = self._txt_paths(event.mimeData())
            if paths:
                event.acceptProposedAction()
                frozen_paths = tuple(paths)
                QTimer.singleShot(
                    0,
                    lambda: self._open_txt_files_in_batch(frozen_paths),
                )
                return True
        return super().eventFilter(watched, event)

    @staticmethod
    def _txt_paths(mime_data) -> list[str]:  # type: ignore[no-untyped-def]
        if not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if local_path and Path(local_path).suffix.lower() == ".txt":
                paths.append(local_path)
        return paths

    def _open_txt_files_in_batch(self, paths: tuple[str, ...]) -> None:
        imported_urls: list[str] = []
        read_errors: list[str] = []
        readable_files = 0

        for raw_path in paths:
            path = str(raw_path).strip()
            if not path:
                continue
            try:
                text = read_text_file(path)
            except OSError as error:
                read_errors.append(f"{path}: {error}")
                continue
            readable_files += 1
            file_urls = extract_url_list(text)
            imported_urls, _duplicates = merge_urls(imported_urls, file_urls)

        if not imported_urls:
            if read_errors and readable_files == 0:
                self.toast.show_message("TXT 파일을 읽지 못했습니다.")
            else:
                self.toast.show_message("TXT 파일에서 영상 주소를 찾지 못했습니다.")
            return

        file_count = len(paths)
        status = f"드롭한 TXT {file_count}개에서 주소 {len(imported_urls)}개를 불러왔습니다."
        if read_errors:
            status += f" 읽지 못한 파일 {len(read_errors)}개가 있습니다."

        self._open_batch_add_dialog(
            initial_text_override="\n".join(imported_urls),
            initial_status=status,
            clear_main_input=False,
        )

    def _open_batch_add_dialog(
        self,
        _checked: bool = False,
        *,
        initial_text_override: str | None = None,
        initial_status: str = "",
        clear_main_input: bool = True,
    ) -> None:
        # 일반 진입에서는 사용자가 명시적으로 입력한 메인 URL만 이어받는다.
        # TXT 드롭 진입에서는 파일에서 읽은 URL만 넣고 메인 입력란은 보존한다.
        # 클립보드는 창 안의 '클립보드에서 추가' 또는 Ctrl+V로만 가져온다.
        initial_text = (
            self.url_input.text().strip()
            if initial_text_override is None
            else initial_text_override.strip()
        )

        dialog = BatchAddDialog(
            initial_text,
            initial_status=initial_status,
            existing_identity_keys=(task.identity_key for task in self.tasks),
            existing_urls=(task.url for task in self.tasks),
            parent=self,
        )
        if dialog.exec() != dialog.DialogCode.Accepted:
            return

        direct_urls = dialog.direct_urls
        if direct_urls:
            added_count = 0
            for url in direct_urls:
                task = self._create_quick_placeholder(
                    url,
                    refresh_state=False,
                )
                self._quick_queue.append((task.task_id, url))
                added_count += 1

            if clear_main_input:
                self.url_input.clear()
            self._show_list_page()
            self._refresh_list_state()
            write_download_event("batch.direct_tasks_added", count=added_count)
            self.toast.show_message(
                f"개별 영상 {added_count}개를 바로 추가했습니다. 정보를 차례로 확인합니다."
            )
            QTimer.singleShot(0, self._start_next_quick_request)
            return

        entries = dialog.selected_entries
        if not entries:
            return

        added_count = 0
        for entry in entries:
            task = self._create_quick_placeholder(
                entry.webpage_url,
                batch_entry=entry,
                refresh_state=False,
            )
            self._quick_queue.append((task.task_id, entry.webpage_url))
            added_count += 1

        if clear_main_input:
            self.url_input.clear()
        self._show_list_page()
        self._refresh_list_state()
        write_download_event("batch.tasks_added", count=added_count)
        self.toast.show_message(
            f"선택한 영상 {added_count}개를 목록에 추가했습니다. 정보를 차례로 확인합니다."
        )
        QTimer.singleShot(0, self._start_next_quick_request)

    @staticmethod
    def _url_from_clipboard() -> str:
        urls = extract_url_list(QApplication.clipboard().text())
        return urls[0] if urls else ""

    def _start_next_quick_request(self) -> None:
        if self.controller.is_analyzing or not self._quick_queue:
            return

        task_id, url = self._quick_queue.popleft()
        self._analysis_mode = "quick"
        self._active_quick_task_id = task_id
        self.controller.analyze(url, task_id)

    # ------------------------------------------------------------------
    # 분석 결과
    # ------------------------------------------------------------------

    def _analysis_started(self) -> None:
        self.analyze_button.setEnabled(False)
        if self._analysis_mode == "preview":
            self.url_input.setEnabled(False)
            self.batch_add_button.setEnabled(False)
            self.quick_add_button.setEnabled(False)
            self.preview_panel.set_loading()

    def _analysis_status_changed(self, message: str) -> None:
        if self._analysis_mode == "preview":
            self.preview_panel.update_loading_message(message)
            return

        task = self._task_by_id(self._active_quick_task_id)
        if task is not None:
            if task.video_id:
                task.phase_message = message
                self.task_list.refresh_task_status(task.task_id)
            else:
                task.title = message
                self.task_list.refresh_task(task.task_id)

    def _analysis_succeeded(
        self,
        media_info: MediaInfo,
        thumbnail_data: bytes,
    ) -> None:
        if self._analysis_mode == "preview":
            if self._preview_abandoned:
                return
            self._current_media_info = media_info
            self._current_thumbnail_data = thumbnail_data
            self.preview_panel.set_media(media_info, thumbnail_data)
            self.toast.show_message("영상 정보 확인 완료")
            return

        self._complete_quick_task(media_info, thumbnail_data)

    def _analysis_failed(self, message: str, detail: str, raw_log_path: str) -> None:
        if self._analysis_mode == "preview":
            if not self._preview_abandoned:
                self.preview_panel.set_error(message, detail)
            return

        task = self._task_by_id(self._active_quick_task_id)
        self._external_auto_download_task_ids.discard(self._active_quick_task_id)
        if task is not None:
            if not task.video_id:
                task.title = "영상 정보를 확인하지 못했습니다"
            task.status = DownloadStatus.FAILED
            task.phase_message = "상세 정보 확인 실패"
            task.error_message = message
            task.error_detail = detail
            task.raw_log_path = raw_log_path
            task.speed = "-"
            task.eta = "-"
            self.task_list.refresh_task(task.task_id)
            self._schedule_queue_save()
            self.toast.show_message("빠른 추가 영상 분석 실패")

    def _analysis_cancelled(self, message: str) -> None:
        if self._analysis_mode == "preview":
            if not self._preview_abandoned:
                self.preview_panel.set_empty()
                self.toast.show_message(message)
            return

        task = self._task_by_id(self._active_quick_task_id)
        self._external_auto_download_task_ids.discard(self._active_quick_task_id)
        if task is not None:
            if not task.video_id:
                task.title = "영상 정보 확인 취소됨"
            task.status = DownloadStatus.STOPPED
            task.phase_message = "상세 정보 확인 취소됨"
            self.task_list.refresh_task(task.task_id)
            self._schedule_queue_save()

    def _analysis_finished(self) -> None:
        finished_mode = self._analysis_mode
        self._analysis_mode = "idle"
        self._active_quick_task_id = ""

        self.url_input.setEnabled(True)
        self.batch_add_button.setEnabled(True)
        self.quick_add_button.setEnabled(True)
        self.analyze_button.setEnabled(True)

        if finished_mode == "preview" and self._current_media_info is None:
            QTimer.singleShot(0, self.url_input.setFocus)

        QTimer.singleShot(0, self._start_next_quick_request)
        if self._queue_running and not self.controller.is_downloading:
            QTimer.singleShot(0, self._start_next_queue_task)

    def _url_edited(self, _text: str) -> None:
        # 정보 편집 화면의 결과는 다른 주소를 입력해도 목록으로 돌아가기 전까지 유지한다.
        return

    # ------------------------------------------------------------------
    # 빠른 추가 작업
    # ------------------------------------------------------------------

    def _create_quick_placeholder(
        self,
        url: str,
        *,
        batch_entry: BatchEntry | None = None,
        refresh_state: bool = True,
    ) -> DownloadTask:
        preferences = load_download_preferences()
        task = DownloadTask(
            task_id=str(uuid4()),
            title=(
                batch_entry.title
                if batch_entry is not None
                else "영상 정보를 확인 중…"
            ),
            url=url,
            status=DownloadStatus.ANALYZING,
            video_id=batch_entry.video_id if batch_entry is not None else "",
            extractor=batch_entry.extractor if batch_entry is not None else "",
            uploader=batch_entry.uploader if batch_entry is not None else "",
            duration_text=(
                batch_entry.duration_text
                if batch_entry is not None and batch_entry.duration_seconds is not None
                else ""
            ),
            thumbnail_url=(
                batch_entry.thumbnail_url if batch_entry is not None else ""
            ),
            preset=preferences.preset,
            resolution=preferences.resolution,
            container=preferences.container,
            codec=preferences.codec,
            subtitle=(
                "선호 자막 확인 중"
                if preferences.receive_subtitles and not preferences.audio_only
                else "자막 없음"
            ),
            embed_subtitles=preferences.embed_subtitles,
            embed_thumbnail=preferences.embed_thumbnail,
            save_thumbnail=preferences.save_thumbnail,
            audio_only=preferences.audio_only,
            audio_format=preferences.audio_format,
            audio_quality=preferences.audio_quality,
            preserve_metadata=preferences.preserve_metadata,
            save_path=str(resolved_download_directory()),
            phase_message="상세 정보 확인 대기 중…",
        )
        self.tasks.append(task)
        self.task_list.add_task(task)
        if refresh_state:
            self._refresh_list_state()
        return task

    def _complete_quick_task(
        self,
        media_info: MediaInfo,
        thumbnail_data: bytes,
    ) -> None:
        task = self._task_by_id(self._active_quick_task_id)
        if task is None:
            return
        auto_download = task.task_id in self._external_auto_download_task_ids
        self._external_auto_download_task_ids.discard(task.task_id)

        existing_task = next(
            (
                candidate
                for candidate in self.tasks
                if candidate.task_id != task.task_id
                and candidate.identity_key == media_info.identity_key
            ),
            None,
        )
        if existing_task is not None:
            choice = ask_duplicate_choice(existing_task, self)
            if choice is DuplicateChoice.CANCEL:
                self._remove_task_silently(task.task_id)
                return
            if choice is DuplicateChoice.FOCUS_EXISTING:
                self._remove_task_silently(task.task_id)
                self._show_list_page()
                self.task_list.focus_task(existing_task.task_id)
                return

        preferences = load_download_preferences()
        subtitle_selection = (
            default_subtitle_selection(
                media_info.manual_subtitle_languages,
                media_info.automatic_subtitle_languages,
                preferences.preferred_subtitles,
                preferences.allow_automatic_subtitles,
            )
            if preferences.receive_subtitles and not preferences.audio_only
            else None
        )

        task.title = media_info.title
        task.url = media_info.webpage_url
        task.status = DownloadStatus.QUEUED
        task.video_id = media_info.video_id
        task.extractor = media_info.extractor
        task.uploader = media_info.uploader
        task.duration_text = media_info.duration_text
        task.thumbnail_url = media_info.thumbnail_url
        task.thumbnail_data = thumbnail_data
        task.preset = preferences.preset
        task.resolution = preferences.resolution
        task.container = preferences.container
        task.codec = preferences.codec
        task.subtitle = (
            subtitle_selection.summary
            if subtitle_selection is not None
            else "자막 없음"
        )
        task.subtitle_tracks = (
            subtitle_selection.encoded_tracks
            if subtitle_selection is not None
            else ()
        )
        task.embed_subtitles = (
            preferences.embed_subtitles
            and subtitle_selection is not None
            and not subtitle_selection.is_empty
        )
        task.embed_thumbnail = preferences.embed_thumbnail
        task.save_thumbnail = preferences.save_thumbnail
        task.audio_only = preferences.audio_only
        task.audio_format = preferences.audio_format
        task.audio_quality = preferences.audio_quality
        task.preserve_metadata = preferences.preserve_metadata
        task.error_message = ""
        task.error_detail = ""
        task.phase_message = ""

        self.task_list.refresh_task(task.task_id)
        self._refresh_list_state()
        if auto_download:
            self.toast.show_message(
                f"'{preferences.preset}' 프리셋으로 추가됨 · 자동 다운로드"
            )
            self._arm_browser_auto_download_queue()
        else:
            self.toast.show_message(
                f"'{preferences.preset}' 프리셋으로 다운로드 목록에 추가됨"
            )
            if self._queue_running and not self.controller.is_downloading:
                QTimer.singleShot(0, self._start_next_queue_task)

    def _arm_browser_auto_download_queue(self) -> None:
        """브라우저 자동 다운로드를 기존 단일 순차 대기열에 연결한다."""
        if self._recovery_running():
            self.toast.show_message(
                "미디어 복구 작업 중이라 영상은 대기열에만 추가했습니다."
            )
            write_download_event("queue.browser_auto_deferred_recovery")
            return

        if not self._queue_running:
            self._queue_running = True
            self._queue_waiting_for_analysis = False
            self._queue_had_success = False
            self._queue_had_failure = False
            write_download_event(
                "queue.browser_auto_started",
                queued=sum(
                    item.status is DownloadStatus.QUEUED
                    for item in self.tasks
                ),
            )
            self._refresh_list_state()

        # 이미 다른 다운로드가 실행 중이면 그 작업의 finished 신호가 기존
        # 대기열 흐름을 이어준다. 다운로드가 없을 때만 즉시 첫 작업을 시작한다.
        if not self.controller.is_downloading:
            QTimer.singleShot(0, self._start_next_queue_task)

    # ------------------------------------------------------------------
    # 정보 확인 작업 생성
    # ------------------------------------------------------------------

    def _create_task_from_preview(self, start_immediately: bool) -> None:
        operation_started = perf_counter()
        first_card = self.task_list.count == 0
        media_info = self._current_media_info
        if media_info is None:
            self.toast.show_message("먼저 영상 정보를 확인해 주세요.")
            return

        duplicate_started = perf_counter()
        existing_task = self.task_list.task_for_identity(media_info.identity_key)
        duplicate_ms = (perf_counter() - duplicate_started) * 1000.0
        if existing_task is not None:
            choice = ask_duplicate_choice(existing_task, self)
            if choice is DuplicateChoice.CANCEL:
                return
            if choice is DuplicateChoice.FOCUS_EXISTING:
                self._reset_preview()
                self._show_list_page()
                self.task_list.focus_task(existing_task.task_id)
                return

        options_started = perf_counter()
        options = self.preview_panel.selected_options()
        options_ms = (perf_counter() - options_started) * 1000.0

        model_started = perf_counter()
        task = DownloadTask(
            task_id=str(uuid4()),
            title=media_info.title,
            url=media_info.webpage_url,
            status=DownloadStatus.QUEUED,
            video_id=media_info.video_id,
            extractor=media_info.extractor,
            uploader=media_info.uploader,
            duration_text=media_info.duration_text,
            thumbnail_url=media_info.thumbnail_url,
            thumbnail_data=self._current_thumbnail_data,
            preset=str(options["preset"]),
            resolution=str(options["resolution"]),
            container=str(options["container"]),
            codec=str(options["codec"]),
            subtitle=str(options["subtitle"]),
            subtitle_tracks=tuple(options["subtitle_tracks"]),
            embed_subtitles=bool(options["embed_subtitles"]),
            embed_thumbnail=bool(options["embed_thumbnail"]),
            save_thumbnail=bool(options["save_thumbnail"]),
            audio_only=bool(options["audio_only"]),
            audio_format=str(options["audio_format"]),
            audio_quality=str(options["audio_quality"]),
            preserve_metadata=bool(options["preserve_metadata"]),
            save_path=str(resolved_download_directory()),
        )
        model_ms = (perf_counter() - model_started) * 1000.0

        position = 0 if start_immediately else None
        add_started = perf_counter()
        self.task_list.add_task(task, position=position)
        add_ms = (perf_counter() - add_started) * 1000.0

        data_started = perf_counter()
        if position == 0:
            self.tasks.insert(0, task)
        else:
            self.tasks.append(task)
        data_ms = (perf_counter() - data_started) * 1000.0

        state_started = perf_counter()
        self._refresh_list_state()
        state_ms = (perf_counter() - state_started) * 1000.0

        reset_started = perf_counter()
        self._reset_preview()
        reset_ms = (perf_counter() - reset_started) * 1000.0

        switch_started = perf_counter()
        self._show_list_page()
        switch_ms = (perf_counter() - switch_started) * 1000.0

        if start_immediately:
            self._queue_running = False
            self.toast.show_message("목록 맨 위에 추가하고 다운로드를 시작합니다.")
            QTimer.singleShot(0, lambda: self._start_task(task.task_id))
        else:
            self.toast.show_message("다운로드 목록에 추가됨")

        total_ms = (perf_counter() - operation_started) * 1000.0
        write_performance(
            "preview_add.click_handler",
            total_ms,
            first_card=first_card,
            duplicate_ms=f"{duplicate_ms:.3f}",
            options_ms=f"{options_ms:.3f}",
            model_ms=f"{model_ms:.3f}",
            add_ms=f"{add_ms:.3f}",
            data_ms=f"{data_ms:.3f}",
            state_ms=f"{state_ms:.3f}",
            reset_ms=f"{reset_ms:.3f}",
            switch_ms=f"{switch_ms:.3f}",
        )

        settled_started = perf_counter()
        QTimer.singleShot(
            0,
            lambda: write_performance(
                "preview_add.event_loop_settled",
                (perf_counter() - settled_started) * 1000.0,
                first_card=first_card,
                count=self.task_list.count,
            ),
        )

    def _reset_preview(self) -> None:
        self._current_media_info = None
        self._current_thumbnail_data = b""
        self.url_input.clear()
        self.preview_panel.set_empty()
        QTimer.singleShot(0, self.url_input.setFocus)

    def _back_to_list(self) -> None:
        if self._analysis_mode == "preview" and self.controller.is_analyzing:
            self._preview_abandoned = True
            self.controller.cancel_analysis()
        self._show_list_page()

    def _show_list_page(self) -> None:
        self.workspace_stack.setCurrentIndex(self.LIST_PAGE)

    def _show_txt_export_menu(self) -> None:
        if not self.tasks:
            self.toast.show_message("내보낼 다운로드 목록이 없습니다.")
            return

        completed_count = sum(
            task.status is DownloadStatus.COMPLETED for task in self.tasks
        )
        failed_count = sum(
            task.status is DownloadStatus.FAILED for task in self.tasks
        )

        menu = QMenu(self)
        all_action = menu.addAction(f"전체 목록 ({len(self.tasks)}개)")
        completed_action = menu.addAction(f"완료 목록 ({completed_count}개)")
        failed_action = menu.addAction(f"실패 목록 ({failed_count}개)")
        completed_action.setEnabled(completed_count > 0)
        failed_action.setEnabled(failed_count > 0)

        selected_action = menu.exec(
            self.export_txt_button.mapToGlobal(
                self.export_txt_button.rect().bottomLeft()
            )
        )
        if selected_action is all_action:
            self._export_task_list("all")
        elif selected_action is completed_action:
            self._export_task_list("completed")
        elif selected_action is failed_action:
            self._export_task_list("failed")

    def _export_task_list(self, scope: str) -> None:
        scope_definitions = {
            "all": ("전체", "전체", lambda _task: True),
            "completed": (
                "완료",
                "완료",
                lambda task: task.status is DownloadStatus.COMPLETED,
            ),
            "failed": (
                "실패",
                "실패",
                lambda task: task.status is DownloadStatus.FAILED,
            ),
        }
        scope_info = scope_definitions.get(scope)
        if scope_info is None:
            return
        scope_label, file_label, predicate = scope_info
        export_tasks = [task for task in self.tasks if predicate(task)]
        if not export_tasks:
            self.toast.show_message(f"내보낼 {scope_label} 작업이 없습니다.")
            return

        default_directory = Path.home() / "Downloads"
        if not default_directory.is_dir():
            default_directory = Path.home()
        default_path = default_directory / f"RR-V_다운로드_목록_{file_label}.txt"
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            f"{scope_label} 다운로드 목록 TXT 내보내기",
            str(default_path),
            "텍스트 파일 (*.txt);;모든 파일 (*)",
        )
        if not file_path:
            return

        destination = Path(file_path)
        if destination.suffix.lower() != ".txt":
            destination = destination.with_suffix(".txt")
        content = format_download_list(
            ((task.title, task.url) for task in export_tasks),
            scope_label=scope_label,
        )
        try:
            write_text_file(destination, content)
        except OSError as error:
            write_download_event(
                "queue.export_failed",
                scope=scope,
                error=str(error),
            )
            self.toast.show_message("TXT 목록을 저장하지 못했습니다.")
            return

        write_download_event(
            "queue.exported",
            scope=scope,
            count=len(export_tasks),
            path=str(destination),
        )
        self.toast.show_message(
            f"{scope_label} 작업 {len(export_tasks)}개를 TXT로 저장했습니다."
        )

    # ------------------------------------------------------------------
    # 실제 다운로드와 순차 대기열
    # ------------------------------------------------------------------

    def _next_queued_task(self) -> DownloadTask | None:
        return next(
            (item for item in self.tasks if item.status is DownloadStatus.QUEUED),
            None,
        )

    def _has_pending_analysis(self) -> bool:
        return (
            self.controller.is_analyzing
            or bool(self._quick_queue)
            or any(
                task.status is DownloadStatus.ANALYZING
                for task in self.tasks
            )
        )

    def _start_first_queued(self) -> None:
        if self.controller.is_downloading:
            return
        if self._recovery_running():
            self.toast.show_message(
                "썸네일/자막 복구가 끝난 뒤 다운로드를 시작해 주세요."
            )
            return

        task = self._next_queued_task()
        if task is None:
            self.toast.show_message("다운로드 대기 중인 작업이 없습니다.")
            self._refresh_list_state()
            return

        self._queue_running = True
        self._queue_waiting_for_analysis = False
        self._queue_had_success = False
        self._queue_had_failure = False
        write_download_event(
            "queue.started",
            queued=sum(
                item.status is DownloadStatus.QUEUED
                for item in self.tasks
            ),
        )
        self._refresh_list_state()
        self._start_task(task.task_id, from_queue=True)

    def _start_next_queue_task(self) -> None:
        if not self._queue_running or self.controller.is_downloading:
            return

        task = self._next_queued_task()
        if task is not None:
            self._queue_waiting_for_analysis = False
            self._start_task(task.task_id, from_queue=True)
            return

        if self._has_pending_analysis():
            self._queue_waiting_for_analysis = True
            self._refresh_list_state()
            return

        self._queue_running = False
        self._queue_waiting_for_analysis = False
        self._refresh_list_state()
        write_download_event("queue.completed")
        if load_general_preferences().notify_queue_complete:
            self.toast.show_message("대기열 다운로드 처리 완료")
        if self._queue_had_success and not self._queue_had_failure:
            play_completion_sound()
        self._queue_had_success = False
        self._queue_had_failure = False

    def _start_task(self, task_id: str, *, from_queue: bool = False) -> None:
        if self._recovery_running():
            if not from_queue:
                self.toast.show_message(
                    "썸네일/자막 복구가 끝난 뒤 다운로드를 시작해 주세요."
                )
            return

        task = self._task_by_id(task_id)
        if task is None:
            if from_queue:
                self._queue_running = False
            return
        if self.controller.is_downloading:
            if task.status is not DownloadStatus.QUEUED:
                task.status = DownloadStatus.QUEUED
                self.task_list.refresh_task_status(task.task_id)
            if not from_queue:
                self.toast.show_message(
                    "현재 다른 작업을 다운로드 중입니다. 이 작업은 대기 상태로 유지됩니다."
                )
            self._refresh_list_state()
            return
        if task.status is DownloadStatus.ANALYZING:
            if not from_queue:
                self.toast.show_message("영상 정보 확인이 끝난 뒤 시작할 수 있습니다.")
            return

        task.status = DownloadStatus.DOWNLOADING
        task.progress = 0
        task.speed = "-"
        task.eta = "-"
        task.downloaded_bytes = 0
        task.total_bytes = 0
        task.total_bytes_estimated = False
        task.file_size_bytes = 0
        task.phase_message = "다운로드 준비 중…"
        task.error_message = ""
        task.error_detail = ""
        task.output_file = ""
        task.process_id = 0
        self.task_list.refresh_task_status(task.task_id)
        self.task_list.focus_task(task.task_id)
        self._refresh_list_state()

        if not self.controller.start_download(task):
            task.status = DownloadStatus.QUEUED
            task.phase_message = ""
            self.task_list.refresh_task_status(task.task_id)
            if from_queue:
                self._queue_running = False
            self.toast.show_message("현재 다른 다운로드 작업이 실행 중입니다.")
            self._refresh_list_state()

    def _prepare_task_for_retry(self, task: DownloadTask) -> None:
        previous_status = task.status
        task.status = DownloadStatus.QUEUED
        task.progress = 0
        task.speed = "-"
        task.eta = "-"
        task.downloaded_bytes = 0
        task.total_bytes = 0
        task.total_bytes_estimated = False
        task.file_size_bytes = 0
        task.phase_message = ""
        task.error_message = ""
        task.error_detail = ""
        task.output_file = ""
        if previous_status is DownloadStatus.COMPLETED:
            task.output_stem = ""
        task.process_id = 0

    def _retry_task(self, task_id: str) -> None:
        if self._recovery_running():
            self.toast.show_message(
                "썸네일/자막 복구가 끝난 뒤 재다운로드해 주세요."
            )
            return
        task = self._task_by_id(task_id)
        if task is None:
            return
        self._prepare_task_for_retry(task)
        self.task_list.refresh_task_status(task.task_id)
        if self.controller.is_downloading:
            self.toast.show_message("재다운로드 작업이 대기열에 추가됨")
            self._refresh_list_state()
        else:
            self._queue_running = False
            self._start_task(task.task_id)

    def _retry_all_failed_tasks(self) -> None:
        if self._recovery_running():
            self.toast.show_message(
                "썸네일/자막 복구가 끝난 뒤 실패 작업을 재시도해 주세요."
            )
            return
        failed_tasks = [
            task for task in self.tasks
            if task.status is DownloadStatus.FAILED
        ]
        if not failed_tasks:
            self.toast.show_message("재시도할 실패 작업이 없습니다.")
            return

        had_queued_before = any(
            task.status is DownloadStatus.QUEUED for task in self.tasks
        )
        for task in failed_tasks:
            self._prepare_task_for_retry(task)
            self.task_list.refresh_task_status(task.task_id)

        # 재시도한 작업이 바로 보이도록 전체 보기로 돌아간다.
        self._set_list_filter("all", refresh=False)
        self._refresh_list_state()
        self._save_queue_now()

        retry_count = len(failed_tasks)
        if self.controller.is_downloading:
            self.toast.show_message(
                f"실패 작업 {retry_count}개를 다시 대기열에 추가했습니다."
            )
            return

        if had_queued_before:
            self.toast.show_message(
                f"실패 작업 {retry_count}개를 다시 대기열에 추가했습니다. "
                "기존 대기 작업과 함께 다운로드 시작을 눌러주세요."
            )
            return

        self._queue_running = False
        self._start_first_queued()
        self.toast.show_message(
            f"실패 작업 {retry_count}개 재시도를 시작했습니다."
        )

    def _set_list_filter(
        self,
        filter_name: str,
        *,
        refresh: bool = True,
    ) -> None:
        failed_count = sum(
            task.status is DownloadStatus.FAILED for task in self.tasks
        )
        if filter_name == "failed" and failed_count == 0:
            filter_name = "all"

        self._list_filter = filter_name
        failed_only = filter_name == "failed"
        self.task_list.set_failed_only(failed_only)
        self.all_filter_button.setChecked(not failed_only)
        self.failed_filter_button.setChecked(failed_only)
        if refresh:
            self._refresh_list_state()

    def _stop_task(self, task_id: str) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        self._queue_running = False
        self._queue_waiting_for_analysis = False
        if self.controller.cancel_download(task_id):
            task.phase_message = "중지를 요청 중…"
            self.task_list.refresh_task_status(task_id)
            self._refresh_list_state()
            write_download_event("queue.paused_by_user", task_id=task_id)
            self.toast.show_message(
                "현재 다운로드를 중지하고 대기열도 일시 중지합니다."
            )

    def _download_started(self, task_id: str) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.status = DownloadStatus.DOWNLOADING
        task.phase_message = "yt-dlp 시작 중…"
        self.task_list.refresh_task_status(task_id)
        self._refresh_list_state()

    def _download_process_started(self, task_id: str, process_id: int) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.process_id = process_id
        task.phase_message = f"다운로드 프로세스 실행 중 · PID {process_id}"
        self.task_list.refresh_task_status(task_id)

    def _download_phase_changed(
        self,
        task_id: str,
        phase: str,
        message: str,
    ) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.status = (
            DownloadStatus.POSTPROCESSING
            if phase == "postprocessing"
            else DownloadStatus.DOWNLOADING
        )
        task.phase_message = message
        self.task_list.refresh_task_status(task_id)

    def _download_progress_changed(
        self,
        task_id: str,
        progress: int,
        speed: str,
        eta: str,
        downloaded_bytes: int,
        total_bytes: int,
        total_estimated: bool,
    ) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.progress = progress
        task.speed = speed or "-"
        task.eta = eta or "-"
        task.downloaded_bytes = max(0, int(downloaded_bytes or 0))
        task.total_bytes = max(0, int(total_bytes or 0))
        task.total_bytes_estimated = bool(total_estimated)
        self.task_list.refresh_task_status(task_id)

    def _download_succeeded(
        self,
        task_id: str,
        output_file: str,
        raw_log_path: str,
    ) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.status = DownloadStatus.COMPLETED
        task.progress = 100
        task.speed = "-"
        task.eta = "-"
        task.phase_message = "다운로드 완료"
        task.output_file = output_file
        try:
            task.file_size_bytes = max(0, Path(output_file).stat().st_size)
        except OSError:
            task.file_size_bytes = 0
        if task.file_size_bytes > 0:
            task.downloaded_bytes = task.file_size_bytes
            task.total_bytes = task.file_size_bytes
            task.total_bytes_estimated = False
        task.raw_log_path = raw_log_path
        task.process_id = 0
        task.error_message = ""
        task.error_detail = ""
        self.task_list.refresh_task_status(task_id)
        self._schedule_queue_save()
        if self._queue_running:
            self._queue_had_success = True
        else:
            self.toast.show_message("영상 다운로드 완료")
            play_completion_sound()

    def _download_failed(
        self,
        task_id: str,
        message: str,
        detail: str,
    ) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.status = DownloadStatus.FAILED
        task.speed = "-"
        task.eta = "-"
        task.phase_message = "다운로드 실패"
        task.error_message = message
        task.error_detail = detail
        task.process_id = 0
        self.task_list.refresh_task_status(task_id)
        self._schedule_queue_save()
        if self._queue_running:
            self._queue_had_failure = True
            self.toast.show_message(
                "작업 하나가 실패했습니다. 다음 대기 작업은 계속 진행됩니다."
            )
        else:
            self.toast.show_message("다운로드 실패 · 상세 정보 확인 필요")

    def _download_cancelled(self, task_id: str, message: str) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        task.status = DownloadStatus.STOPPED
        task.speed = "-"
        task.eta = "-"
        task.phase_message = "사용자가 다운로드를 중지함"
        task.process_id = 0
        self.task_list.refresh_task_status(task_id)
        self._schedule_queue_save()
        self.toast.show_message(message)

    def _download_finished(self, _task_id: str) -> None:
        self._refresh_list_state()
        if self._queue_running:
            QTimer.singleShot(120, self._start_next_queue_task)

    # ------------------------------------------------------------------
    # 다운로드 결과 복구 공통 상태
    # ------------------------------------------------------------------

    def _recovery_running(self) -> bool:
        return (
            self._thumbnail_recovery_worker is not None
            or self._subtitle_recovery_worker is not None
        )

    def _recovery_button_text(self) -> str:
        if self._subtitle_recovery_worker is not None:
            return "자막 복구 중"
        if self._thumbnail_recovery_worker is not None:
            return "썸네일 복구 중"
        return "복구 중"

    # ------------------------------------------------------------------
    # 다운로드 결과 썸네일 복구
    # ------------------------------------------------------------------

    def _thumbnail_recovery_running(self) -> bool:
        # Worker를 생성한 순간부터 finished 처리로 참조를 지울 때까지를
        # 하나의 복구 작업으로 본다. QThread.start() 직후 isRunning()이 아직
        # False인 짧은 틈에도 다른 다운로드가 시작되지 않게 하기 위함이다.
        return self._thumbnail_recovery_worker is not None

    def _recover_task_thumbnail(self, task_id: str) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        if self._recovery_running():
            self.toast.show_message("이미 다른 미디어 복구 작업을 진행하고 있습니다.")
            return
        if self.controller.is_downloading or self._queue_running:
            self.toast.show_message(
                "다운로드 대기열이 끝난 뒤 썸네일을 복구해 주세요."
            )
            return
        if task.status not in {DownloadStatus.COMPLETED, DownloadStatus.FAILED}:
            self.toast.show_message(
                "완료되었거나 실패한 영상에서만 썸네일을 복구할 수 있습니다."
            )
            return
        if task.audio_only:
            self.toast.show_message(
                "오디오 커버 이미지는 미디어 도구에서 처리해 주세요."
            )
            return

        self._thumbnail_recovery_task_id = task.task_id
        self._thumbnail_recovery_original_status = task.status
        self._thumbnail_recovery_original_phase = task.phase_message
        self._thumbnail_recovery_was_thumbnail_failure = (
            self._is_thumbnail_related_failure(task)
        )

        task.phase_message = "썸네일 복구 준비 중…"
        self.task_list.refresh_task_status(task.task_id)
        self._refresh_list_state()

        worker = ThumbnailRecoveryWorker(task)
        self._thumbnail_recovery_worker = worker
        worker.phase_changed.connect(self._thumbnail_recovery_phase_changed)
        worker.succeeded.connect(self._thumbnail_recovery_succeeded)
        worker.failed.connect(self._thumbnail_recovery_failed)
        worker.cancelled.connect(self._thumbnail_recovery_cancelled)
        worker.finished.connect(self._thumbnail_recovery_finished)
        worker.start()
        self._refresh_list_state()
        self.toast.show_message("영상은 다시 받지 않고 썸네일만 복구합니다.")

    def _thumbnail_recovery_phase_changed(self, message: str) -> None:
        task = self._task_by_id(self._thumbnail_recovery_task_id)
        if task is None:
            return
        task.phase_message = message
        self.task_list.refresh_task_status(task.task_id)

    def _thumbnail_recovery_succeeded(self, result: object) -> None:
        task = self._task_by_id(self._thumbnail_recovery_task_id)
        if task is None:
            return

        output_file = str(getattr(result, "output_file", "") or "")
        thumbnail_url = str(getattr(result, "thumbnail_url", "") or "")
        thumbnail_data = bytes(getattr(result, "thumbnail_data", b"") or b"")
        if output_file:
            task.output_file = output_file
        if thumbnail_url:
            task.thumbnail_url = thumbnail_url
        if thumbnail_data:
            task.thumbnail_data = thumbnail_data

        original_status = self._thumbnail_recovery_original_status
        if (
            original_status is DownloadStatus.FAILED
            and self._thumbnail_recovery_was_thumbnail_failure
        ):
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.speed = "-"
            task.eta = "-"
            task.error_message = ""
            task.error_detail = ""
            task.phase_message = "썸네일 복구 완료"
            message = "썸네일 복구 완료 · 실패 작업을 완료 상태로 복원했습니다."
        elif original_status is DownloadStatus.FAILED:
            # 다른 실패 원인을 썸네일 복구가 가려버리지 않도록 원래 실패 상태는
            # 유지한다. 영상 파일 위치와 썸네일 캐시는 그래도 갱신한다.
            task.status = DownloadStatus.FAILED
            task.phase_message = "썸네일 복구 완료 · 기존 실패 상태 유지"
            message = "썸네일은 복구됐지만 기존 다운로드 실패 상태는 유지됩니다."
        else:
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.phase_message = "썸네일 복구 완료"
            message = "썸네일 복구 완료"

        self.task_list.refresh_task(task.task_id)
        self._save_queue_now()
        self.toast.show_message(message)

    def _thumbnail_recovery_failed(self, message: str, detail: str) -> None:
        task = self._task_by_id(self._thumbnail_recovery_task_id)
        if task is not None:
            task.phase_message = self._thumbnail_recovery_original_phase
            self.task_list.refresh_task_status(task.task_id)

        detail = detail.strip()
        if len(detail) > 520:
            detail = detail[:517].rstrip() + "…"
        dialog_message = message
        if detail and detail != message:
            dialog_message += f"\n\n{detail}"
        show_warm_message(
            self,
            "썸네일 복구 실패",
            dialog_message,
        )

    def _thumbnail_recovery_cancelled(self, message: str) -> None:
        task = self._task_by_id(self._thumbnail_recovery_task_id)
        if task is not None:
            task.phase_message = self._thumbnail_recovery_original_phase
            self.task_list.refresh_task_status(task.task_id)
        self.toast.show_message(message or "썸네일 복구 중지됨")

    def _thumbnail_recovery_finished(self) -> None:
        worker = self._thumbnail_recovery_worker
        self._thumbnail_recovery_worker = None
        self._thumbnail_recovery_task_id = ""
        self._thumbnail_recovery_original_status = None
        self._thumbnail_recovery_original_phase = ""
        self._thumbnail_recovery_was_thumbnail_failure = False
        if worker is not None:
            worker.deleteLater()
        self._refresh_list_state()

    @staticmethod
    def _is_thumbnail_related_failure(task: DownloadTask) -> bool:
        tokens = (
            "썸네일",
            "thumbnail",
            "embedthumbnail",
            "thumbnailconvertor",
            "thumbnailsconvertor",
            "cover art",
            "coverart",
        )
        text = f"{task.error_message}\n{task.error_detail}".casefold()
        if any(token in text for token in tokens):
            return True

        # yt-dlp의 사용자용 오류 문구가 일반화되더라도 원본 로그에는
        # EmbedThumbnail/ThumbnailConvertor 단계가 남는 경우가 있으므로
        # 마지막 부분만 보조적으로 확인한다. 로그가 없으면 조용히 건너뛴다.
        if task.raw_log_path:
            try:
                raw = Path(task.raw_log_path).read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                raw = ""
            if raw:
                tail = raw[-24000:].casefold()
                return any(token in tail for token in tokens)
        return False

    # ------------------------------------------------------------------
    # 다운로드 결과 자막 복구
    # ------------------------------------------------------------------

    def _subtitle_recovery_running(self) -> bool:
        return self._subtitle_recovery_worker is not None

    def _recover_task_subtitle(self, task_id: str) -> None:
        task = self._task_by_id(task_id)
        if task is None:
            return
        if self._recovery_running():
            self.toast.show_message("이미 다른 미디어 복구 작업을 진행하고 있습니다.")
            return
        if self.controller.is_downloading or self._queue_running:
            self.toast.show_message(
                "다운로드 대기열이 끝난 뒤 자막을 복구해 주세요."
            )
            return
        if task.status not in {DownloadStatus.COMPLETED, DownloadStatus.FAILED}:
            self.toast.show_message(
                "완료되었거나 실패한 영상에서만 자막을 복구할 수 있습니다."
            )
            return
        if task.audio_only:
            self.toast.show_message("오디오 전용 작업에는 자막을 복구할 수 없습니다.")
            return
        if not task.subtitle_tracks:
            self.toast.show_message("이 작업에는 선택했던 자막 정보가 없습니다.")
            return

        self._subtitle_recovery_task_id = task.task_id
        self._subtitle_recovery_original_status = task.status
        self._subtitle_recovery_original_phase = task.phase_message
        self._subtitle_recovery_was_subtitle_failure = (
            self._is_subtitle_related_failure(task)
        )

        task.phase_message = "자막 복구 준비 중…"
        self.task_list.refresh_task_status(task.task_id)
        self._refresh_list_state()

        worker = SubtitleRecoveryWorker(task)
        self._subtitle_recovery_worker = worker
        worker.phase_changed.connect(self._subtitle_recovery_phase_changed)
        worker.succeeded.connect(self._subtitle_recovery_succeeded)
        worker.failed.connect(self._subtitle_recovery_failed)
        worker.cancelled.connect(self._subtitle_recovery_cancelled)
        worker.finished.connect(self._subtitle_recovery_finished)
        worker.start()
        self._refresh_list_state()
        self.toast.show_message(
            "영상은 다시 받지 않고 선택했던 자막만 복구합니다."
        )

    def _subtitle_recovery_phase_changed(self, message: str) -> None:
        task = self._task_by_id(self._subtitle_recovery_task_id)
        if task is None:
            return
        task.phase_message = message
        self.task_list.refresh_task_status(task.task_id)

    def _subtitle_recovery_succeeded(self, result: object) -> None:
        task = self._task_by_id(self._subtitle_recovery_task_id)
        if task is None:
            return

        output_file = str(getattr(result, "output_file", "") or "")
        embedded_languages = tuple(
            getattr(result, "embedded_languages", ()) or ()
        )
        sidecar_files = tuple(getattr(result, "sidecar_files", ()) or ())
        skipped_languages = tuple(
            getattr(result, "skipped_existing_languages", ()) or ()
        )
        embed_mode = bool(getattr(result, "embed_mode", False))
        if output_file:
            task.output_file = output_file

        if embed_mode:
            if embedded_languages:
                completed_phase = f"자막 {len(embedded_languages)}개 복구 완료"
                base_message = f"자막 {len(embedded_languages)}개 복구 완료"
                if skipped_languages:
                    base_message += f" · 이미 있던 자막 {len(skipped_languages)}개 제외"
            elif skipped_languages:
                completed_phase = "선택한 자막이 이미 영상에 있음"
                base_message = "선택한 자막이 이미 영상에 들어 있습니다."
            else:
                completed_phase = "자막 복구 완료"
                base_message = "자막 복구 완료"
        else:
            completed_phase = f"자막 파일 {len(sidecar_files)}개 복구 완료"
            base_message = f"자막 파일 {len(sidecar_files)}개 복구 완료"

        original_status = self._subtitle_recovery_original_status
        if (
            original_status is DownloadStatus.FAILED
            and self._subtitle_recovery_was_subtitle_failure
        ):
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.speed = "-"
            task.eta = "-"
            task.error_message = ""
            task.error_detail = ""
            task.phase_message = completed_phase
            message = base_message + " · 실패 작업을 완료 상태로 복원했습니다."
        elif original_status is DownloadStatus.FAILED:
            task.status = DownloadStatus.FAILED
            task.phase_message = completed_phase + " · 기존 실패 상태 유지"
            message = base_message + " · 기존 다운로드 실패 상태는 유지됩니다."
        else:
            task.status = DownloadStatus.COMPLETED
            task.progress = 100
            task.phase_message = completed_phase
            message = base_message

        self.task_list.refresh_task(task.task_id)
        self._save_queue_now()
        self.toast.show_message(message)

    def _subtitle_recovery_failed(self, message: str, detail: str) -> None:
        task = self._task_by_id(self._subtitle_recovery_task_id)
        if task is not None:
            task.phase_message = self._subtitle_recovery_original_phase
            self.task_list.refresh_task_status(task.task_id)

        detail = detail.strip()
        if len(detail) > 520:
            detail = detail[:517].rstrip() + "…"
        dialog_message = message
        if detail and detail != message:
            dialog_message += f"\n\n{detail}"
        show_warm_message(
            self,
            "자막 복구 실패",
            dialog_message,
        )

    def _subtitle_recovery_cancelled(self, message: str) -> None:
        task = self._task_by_id(self._subtitle_recovery_task_id)
        if task is not None:
            task.phase_message = self._subtitle_recovery_original_phase
            self.task_list.refresh_task_status(task.task_id)
        self.toast.show_message(message or "자막 복구 중지됨")

    def _subtitle_recovery_finished(self) -> None:
        worker = self._subtitle_recovery_worker
        self._subtitle_recovery_worker = None
        self._subtitle_recovery_task_id = ""
        self._subtitle_recovery_original_status = None
        self._subtitle_recovery_original_phase = ""
        self._subtitle_recovery_was_subtitle_failure = False
        if worker is not None:
            worker.deleteLater()
        self._refresh_list_state()

    @staticmethod
    def _is_subtitle_related_failure(task: DownloadTask) -> bool:
        tokens = (
            "자막",
            "subtitle",
            "embedsubtitles",
            "embedsubtitle",
            "subtitlesconvertor",
            "subtitleconvertor",
            "writesubtitles",
            "write-subs",
            "requested subtitles",
        )
        text = f"{task.error_message}\n{task.error_detail}".casefold()
        if any(token in text for token in tokens):
            return True

        if task.raw_log_path:
            try:
                raw = Path(task.raw_log_path).read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                raw = ""
            if raw:
                tail = raw[-24000:].casefold()
                return any(token in tail for token in tokens)
        return False

    # ------------------------------------------------------------------
    # 목록 집중 모드와 위치
    # ------------------------------------------------------------------

    def _toggle_focus_mode(self) -> None:
        self._set_focus_mode(not self._focus_mode)

    def _set_focus_mode(self, enabled: bool) -> None:
        self._focus_mode = enabled
        self.url_card.setVisible(not enabled)
        self.add_video_button.setVisible(enabled)
        self._update_focus_button()

    def _update_focus_button(self) -> None:
        if self._focus_mode:
            self.focus_mode_button.setIcon(QIcon(str(COLLAPSE_ICON_PATH)))
            self.focus_mode_button.setToolTip("원래 화면으로 돌아가기")
        else:
            self.focus_mode_button.setIcon(QIcon(str(EXPAND_ICON_PATH)))
            self.focus_mode_button.setToolTip("다운로드 목록 크게 보기")
        self.focus_mode_button.setIconSize(QSize(22, 22))

    def _show_video_input(self) -> None:
        self._set_focus_mode(False)
        QTimer.singleShot(0, self.url_input.setFocus)

    def _scroll_to_expanded_card(self, task_id: str) -> None:
        QTimer.singleShot(30, lambda: self._position_card_near_top(task_id))

    def _position_card_near_top(self, task_id: str) -> None:
        card = self.task_list.card_for_task(task_id)
        if card is None:
            return
        self.task_list.layout().activate()
        scrollbar = self.scroll_area.verticalScrollBar()
        target_value = max(0, card.y() - 8)
        scrollbar.setValue(min(target_value, scrollbar.maximum()))

    # ------------------------------------------------------------------
    # 작업 목록 자동 저장과 복구
    # ------------------------------------------------------------------

    def _schedule_queue_save(self, delay_ms: int = 450) -> None:
        if self._suspend_queue_save:
            return
        self._queue_save_timer.start(max(0, delay_ms))

    def _save_queue_now(self) -> bool:
        self._queue_save_timer.stop()
        try:
            save_queue(self.tasks)
            self._queue_save_error_shown = False
            return True
        except (OSError, ValueError, TypeError) as error:
            write_download_event(
                "queue.save_failed",
                error=str(error),
            )
            if not self._queue_save_error_shown:
                self._queue_save_error_shown = True
                self.toast.show_message(
                    "작업 목록을 저장하지 못했습니다. 로그를 확인해 주세요."
                )
            return False

    def _resume_restored_analyses(self) -> None:
        analyzing_tasks = [
            task for task in self.tasks if task.status is DownloadStatus.ANALYZING
        ]
        if not analyzing_tasks:
            return

        queued_ids = {task_id for task_id, _url in self._quick_queue}
        for task in analyzing_tasks:
            if task.task_id in queued_ids:
                continue
            task.phase_message = "프로그램 재시작 후 상세 정보 확인 대기 중…"
            self.task_list.refresh_task_status(task.task_id)
            self._quick_queue.append((task.task_id, task.url))

        self.toast.show_message(
            f"완료되지 않은 영상 분석 {len(analyzing_tasks)}개를 다시 시작합니다."
        )
        self._refresh_list_state()
        self._start_next_quick_request()

    def _show_queue_restore_message(self) -> None:
        result = self._queue_load_result
        if result.restored_from_backup:
            self.toast.show_message(
                f"기본 저장본이 손상되어 백업에서 작업 {len(self.tasks)}개를 복구했습니다."
            )
            write_download_event(
                "queue.restored_from_backup",
                count=len(self.tasks),
                primary_error=result.error_message,
            )
            return
        if result.error_message and not self.tasks:
            self.toast.show_message(
                "이전 작업 목록을 읽지 못해 빈 목록으로 시작합니다."
            )
            write_download_event(
                "queue.restore_failed",
                error=result.error_message,
            )
            return
        if self.tasks:
            self.toast.show_message(
                f"이전 작업 목록 {len(self.tasks)}개를 복원했습니다."
            )
            write_download_event("queue.restored", count=len(self.tasks))

    # ------------------------------------------------------------------
    # 목록 데이터 동기화
    # ------------------------------------------------------------------

    def _task_by_id(self, task_id: str) -> DownloadTask | None:
        return next(
            (task for task in self.tasks if task.task_id == task_id),
            None,
        )

    def _remove_task_silently(self, task_id: str) -> None:
        self._external_auto_download_task_ids.discard(task_id)
        self.tasks = [task for task in self.tasks if task.task_id != task_id]
        self.task_list.remove_task(task_id, emit_signals=False)
        self._refresh_list_state()

    def _editable_path_tasks(self) -> list[DownloadTask]:
        editable_statuses = {
            DownloadStatus.ANALYZING,
            DownloadStatus.QUEUED,
        }
        return [
            task for task in self.tasks if task.status in editable_statuses
        ]

    def _change_all_task_save_paths(self) -> None:
        editable_tasks = self._editable_path_tasks()
        if not editable_tasks:
            self.toast.show_message(
                "아직 다운로드를 시작하지 않은 작업이 없습니다."
            )
            return

        current_paths = {
            task.save_path.strip()
            for task in editable_tasks
            if task.save_path.strip()
        }
        initial_path = (
            next(iter(current_paths))
            if len(current_paths) == 1
            else str(resolved_download_directory())
        )
        selected_path = QFileDialog.getExistingDirectory(
            self,
            "다운로드 목록 저장 위치 선택",
            initial_path,
        )
        if not selected_path:
            return

        changed_tasks = [
            task for task in editable_tasks if task.save_path != selected_path
        ]
        if not changed_tasks:
            self.toast.show_message("이미 같은 저장 위치를 사용하고 있습니다.")
            return

        for task in changed_tasks:
            task.save_path = selected_path
            self.task_list.refresh_task_status(task.task_id)

        self._refresh_list_state()
        if not self._save_queue_now():
            return

        excluded_count = len(self.tasks) - len(editable_tasks)
        message = (
            f"다운로드를 시작하지 않은 작업 {len(changed_tasks)}개의 "
            "저장 위치를 변경했습니다."
        )
        if excluded_count:
            message += (
                f" 이미 시작되었거나 완료된 작업 {excluded_count}개는 "
                "제외했습니다."
            )
        self.toast.show_message(message)

    def _task_path_changed(self, _task_id: str) -> None:
        # 개별 카드에서 바꾼 저장 위치도 프로그램 종료 전에 확실히 보존한다.
        if self._save_queue_now():
            self.toast.show_message("저장 위치 변경 완료")

    def _open_default_download_folder(self) -> None:
        folder = resolved_download_directory()
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.toast.show_message(
                "기본 다운로드 폴더를 준비하지 못했습니다."
            )
            return

        opened = QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(folder.resolve()))
        )
        if not opened:
            self.toast.show_message(
                "기본 다운로드 폴더를 열지 못했습니다."
            )

    def _remove_completed_tasks(self) -> None:
        if self._recovery_running():
            self.toast.show_message(
                "썸네일/자막 복구가 끝난 뒤 완료 작업을 정리해 주세요."
            )
            return
        completed_ids = [
            task.task_id
            for task in self.tasks
            if task.status is DownloadStatus.COMPLETED
        ]
        if not completed_ids:
            self.toast.show_message("완료된 항목이 없습니다.")
            return

        completed_set = set(completed_ids)
        self.tasks = [
            task for task in self.tasks if task.task_id not in completed_set
        ]
        for task_id in completed_ids:
            self.task_list.remove_task(task_id, emit_signals=False)
        self._refresh_list_state()
        self.toast.show_message(
            f"완료된 항목 {len(completed_ids)}개를 목록에서 제거했습니다."
        )

    def _task_removed(self, task_id: str) -> None:
        self._external_auto_download_task_ids.discard(task_id)
        if (
            task_id == self._thumbnail_recovery_task_id
            and self._thumbnail_recovery_worker is not None
        ):
            self._thumbnail_recovery_worker.cancel()
        if (
            task_id == self._subtitle_recovery_task_id
            and self._subtitle_recovery_worker is not None
        ):
            self._subtitle_recovery_worker.cancel()
        if self.controller.active_download_task_id == task_id:
            self._queue_running = False
            self._queue_waiting_for_analysis = False
            self.controller.cancel_download(task_id)
        if (
            self._active_quick_task_id == task_id
            and self.controller.is_analyzing
        ):
            self.controller.cancel_analysis()
        self.tasks = [task for task in self.tasks if task.task_id != task_id]
        self._quick_queue = deque(
            (pending_id, url)
            for pending_id, url in self._quick_queue
            if pending_id != task_id
        )
        self._refresh_list_state()

    def _order_changed(self, ordered_ids: list[str]) -> None:
        by_id = {task.task_id: task for task in self.tasks}
        self.tasks = [
            by_id[task_id]
            for task_id in ordered_ids
            if task_id in by_id
        ]
        self._schedule_queue_save()

    def _refresh_list_state(self) -> None:
        started = perf_counter()
        count = self.task_list.count
        failed_count = sum(
            task.status is DownloadStatus.FAILED for task in self.tasks
        )
        if self._list_filter == "failed" and failed_count == 0:
            self._set_list_filter("all", refresh=False)

        failed_only = self._list_filter == "failed"
        self.count_label.setText(
            f"실패 {failed_count}개" if failed_only else f"{count}개"
        )
        self.failed_filter_button.setText(f"실패 {failed_count}")
        self.failed_filter_button.setEnabled(failed_count > 0)
        recovery_running = self._recovery_running()
        self.retry_all_failed_button.setEnabled(
            failed_count > 0 and not recovery_running
        )
        self.retry_all_failed_button.setToolTip(
            (
                f"실패한 작업 {failed_count}개를 다시 시도"
                if failed_count
                else "현재 실패한 작업이 없습니다."
            )
        )
        self.list_filter_bar.setVisible(count > 0)
        self.export_txt_button.setEnabled(count > 0)

        editable_path_count = len(self._editable_path_tasks())
        self.change_all_paths_button.setEnabled(editable_path_count > 0)
        self.change_all_paths_button.setToolTip(
            (
                f"저장 위치를 바꿀 수 있는 작업 {editable_path_count}개의 폴더를 한꺼번에 변경"
                if editable_path_count
                else "현재 저장 위치를 변경할 수 있는 작업이 없습니다."
            )
        )

        completed_count = sum(
            task.status is DownloadStatus.COMPLETED for task in self.tasks
        )
        self.clear_completed_button.setText(
            f"완료 삭제 {completed_count}" if completed_count else "완료 삭제"
        )
        self.clear_completed_button.setEnabled(
            completed_count > 0 and not recovery_running
        )
        queued_exists = any(
            task.status is DownloadStatus.QUEUED for task in self.tasks
        )
        if self._recovery_running():
            self.start_all_button.setText(self._recovery_button_text())
            self.start_all_button.setEnabled(False)
        elif self.controller.is_downloading:
            self.start_all_button.setText("다운로드 진행 중")
            self.start_all_button.setEnabled(False)
        elif self._queue_waiting_for_analysis:
            self.start_all_button.setText("분석 완료 대기 중")
            self.start_all_button.setEnabled(False)
        else:
            self.start_all_button.setText("다운로드 시작")
            self.start_all_button.setEnabled(queued_exists)
        self.list_stack.setCurrentIndex(1 if count else 0)
        write_performance(
            "download_page.refresh_list_state",
            (perf_counter() - started) * 1000.0,
            count=count,
        )
        if not self._suspend_queue_save:
            self._schedule_queue_save()
