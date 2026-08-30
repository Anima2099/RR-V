from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl, Signal
from PySide6.QtGui import (
    QIcon,
    QDesktopServices,
    QDragEnterEvent,
    QDropEvent,
    QPixmap,
    QResizeEvent,
)
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.notifications import play_completion_sound
from app.paths import RRV_LOGS_DIR, SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH
from app.theme import themed_icon_path
from app.thumbnail_log import thumbnail_log_path
from app.thumbnail_preferences import (
    ThumbnailPreferences,
    load_thumbnail_preferences,
    save_thumbnail_preferences,
)
from core.thumbnail_models import (
    OUTPUT_NEW_FILE,
    OUTPUT_OVERWRITE,
    ThumbnailOptions,
    ThumbnailProbeResult,
    ThumbnailTask,
)
from services.thumbnail_service import (
    SUPPORTED_IMAGE_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    find_matching_image,
)
from workers.thumbnail_worker import (
    ThumbnailBatchWorker,
    ThumbnailFolderScanWorker,
    ThumbnailProbeWorker,
)


class DropPathEdit(QLineEdit):
    path_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setAcceptDrops(True)
        self.setReadOnly(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.path_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()


class ImagePreviewLabel(QLabel):
    def __init__(self, empty_text: str) -> None:
        super().__init__(empty_text)
        self._empty_text = empty_text
        self._source_pixmap = QPixmap()
        self.setObjectName("thumbnailPreviewImage")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(150)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Expanding,
        )

    def set_preview_pixmap(self, pixmap: QPixmap) -> None:
        self._source_pixmap = QPixmap(pixmap)
        self._refresh_pixmap()

    def clear_preview(self, text: str | None = None) -> None:
        self._source_pixmap = QPixmap()
        self.setPixmap(QPixmap())
        self.setText(text or self._empty_text)

    def resizeEvent(self, event: QResizeEvent) -> None:
        super().resizeEvent(event)
        self._refresh_pixmap()

    def _refresh_pixmap(self) -> None:
        if self._source_pixmap.isNull():
            return
        target = self.contentsRect().size()
        if target.width() <= 4 or target.height() <= 4:
            return
        scaled = self._source_pixmap.scaled(
            target,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self.setText("")
        self.setPixmap(scaled)


class CollapsibleSection(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        self._title = title
        self._expanded = bool(expanded)
        self.setObjectName("thumbnailCollapsibleCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_button = QPushButton()
        self.header_button.setObjectName("thumbnailCollapseButton")
        self.header_button.setCheckable(True)
        self.header_button.setChecked(self._expanded)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self.set_expanded)
        outer.addWidget(self.header_button)

        self.body = QWidget()
        self.body.setObjectName("thumbnailCollapsibleBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(18, 14, 18, 18)
        self.body_layout.setSpacing(12)
        outer.addWidget(self.body)

        self._apply_state()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        if self._expanded == expanded:
            self._apply_state()
            return
        self._expanded = expanded
        self._apply_state()
        self.toggled.emit(self._expanded)

    def set_suffix(self, suffix: str) -> None:
        self._suffix = suffix.strip()
        self._apply_state()

    def _apply_state(self) -> None:
        self.header_button.setChecked(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        suffix = f"   {self._suffix}" if getattr(self, "_suffix", "") else ""
        self.header_button.setText(f"{arrow}  {self._title}{suffix}")
        self.body.setVisible(self._expanded)



class ThumbnailTaskRow(QFrame):
    remove_requested = Signal(object)

    def __init__(self, task: ThumbnailTask) -> None:
        super().__init__()
        self.task = task
        self.setObjectName("thumbnailTaskRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 12, 10)
        layout.setSpacing(12)

        text_box = QVBoxLayout()
        text_box.setSpacing(3)

        video_label = QLabel(Path(task.video_path).name)
        video_label.setObjectName("thumbnailTaskTitle")
        video_label.setToolTip(task.video_path)
        image_label = QLabel(f"썸네일: {Path(task.image_path).name}")
        image_label.setObjectName("mutedText")
        image_label.setToolTip(task.image_path)

        text_box.addWidget(video_label)
        text_box.addWidget(image_label)
        layout.addLayout(text_box, 1)

        self.state = "pending"
        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("thumbnailTaskStatus")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setMinimumWidth(84)
        layout.addWidget(self.status_label)

        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("iconTextButton")
        self.remove_button.setToolTip("목록에서 제거")
        self.remove_button.setFixedWidth(34)
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_button)

    def set_status(self, text: str, state: str) -> None:
        self.state = state
        self.status_label.setText(text)
        self.status_label.setProperty("taskState", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class ThumbnailPage(QWidget):
    VIDEO_FILTER = "영상 파일 (*.mp4 *.m4v *.mov *.mkv)"
    IMAGE_FILTER = "이미지 파일 (*.jpg *.jpeg *.png *.webp)"

    def __init__(self) -> None:
        super().__init__()
        self._preferences = load_thumbnail_preferences()
        self._video_path = ""
        self._image_path = ""
        self._probe_worker: ThumbnailProbeWorker | None = None
        self._scan_worker: ThumbnailFolderScanWorker | None = None
        self._batch_worker: ThumbnailBatchWorker | None = None
        self._tasks: list[ThumbnailTask] = []
        self._rows: list[ThumbnailTaskRow] = []
        self._run_mode = ""
        self._active_rows: list[ThumbnailTaskRow] = []
        self._last_output_path = ""

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)

        title = QLabel("영상 썸네일 교체")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "영상 품질을 다시 인코딩하지 않고 내장 썸네일만 안전하게 교체합니다. "
            "MP4·M4V·MOV·MKV 영상을 지원합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        scroll = QScrollArea()
        scroll.setObjectName("thumbnailScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.single_section = self._create_single_card()
        self.batch_section = self._create_queue_card()
        self.options_section = self._create_options_card()
        self.single_section.toggled.connect(self._section_state_changed)
        self.batch_section.toggled.connect(self._section_state_changed)
        self.options_section.toggled.connect(self._section_state_changed)

        layout.addWidget(self.single_section)
        layout.addWidget(self.batch_section)
        layout.addWidget(self.options_section)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.status_card = self._create_status_card()
        self.status_card.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Fixed,
        )
        outer.addWidget(self.status_card, 0)

        self._load_preferences_into_ui()
        self._refresh_queue_state()
        thumbnail_log_path()

    @property
    def has_active_operation(self) -> bool:
        return self._batch_worker is not None and self._batch_worker.isRunning()

    def shutdown(self) -> None:
        self._save_preferences()
        if self._batch_worker is not None and self._batch_worker.isRunning():
            self._batch_worker.cancel()
            self._batch_worker.wait(5000)
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
            self._probe_worker.wait(1200)
        if self._scan_worker is not None and self._scan_worker.isRunning():
            self._scan_worker.requestInterruption()
            self._scan_worker.wait(1200)

    def _create_single_card(self) -> CollapsibleSection:
        section = CollapsibleSection(
            "단일 영상",
            self._preferences.single_expanded,
        )
        layout = section.body_layout

        self.video_edit = DropPathEdit()
        self.video_edit.setPlaceholderText("영상 파일을 끌어놓거나 선택해 주세요")
        self.video_edit.path_dropped.connect(self._set_video_path)
        self.video_select_button = QPushButton("영상 선택")
        self.video_select_button.setObjectName("secondaryButton")
        self.video_select_button.clicked.connect(self._choose_video)

        video_row = QHBoxLayout()
        video_row.setSpacing(10)
        video_row.addWidget(QLabel("영상"))
        video_row.addWidget(self.video_edit, 1)
        video_row.addWidget(self.video_select_button)
        layout.addLayout(video_row)

        self.image_edit = DropPathEdit()
        self.image_edit.setPlaceholderText("교체할 JPG·PNG·WebP 이미지를 끌어놓거나 선택해 주세요")
        self.image_edit.path_dropped.connect(self._set_image_path)
        self.image_select_button = QPushButton("이미지 선택")
        self.image_select_button.setObjectName("secondaryButton")
        self.image_select_button.clicked.connect(self._choose_image)

        image_row = QHBoxLayout()
        image_row.setSpacing(10)
        image_row.addWidget(QLabel("이미지"))
        image_row.addWidget(self.image_edit, 1)
        image_row.addWidget(self.image_select_button)
        layout.addLayout(image_row)

        preview_box = QFrame()
        preview_box.setObjectName("thumbnailPreviewBox")
        preview_layout = QHBoxLayout(preview_box)
        preview_layout.setContentsMargins(12, 12, 12, 12)
        preview_layout.setSpacing(12)

        current_col = QVBoxLayout()
        current_title = QLabel("현재 내장 썸네일")
        current_title.setObjectName("previewOptionName")
        self.current_preview = ImagePreviewLabel("내장 썸네일 미리보기")
        current_col.addWidget(current_title)
        current_col.addWidget(self.current_preview)

        new_col = QVBoxLayout()
        new_title = QLabel("교체할 썸네일")
        new_title.setObjectName("previewOptionName")
        self.new_preview = ImagePreviewLabel("새 이미지 미리보기")
        new_col.addWidget(new_title)
        new_col.addWidget(self.new_preview)

        preview_layout.addLayout(current_col, 1)
        preview_layout.addLayout(new_col, 1)
        layout.addWidget(preview_box)

        action_row = QHBoxLayout()
        action_row.addStretch()
        self.add_queue_button = QPushButton("목록에 추가")
        self.add_queue_button.setObjectName("secondaryButton")
        self.add_queue_button.clicked.connect(self._add_current_to_queue)
        self.replace_now_button = QPushButton("지금 교체")
        self.replace_now_button.setObjectName("primaryButton")
        self.replace_now_button.clicked.connect(self._replace_current_now)
        action_row.addWidget(self.add_queue_button)
        action_row.addWidget(self.replace_now_button)
        layout.addLayout(action_row)
        return section

    def _create_queue_card(self) -> CollapsibleSection:
        section = CollapsibleSection(
            "여러 영상",
            self._preferences.batch_expanded,
        )
        layout = section.body_layout
        header = QHBoxLayout()
        self.queue_count_label = QLabel("0개")
        self.queue_count_label.setObjectName("mutedText")
        self.folder_button = QPushButton("폴더 통째로 추가")
        self.folder_button.setObjectName("secondaryButton")
        self.folder_button.clicked.connect(self._choose_folder)
        self.clear_button = QPushButton("목록 지우기")
        self.clear_button.setObjectName("secondaryButton")
        self.clear_button.clicked.connect(self._clear_queue)

        header.addWidget(self.queue_count_label)
        header.addStretch()
        header.addWidget(self.folder_button)
        header.addWidget(self.clear_button)
        layout.addLayout(header)

        hint = QLabel(
            "같은 이름의 이미지(예: video.mp4 ↔ video.jpg)를 자동으로 찾아 목록에 추가합니다. "
            "하위 폴더도 함께 확인합니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setObjectName("thumbnailQueueScroll")
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setMinimumHeight(160)
        self.queue_scroll.setMaximumHeight(320)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.queue_content = QWidget()
        self.queue_layout = QVBoxLayout(self.queue_content)
        self.queue_layout.setContentsMargins(4, 4, 4, 4)
        self.queue_layout.setSpacing(7)
        self.queue_layout.addStretch()
        self.queue_scroll.setWidget(self.queue_content)
        layout.addWidget(self.queue_scroll)

        self.queue_empty_label = QLabel("아직 추가한 작업이 없습니다.")
        self.queue_empty_label.setObjectName("thumbnailQueueEmpty")
        self.queue_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_layout.insertWidget(0, self.queue_empty_label)

        batch_action_row = QHBoxLayout()
        batch_action_row.addStretch()
        self.start_batch_button = QPushButton("여러 영상 교체 시작")
        self.start_batch_button.setObjectName("primaryButton")
        self.start_batch_button.clicked.connect(self._start_batch)
        batch_action_row.addWidget(self.start_batch_button)
        layout.addLayout(batch_action_row)
        return section

    def _create_options_card(self) -> CollapsibleSection:
        section = CollapsibleSection(
            "처리 옵션",
            self._preferences.options_expanded,
        )
        layout = section.body_layout

        self.auto_find_check = QCheckBox("영상 이름으로 이미지 자동 찾기")
        self.auto_find_check.setObjectName("settingsCheckBox")
        self.delete_image_check = QCheckBox("성공하면 사용한 이미지 삭제")
        self.delete_image_check.setObjectName("settingsCheckBox")
        self.auto_find_check.toggled.connect(self._preferences_changed)
        self.delete_image_check.toggled.connect(self._preferences_changed)

        check_row = QHBoxLayout()
        check_row.setSpacing(22)
        check_row.addWidget(self.auto_find_check)
        check_row.addWidget(self.delete_image_check)
        check_row.addStretch()
        layout.addLayout(check_row)

        self.overwrite_radio = QRadioButton("원본 영상에 안전하게 적용")
        self.new_file_radio = QRadioButton("새 파일로 저장 (_thumbnail)")
        self.overwrite_radio.setObjectName("settingsRadioButton")
        self.new_file_radio.setObjectName("settingsRadioButton")
        self.output_group = QButtonGroup(self)
        self.output_group.setExclusive(True)
        self.output_group.addButton(self.overwrite_radio)
        self.output_group.addButton(self.new_file_radio)
        self.overwrite_radio.toggled.connect(self._preferences_changed)
        self.new_file_radio.toggled.connect(self._preferences_changed)

        output_row = QHBoxLayout()
        output_row.setSpacing(22)
        output_row.addWidget(self.overwrite_radio)
        output_row.addWidget(self.new_file_radio)
        output_row.addStretch()
        layout.addLayout(output_row)

        warning = QLabel(
            "원본 적용도 먼저 임시 영상을 만들고 썸네일 삽입을 확인한 뒤 교체합니다. "
            "영상·오디오는 재인코딩하지 않습니다. 이미지 삭제 옵션은 기본적으로 꺼져 있습니다."
        )
        warning.setObjectName("mutedText")
        warning.setWordWrap(True)
        layout.addWidget(warning)
        return section

    def _create_status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("thumbnailStatusBar")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)

        summary_row = QHBoxLayout()
        summary_row.setSpacing(10)

        title = QLabel("처리 상태")
        title.setObjectName("thumbnailStatusTitle")
        summary_row.addWidget(title)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("thumbnailStatusText")
        self.status_label.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )
        summary_row.addWidget(self.status_label, 1)

        self.status_counter = QLabel("")
        self.status_counter.setObjectName("thumbnailStatusCounter")
        summary_row.addWidget(self.status_counter)

        self.details_button = QPushButton("자세히")
        self.details_button.setObjectName("thumbnailStatusDetailsButton")
        self.details_button.setIcon(
            QIcon(str(themed_icon_path(SPIN_DOWN_ICON_PATH)))
        )
        self.details_button.setIconSize(QSize(12, 8))
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_status_details)
        summary_row.addWidget(self.details_button)
        layout.addLayout(summary_row)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("thumbnailStatusProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, 1)

        self.stop_button = QPushButton("■ 중지")
        self.stop_button.setObjectName("thumbnailStatusStopButton")
        self.stop_button.clicked.connect(self._stop_operation)
        self.stop_button.setVisible(False)
        progress_row.addWidget(self.stop_button)
        self.progress_row_widget = QWidget()
        self.progress_row_widget.setObjectName("thumbnailStatusProgressRow")
        progress_wrapper = QHBoxLayout(self.progress_row_widget)
        progress_wrapper.setContentsMargins(0, 0, 0, 0)
        progress_wrapper.setSpacing(0)
        progress_wrapper.addLayout(progress_row)
        self.progress_row_widget.setVisible(False)
        layout.addWidget(self.progress_row_widget)

        self.status_detail_frame = QFrame()
        self.status_detail_frame.setObjectName("thumbnailStatusDetail")
        detail_layout = QVBoxLayout(self.status_detail_frame)
        detail_layout.setContentsMargins(10, 9, 10, 9)
        detail_layout.setSpacing(8)

        self.status_detail_label = QLabel("아직 상세 작업 내용이 없습니다.")
        self.status_detail_label.setObjectName("thumbnailStatusDetailText")
        self.status_detail_label.setWordWrap(True)
        detail_layout.addWidget(self.status_detail_label)

        detail_buttons = QHBoxLayout()
        detail_buttons.addStretch()
        self.open_result_button = QPushButton("결과 폴더 열기")
        self.open_result_button.setObjectName("secondaryButton")
        self.open_result_button.clicked.connect(self._open_result_folder)
        self.log_button = QPushButton("로그 폴더 열기")
        self.log_button.setObjectName("secondaryButton")
        self.log_button.clicked.connect(self._open_log_folder)
        detail_buttons.addWidget(self.open_result_button)
        detail_buttons.addWidget(self.log_button)
        detail_layout.addLayout(detail_buttons)

        self.status_detail_frame.setVisible(False)
        layout.addWidget(self.status_detail_frame)
        return card

    def _toggle_status_details(self, expanded: bool) -> None:
        self.status_detail_frame.setVisible(bool(expanded))
        icon_path = SPIN_UP_ICON_PATH if expanded else SPIN_DOWN_ICON_PATH

        self.details_button.setIcon(QIcon(str(themed_icon_path(icon_path))))

    def _set_status(
        self,
        summary: str,
        detail: str | None = None,
        *,
        show_progress: bool | None = None,
    ) -> None:
        self.status_label.setText(summary)
        self.status_detail_label.setText(detail or summary)
        if show_progress is not None:
            self.progress_row_widget.setVisible(show_progress)
            self.progress_bar.setVisible(show_progress)
            self.stop_button.setVisible(show_progress)

    def _load_preferences_into_ui(self) -> None:
        self.auto_find_check.setChecked(self._preferences.auto_find_image)
        self.delete_image_check.setChecked(self._preferences.delete_image_on_success)
        if self._preferences.output_mode == OUTPUT_NEW_FILE:
            self.new_file_radio.setChecked(True)
        else:
            self.overwrite_radio.setChecked(True)

    def _preferences_changed(self, checked: bool = False) -> None:
        del checked
        self._save_preferences()
        if self.auto_find_check.isChecked() and self._video_path and not self._image_path:
            match = find_matching_image(self._video_path)
            if match is not None:
                self._set_image_path(str(match))

    def _section_state_changed(self, expanded: bool = False) -> None:
        del expanded
        self._save_preferences()

    def _save_preferences(self) -> None:
        single_expanded = getattr(
            getattr(self, "single_section", None),
            "expanded",
            self._preferences.single_expanded,
        )
        batch_expanded = getattr(
            getattr(self, "batch_section", None),
            "expanded",
            self._preferences.batch_expanded,
        )
        options_expanded = getattr(
            getattr(self, "options_section", None),
            "expanded",
            self._preferences.options_expanded,
        )
        self._preferences = ThumbnailPreferences(
            auto_find_image=self.auto_find_check.isChecked(),
            delete_image_on_success=self.delete_image_check.isChecked(),
            output_mode=(
                OUTPUT_NEW_FILE if self.new_file_radio.isChecked() else OUTPUT_OVERWRITE
            ),
            single_expanded=bool(single_expanded),
            batch_expanded=bool(batch_expanded),
            options_expanded=bool(options_expanded),
        )
        save_thumbnail_preferences(self._preferences)

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "영상 선택", "", self.VIDEO_FILTER)
        if path:
            self._set_video_path(path)

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "썸네일 이미지 선택", "", self.IMAGE_FILTER)
        if path:
            self._set_image_path(path)

    def _set_video_path(self, path: str) -> None:
        video = Path(path)
        if not video.is_file() or video.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            self._show_warning(
                "영상 확인",
                "MP4, M4V, MOV, MKV 영상 파일을 선택해 주세요.",
            )
            return
        self._video_path = str(video)
        self.video_edit.setText(str(video))
        self._image_path = ""
        self.image_edit.clear()
        self.new_preview.clear_preview("새 이미지 미리보기")
        self.current_preview.clear_preview("현재 내장 썸네일을 확인 중…")
        self._start_probe(str(video))
        if self.auto_find_check.isChecked():
            match = find_matching_image(video)
            if match is not None:
                self._set_image_path(str(match))
        self._refresh_buttons()

    def _set_image_path(self, path: str) -> None:
        image = Path(path)
        if not image.is_file() or image.suffix.lower() not in SUPPORTED_IMAGE_EXTENSIONS:
            self._show_warning("이미지 확인", "JPG, JPEG, PNG, WebP 이미지를 선택해 주세요.")
            return
        self._image_path = str(image)
        self.image_edit.setText(str(image))
        pixmap = QPixmap(str(image))
        if pixmap.isNull():
            self.new_preview.clear_preview("이미지를 미리 볼 수 없습니다.")
        else:
            self.new_preview.set_preview_pixmap(pixmap)
        self._refresh_buttons()

    def _start_probe(self, video_path: str) -> None:
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
        worker = ThumbnailProbeWorker(video_path)
        self._probe_worker = worker
        worker.succeeded.connect(self._probe_succeeded)
        worker.failed.connect(self._probe_failed)
        worker.finished.connect(self._probe_finished)
        worker.start()

    def _probe_succeeded(self, result: ThumbnailProbeResult) -> None:
        if result.video_path != self._video_path:
            return
        if result.thumbnail_bytes:
            pixmap = QPixmap()
            if pixmap.loadFromData(result.thumbnail_bytes):
                self.current_preview.set_preview_pixmap(pixmap)
                return
        if result.has_thumbnail:
            self.current_preview.clear_preview("내장 썸네일은 있지만 미리보기를 만들지 못했습니다.")
        else:
            self.current_preview.clear_preview("현재 내장 썸네일이 없습니다.")

    def _probe_failed(self, message: str, detail: str) -> None:
        self.current_preview.clear_preview("현재 썸네일을 확인하지 못했습니다.")
        self._set_status(message, detail or message)

    def _probe_finished(self) -> None:
        worker = self._probe_worker
        if worker is not None:
            worker.deleteLater()
        self._probe_worker = None

    def _current_task(self) -> ThumbnailTask | None:
        if not self._video_path or not self._image_path:
            return None
        return ThumbnailTask(self._video_path, self._image_path)

    def _reset_single_inputs(self) -> None:
        self._video_path = ""
        self._image_path = ""
        self.video_edit.clear()
        self.image_edit.clear()
        self.current_preview.clear_preview("영상을 선택하면 현재 내장 썸네일을 표시합니다.")
        self.new_preview.clear_preview("새 이미지 미리보기")
        self._refresh_buttons()

    def _add_current_to_queue(self) -> None:
        task = self._current_task()
        if task is None:
            self._show_info("목록 추가", "영상과 썸네일 이미지를 먼저 선택해 주세요.")
            return
        if self._add_task(task):
            self._set_status("여러 영상 목록에 작업 추가됨")
            self._reset_single_inputs()

    def _replace_current_now(self) -> None:
        task = self._current_task()
        if task is None:
            self._show_info("썸네일 교체", "영상과 썸네일 이미지를 먼저 선택해 주세요.")
            return
        self._start_worker([task], "direct")

    def _add_task(self, task: ThumbnailTask) -> bool:
        video_key = str(Path(task.video_path).resolve()).lower()
        for existing in self._tasks:
            try:
                existing_key = str(Path(existing.video_path).resolve()).lower()
            except OSError:
                existing_key = existing.video_path.lower()
            if existing_key == video_key:
                return False

        row = ThumbnailTaskRow(task)
        row.remove_requested.connect(self._remove_row)
        self._tasks.append(task)
        self._rows.append(row)
        self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)
        self._refresh_queue_state()
        return True

    def _remove_row(self, row: ThumbnailTaskRow) -> None:
        if self.has_active_operation:
            return
        if row not in self._rows:
            return
        index = self._rows.index(row)
        self._rows.pop(index)
        self._tasks.pop(index)
        row.setParent(None)
        row.deleteLater()
        self._refresh_queue_state()

    def _clear_queue(self) -> None:
        if self.has_active_operation:
            return
        for row in self._rows:
            row.setParent(None)
            row.deleteLater()
        self._tasks.clear()
        self._rows.clear()
        self._refresh_queue_state()

    def _choose_folder(self) -> None:
        if self.has_active_operation or (self._scan_worker is not None and self._scan_worker.isRunning()):
            return
        folder = QFileDialog.getExistingDirectory(self, "영상과 이미지가 있는 폴더 선택")
        if not folder:
            return
        self._set_status("폴더의 영상·이미지 검색 중…", folder)
        worker = ThumbnailFolderScanWorker(folder)
        self._scan_worker = worker
        worker.succeeded.connect(self._folder_scan_succeeded)
        worker.failed.connect(self._folder_scan_failed)
        worker.finished.connect(self._folder_scan_finished)
        worker.start()

    def _folder_scan_succeeded(self, pairs: object) -> None:
        added = 0
        if isinstance(pairs, list):
            for pair in pairs:
                if not isinstance(pair, tuple) or len(pair) != 2:
                    continue
                video, image = pair
                if self._add_task(ThumbnailTask(str(video), str(image))):
                    added += 1
        if added:
            self._set_status(f"{added}개의 영상·이미지 쌍이 목록에 추가됨")
        else:
            self._set_status("새로 추가할 영상·이미지 쌍 없음")

    def _folder_scan_failed(self, detail: str) -> None:
        self._set_status("폴더 확인 실패", detail)
        self._show_warning("폴더 확인 실패", detail)

    def _folder_scan_finished(self) -> None:
        worker = self._scan_worker
        if worker is not None:
            worker.deleteLater()
        self._scan_worker = None

    def _start_batch(self) -> None:
        pairs = [
            (task, row)
            for task, row in zip(self._tasks, self._rows)
            if row.state != "done"
        ]
        if not pairs:
            self._show_info("여러 영상", "처리할 대기 작업이 없습니다.")
            return
        tasks = [task for task, _ in pairs]
        self._active_rows = [row for _, row in pairs]
        for row in self._active_rows:
            row.set_status("대기 중", "pending")
        self._start_worker(tasks, "batch")

    def _start_worker(self, tasks: list[ThumbnailTask], mode: str) -> None:
        if self.has_active_operation:
            return
        if not tasks:
            return
        self._save_preferences()
        options = ThumbnailOptions(
            output_mode=self._preferences.output_mode,
            delete_image_on_success=self._preferences.delete_image_on_success,
        )
        worker = ThumbnailBatchWorker(tasks, options)
        self._batch_worker = worker
        self._run_mode = mode
        if mode != "batch":
            self._active_rows = []
        worker.task_started.connect(self._task_started)
        worker.task_succeeded.connect(self._task_succeeded)
        worker.task_failed.connect(self._task_failed)
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.cancelled.connect(self._operation_cancelled)
        worker.completed.connect(self._operation_completed)
        worker.finished.connect(self._operation_finished)

        self.progress_bar.setValue(0)
        self.status_counter.setText(f"0 / {len(tasks)}")
        self._set_status(
            "썸네일 교체를 준비 중…",
            f"총 {len(tasks)}개 작업을 순서대로 처리합니다.",
            show_progress=True,
        )
        self._set_controls_enabled(False)
        self.stop_button.setEnabled(True)
        worker.start()

    def _stop_operation(self) -> None:
        if self._batch_worker is None or not self._batch_worker.isRunning():
            return
        self._set_status("현재 작업 중지 중…", show_progress=True)
        self.stop_button.setEnabled(False)
        self._batch_worker.cancel()

    def _task_started(self, index: int, total: int, video_path: str) -> None:
        self.status_counter.setText(f"{index + 1} / {total}")
        filename = Path(video_path).name
        self._set_status(
            f"교체 중 · {filename}",
            f"{index + 1}/{total}번째 작업을 처리 중입니다.\n{video_path}",
            show_progress=True,
        )
        if self._run_mode == "batch" and 0 <= index < len(self._active_rows):
            self._active_rows[index].set_status("처리 중", "working")

    def _task_succeeded(self, index: int, output_path: str) -> None:
        self._last_output_path = output_path
        if self._run_mode == "batch" and 0 <= index < len(self._active_rows):
            self._active_rows[index].set_status("완료", "done")

    def _task_failed(self, index: int, message: str, detail: str) -> None:
        if self._run_mode == "batch" and 0 <= index < len(self._active_rows):
            self._active_rows[index].set_status("실패", "error")
            self._active_rows[index].status_label.setToolTip(detail or message)
        self._set_status(message, detail or message)

    def _operation_cancelled(self) -> None:
        self._set_status("썸네일 교체 중지됨", show_progress=False)

    def _operation_completed(self, success_count: int, fail_count: int) -> None:
        was_direct = self._run_mode == "direct"
        self.progress_bar.setValue(100)
        if fail_count:
            self._set_status(
                f"작업 완료 · 성공 {success_count} · 실패 {fail_count}",
                "실패 항목은 목록에 유지됩니다. 자세한 원인은 로그 폴더에서 확인할 수 있습니다.",
                show_progress=False,
            )
        elif was_direct:
            completed_name = Path(self._last_output_path).name if self._last_output_path else "영상"
            detail = "단일 영상 입력은 다음 작업을 위해 초기화했습니다."
            if self._last_output_path:
                detail += f"\n결과: {self._last_output_path}"
            self._set_status(
                f"교체 완료 · {completed_name}",
                detail,
                show_progress=False,
            )
            self._reset_single_inputs()
        else:
            self._set_status(
                f"여러 영상 교체 완료 · {success_count}개",
                f"대기 목록의 {success_count}개 작업을 모두 처리했습니다.",
                show_progress=False,
            )
        if success_count > 0 and fail_count == 0:
            play_completion_sound()

    def _operation_finished(self) -> None:
        worker = self._batch_worker
        if worker is not None:
            worker.deleteLater()
        self._batch_worker = None
        self._run_mode = ""
        self._active_rows = []
        self._set_controls_enabled(True)
        self.stop_button.setEnabled(False)
        self.stop_button.setVisible(False)
        if self.progress_bar.value() < 100:
            self.progress_row_widget.setVisible(False)
        self._refresh_buttons()

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.video_edit.setEnabled(enabled)
        self.image_edit.setEnabled(enabled)
        self.video_select_button.setEnabled(enabled)
        self.image_select_button.setEnabled(enabled)
        self.folder_button.setEnabled(enabled)
        self.add_queue_button.setEnabled(enabled)
        self.replace_now_button.setEnabled(enabled and self._current_task() is not None)
        self.auto_find_check.setEnabled(enabled)
        self.delete_image_check.setEnabled(enabled)
        self.overwrite_radio.setEnabled(enabled)
        self.new_file_radio.setEnabled(enabled)
        self.clear_button.setEnabled(enabled and bool(self._tasks))
        for row in self._rows:
            row.remove_button.setEnabled(enabled)
        self.start_batch_button.setEnabled(enabled and bool(self._tasks))

    def _refresh_buttons(self) -> None:
        active = self.has_active_operation
        ready = self._current_task() is not None
        self.add_queue_button.setEnabled(ready and not active)
        self.replace_now_button.setEnabled(ready and not active)
        self.start_batch_button.setEnabled(bool(self._tasks) and not active)
        self.clear_button.setEnabled(bool(self._tasks) and not active)
        self.stop_button.setEnabled(active)
        self.stop_button.setVisible(active)
        self.open_result_button.setEnabled(bool(self._last_output_path))

    def _refresh_queue_state(self) -> None:
        count = len(self._tasks)
        self.queue_count_label.setText(f"{count}개")
        if hasattr(self, "batch_section"):
            self.batch_section.set_suffix(f"{count}개")
        self.queue_empty_label.setVisible(count == 0)
        self._refresh_buttons()

    def _open_result_folder(self) -> None:
        if not self._last_output_path:
            self._show_info("결과 폴더", "아직 완료된 결과가 없습니다.")
            return
        folder = Path(self._last_output_path).parent
        if not folder.is_dir():
            self._show_warning("결과 폴더", "결과 폴더를 찾을 수 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_log_folder(self) -> None:
        RRV_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RRV_LOGS_DIR)))

    def _show_warning(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        box.exec()

    def _show_info(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        box.exec()
