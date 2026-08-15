from __future__ import annotations

from pathlib import Path
import re

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFileDialog,
    QFontComboBox,
    QFrame,
    QGridLayout,
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
from app.paths import RRV_LOGS_DIR
from app.snapshot_log import snapshot_log_path
from app.snapshot_preferences import SnapshotPreferences, load_snapshot_preferences, save_snapshot_preferences
from core.snapshot_models import OUTPUT_CUSTOM, OUTPUT_SOURCE, SIZE_HEIGHT, SIZE_WIDTH, SnapshotOptions, SnapshotProbeResult, SnapshotResult
from services.snapshot_service import SUPPORTED_VIDEO_EXTENSIONS
from ui.widgets.common import NoWheelSpinBox
from workers.snapshot_worker import SnapshotBatchWorker, SnapshotProbeWorker, SnapshotWorker


VIDEO_FILTER = "영상 파일 (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.ts)"


class SnapshotDropFrame(QFrame):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("snapshotDropArea")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        urls = event.mimeData().urls()
        if any(url.isLocalFile() for url in urls):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.file_dropped.emit(url.toLocalFile())
                event.acceptProposedAction()
                return
        event.ignore()


class SnapshotCollapsibleSection(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        self._title = title
        self._expanded = bool(expanded)
        self._suffix = ""
        self.setObjectName("snapshotCollapsibleCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_button = QPushButton()
        self.header_button.setObjectName("snapshotCollapseButton")
        self.header_button.setCheckable(True)
        self.header_button.setChecked(self._expanded)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self.set_expanded)
        outer.addWidget(self.header_button)

        self.body = QWidget()
        self.body.setObjectName("snapshotCollapsibleBody")
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
        changed = expanded != self._expanded
        self._expanded = expanded
        self._apply_state()
        if changed:
            self.toggled.emit(self._expanded)

    def set_suffix(self, suffix: str) -> None:
        self._suffix = suffix.strip()
        self._apply_state()

    def _apply_state(self) -> None:
        self.header_button.setChecked(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        suffix = f"   {self._suffix}" if self._suffix else ""
        self.header_button.setText(f"{arrow}  {self._title}{suffix}")
        self.body.setVisible(self._expanded)


class SnapshotElidedLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        # Start empty so the full filename never becomes the layout's preferred width.
        super().__init__("")
        self._full_text = text
        self.setMinimumWidth(0)
        # Ignored is important here: the label must accept the width the row actually has,
        # then elide its text to that width instead of forcing the row wider.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._apply_elide()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._apply_elide()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(0)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply_elide()

    def _apply_elide(self) -> None:
        width = max(20, self.contentsRect().width())
        metrics = QFontMetrics(self.font())
        QLabel.setText(self, metrics.elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


class SnapshotTaskRow(QFrame):
    remove_requested = Signal(object)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.state = "pending"
        self.output_path = ""
        self.setObjectName("snapshotTaskRow")
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 12, 9)
        layout.setSpacing(12)

        self.name_label = SnapshotElidedLabel(Path(path).name)
        self.name_label.setObjectName("snapshotTaskTitle")
        self.name_label.setToolTip(path)
        layout.addWidget(self.name_label, 1)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("snapshotTaskStatus")
        self.status_label.setMinimumWidth(90)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("iconTextButton")
        self.remove_button.setFixedWidth(34)
        self.remove_button.setToolTip("목록에서 제거")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_button)

    def set_status(self, text: str, state: str) -> None:
        self.state = state
        self.status_label.setText(text)
        self.status_label.setProperty("taskState", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class SnapshotPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._preferences = load_snapshot_preferences()
        self._input_path = ""
        self._probe_result: SnapshotProbeResult | None = None
        self._probe_worker: SnapshotProbeWorker | None = None
        self._worker: SnapshotWorker | None = None
        self._batch_worker: SnapshotBatchWorker | None = None
        self._batch_paths: list[str] = []
        self._batch_rows: list[SnapshotTaskRow] = []
        self._run_mode = ""
        self._last_output_path = ""
        self._batch_current = 0
        self._batch_total = 0
        self._batch_success = 0
        self._batch_fail = 0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_preferences)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)

        title = QLabel("영상 스냅샷")
        title.setObjectName("sectionTitle")
        description = QLabel("영상의 여러 장면을 일정한 간격으로 추출해 한 장의 스냅샷 시트로 구성합니다.")
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        scroll = QScrollArea()
        scroll.setObjectName("snapshotScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.single_section = self._create_single_section()
        self.batch_section = self._create_batch_section()
        self.layout_section = self._create_layout_section()
        self.display_section = self._create_display_section()
        self.output_section = self._create_output_section()

        for section in (
            self.single_section,
            self.batch_section,
            self.layout_section,
            self.display_section,
            self.output_section,
        ):
            section.toggled.connect(self._section_state_changed)
            layout.addWidget(section)
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        self.status_bar = self._create_status_bar()
        self.status_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer.addWidget(self.status_bar, 0)

        self._load_preferences_into_ui()
        self._refresh_batch_state()
        self._refresh_section_summaries()
        self._refresh_ui_state()
        snapshot_log_path()

    @property
    def has_active_operation(self) -> bool:
        single = self._worker is not None and self._worker.isRunning()
        batch = self._batch_worker is not None and self._batch_worker.isRunning()
        return single or batch

    def shutdown(self) -> None:
        self._save_preferences()
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        if self._batch_worker is not None and self._batch_worker.isRunning():
            self._batch_worker.cancel()
            self._batch_worker.wait(5000)
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
            self._probe_worker.wait(1200)

    def _create_single_section(self) -> SnapshotCollapsibleSection:
        section = SnapshotCollapsibleSection("단일 영상", self._preferences.single_expanded)
        layout = section.body_layout

        drop = SnapshotDropFrame()
        drop.file_dropped.connect(self._set_input_file)
        drop_layout = QHBoxLayout(drop)
        drop_layout.setContentsMargins(14, 12, 12, 12)
        drop_layout.setSpacing(10)

        self.input_edit = QLineEdit()
        self.input_edit.setObjectName("snapshotPathInput")
        self.input_edit.setReadOnly(True)
        self.input_edit.setPlaceholderText("영상을 끌어놓거나 선택해 주세요")
        drop_layout.addWidget(self.input_edit, 1)

        choose_button = QPushButton("영상 선택")
        choose_button.setObjectName("secondaryButton")
        choose_button.clicked.connect(self._choose_input_file)
        drop_layout.addWidget(choose_button)
        self.single_choose_button = choose_button
        layout.addWidget(drop)

        self.input_info_label = QLabel("영상을 선택하면 길이와 해상도를 확인합니다.")
        self.input_info_label.setObjectName("mutedText")
        layout.addWidget(self.input_info_label)

        actions = QHBoxLayout()
        actions.addStretch()
        self.single_start_button = QPushButton("스냅샷 생성")
        self.single_start_button.setObjectName("primaryButton")
        self.single_start_button.clicked.connect(self._start_single)
        actions.addWidget(self.single_start_button)
        layout.addLayout(actions)
        return section

    def _create_batch_section(self) -> SnapshotCollapsibleSection:
        section = SnapshotCollapsibleSection("여러 영상", self._preferences.batch_expanded)
        layout = section.body_layout

        buttons = QHBoxLayout()
        self.batch_files_button = QPushButton("파일 여러 개 추가")
        self.batch_files_button.setObjectName("secondaryButton")
        self.batch_files_button.clicked.connect(self._choose_batch_files)
        buttons.addWidget(self.batch_files_button)

        self.batch_folder_button = QPushButton("폴더 추가")
        self.batch_folder_button.setObjectName("secondaryButton")
        self.batch_folder_button.clicked.connect(self._choose_batch_folder)
        buttons.addWidget(self.batch_folder_button)

        self.batch_clear_button = QPushButton("목록 지우기")
        self.batch_clear_button.setObjectName("secondaryButton")
        self.batch_clear_button.clicked.connect(self._clear_batch)
        buttons.addWidget(self.batch_clear_button)
        buttons.addStretch()
        layout.addLayout(buttons)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setObjectName("snapshotQueueScroll")
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.queue_scroll.setMinimumHeight(185)
        self.queue_scroll.setMaximumHeight(300)

        queue_content = QWidget()
        self.queue_layout = QVBoxLayout(queue_content)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(7)
        self.queue_empty_label = QLabel("아직 추가된 영상이 없습니다.")
        self.queue_empty_label.setObjectName("snapshotQueueEmpty")
        self.queue_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_layout.addWidget(self.queue_empty_label)
        self.queue_layout.addStretch()
        self.queue_scroll.setWidget(queue_content)
        layout.addWidget(self.queue_scroll)

        bottom = QHBoxLayout()
        self.batch_count_label = QLabel("0개 영상")
        self.batch_count_label.setObjectName("mutedText")
        bottom.addWidget(self.batch_count_label)
        bottom.addStretch()
        self.batch_start_button = QPushButton("여러 영상 스냅샷 생성")
        self.batch_start_button.setObjectName("primaryButton")
        self.batch_start_button.clicked.connect(self._start_batch)
        bottom.addWidget(self.batch_start_button)
        layout.addLayout(bottom)
        return section

    def _create_layout_section(self) -> SnapshotCollapsibleSection:
        section = SnapshotCollapsibleSection("스냅샷 구성", self._preferences.layout_expanded)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        grid.addWidget(QLabel("가로"), 0, 0)
        self.columns_spin = NoWheelSpinBox()
        self.columns_spin.setObjectName("converterSpinBox")
        self.columns_spin.setRange(1, 12)
        self.columns_spin.setSuffix(" 칸")
        grid.addWidget(self.columns_spin, 0, 1)

        grid.addWidget(QLabel("세로"), 0, 2)
        self.rows_spin = NoWheelSpinBox()
        self.rows_spin.setObjectName("converterSpinBox")
        self.rows_spin.setRange(1, 30)
        self.rows_spin.setSuffix(" 칸")
        grid.addWidget(self.rows_spin, 0, 3)

        self.total_shots_label = QLabel("총 48장")
        self.total_shots_label.setObjectName("converterValueLabel")
        grid.addWidget(self.total_shots_label, 0, 4)

        grid.addWidget(QLabel("완성 이미지"), 1, 0)
        mode_box = QHBoxLayout()
        self.size_width_radio = QRadioButton("가로 기준")
        self.size_width_radio.setObjectName("settingsRadioButton")
        self.size_height_radio = QRadioButton("세로 기준")
        self.size_height_radio.setObjectName("settingsRadioButton")
        self.size_group = QButtonGroup(self)
        self.size_group.addButton(self.size_width_radio)
        self.size_group.addButton(self.size_height_radio)
        mode_box.addWidget(self.size_width_radio)
        mode_box.addWidget(self.size_height_radio)
        grid.addLayout(mode_box, 1, 1, 1, 2)

        self.target_size_spin = NoWheelSpinBox()
        self.target_size_spin.setObjectName("converterSpinBox")
        self.target_size_spin.setRange(480, 10000)
        self.target_size_spin.setSingleStep(100)
        self.target_size_spin.setSuffix(" px")
        grid.addWidget(self.target_size_spin, 1, 3)

        grid.addWidget(QLabel("프레임 여백"), 2, 0)
        self.margin_spin = NoWheelSpinBox()
        self.margin_spin.setObjectName("converterSpinBox")
        self.margin_spin.setRange(0, 100)
        self.margin_spin.setSuffix(" px")
        grid.addWidget(self.margin_spin, 2, 1)
        grid.setColumnStretch(5, 1)

        section.body_layout.addLayout(grid)
        for widget in (self.columns_spin, self.rows_spin, self.target_size_spin, self.margin_spin):
            widget.valueChanged.connect(self._controls_changed)
        self.size_width_radio.toggled.connect(self._controls_changed)
        self.size_height_radio.toggled.connect(self._controls_changed)
        return section

    def _create_display_section(self) -> SnapshotCollapsibleSection:
        section = SnapshotCollapsibleSection("표시 옵션", self._preferences.display_expanded)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        self.show_info_check = QCheckBox("영상 정보 표시")
        self.show_time_check = QCheckBox("각 장면에 시간 표시")
        self.show_info_check.setObjectName("previewCheckBox")
        self.show_time_check.setObjectName("previewCheckBox")
        grid.addWidget(self.show_info_check, 0, 0, 1, 2)
        grid.addWidget(self.show_time_check, 0, 2, 1, 2)

        grid.addWidget(QLabel("글꼴"), 1, 0)
        self.font_combo = QFontComboBox()
        self.font_combo.setObjectName("snapshotFontCombo")
        self.font_combo.setMaximumWidth(360)
        self.font_combo.setToolTip("Windows에 설치된 글꼴 중 스냅샷에 사용할 글꼴을 선택합니다.")
        grid.addWidget(self.font_combo, 1, 1, 1, 3)

        grid.addWidget(QLabel("정보 글자"), 2, 0)
        self.info_size_spin = NoWheelSpinBox()
        self.info_size_spin.setObjectName("converterSpinBox")
        self.info_size_spin.setRange(10, 72)
        self.info_size_spin.setSuffix(" pt")
        grid.addWidget(self.info_size_spin, 2, 1)

        grid.addWidget(QLabel("시간 글자"), 2, 2)
        self.time_size_spin = NoWheelSpinBox()
        self.time_size_spin.setObjectName("converterSpinBox")
        self.time_size_spin.setRange(8, 64)
        self.time_size_spin.setSuffix(" pt")
        grid.addWidget(self.time_size_spin, 2, 3)
        grid.setColumnStretch(4, 1)
        section.body_layout.addLayout(grid)

        self.show_info_check.toggled.connect(self._controls_changed)
        self.show_time_check.toggled.connect(self._controls_changed)
        self.font_combo.currentFontChanged.connect(self._controls_changed)
        self.info_size_spin.valueChanged.connect(self._controls_changed)
        self.time_size_spin.valueChanged.connect(self._controls_changed)
        return section

    def _create_output_section(self) -> SnapshotCollapsibleSection:
        section = SnapshotCollapsibleSection("출력 위치", self._preferences.output_expanded)
        layout = section.body_layout

        mode_line = QHBoxLayout()
        self.output_source_radio = QRadioButton("영상과 같은 폴더")
        self.output_source_radio.setObjectName("settingsRadioButton")
        self.output_custom_radio = QRadioButton("지정 폴더")
        self.output_custom_radio.setObjectName("settingsRadioButton")
        self.output_group = QButtonGroup(self)
        self.output_group.addButton(self.output_source_radio)
        self.output_group.addButton(self.output_custom_radio)
        mode_line.addWidget(self.output_source_radio)
        mode_line.addWidget(self.output_custom_radio)
        mode_line.addStretch()
        layout.addLayout(mode_line)

        sub_line = QHBoxLayout()
        self.subfolder_check = QCheckBox("하위 폴더에 저장")
        self.subfolder_check.setObjectName("previewCheckBox")
        sub_line.addWidget(self.subfolder_check)
        self.subfolder_edit = QLineEdit()
        self.subfolder_edit.setPlaceholderText("Snapshot")
        self.subfolder_edit.setMaximumWidth(220)
        sub_line.addWidget(self.subfolder_edit)
        sub_line.addStretch()
        layout.addLayout(sub_line)

        custom_line = QHBoxLayout()
        self.output_edit = QLineEdit()
        self.output_edit.setReadOnly(True)
        self.output_edit.setObjectName("snapshotPathInput")
        custom_line.addWidget(self.output_edit, 1)
        self.output_button = QPushButton("폴더 선택")
        self.output_button.setObjectName("secondaryButton")
        self.output_button.clicked.connect(self._choose_output_folder)
        custom_line.addWidget(self.output_button)
        layout.addLayout(custom_line)

        self.output_source_radio.toggled.connect(self._output_mode_changed)
        self.output_custom_radio.toggled.connect(self._output_mode_changed)
        self.subfolder_check.toggled.connect(self._output_mode_changed)
        self.subfolder_edit.textChanged.connect(self._controls_changed)
        return section

    def _create_status_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("snapshotStatusBar")
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(7)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.status_title = QLabel("● 대기 중")
        self.status_title.setObjectName("snapshotStatusTitle")
        top.addWidget(self.status_title)
        self.status_text = QLabel("영상과 설정을 준비해 주세요.")
        self.status_text.setObjectName("snapshotStatusText")
        self.status_text.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        top.addWidget(self.status_text, 1)
        self.status_counter = QLabel("")
        self.status_counter.setObjectName("snapshotStatusCounter")
        top.addWidget(self.status_counter)
        self.status_details_button = QPushButton("자세히 ▾")
        self.status_details_button.setObjectName("snapshotStatusDetailsButton")
        self.status_details_button.setCheckable(True)
        self.status_details_button.toggled.connect(self._toggle_status_details)
        top.addWidget(self.status_details_button)
        outer.addLayout(top)

        self.quick_actions = QWidget()
        quick_layout = QHBoxLayout(self.quick_actions)
        quick_layout.setContentsMargins(0, 0, 0, 0)
        quick_layout.setSpacing(7)
        quick_layout.addStretch()
        self.quick_open_result_button = QPushButton("이미지 열기")
        self.quick_open_result_button.setObjectName("snapshotQuickActionButton")
        self.quick_open_result_button.clicked.connect(self._open_result_file)
        quick_layout.addWidget(self.quick_open_result_button)
        self.quick_open_folder_button = QPushButton("폴더 열기")
        self.quick_open_folder_button.setObjectName("snapshotQuickActionButton")
        self.quick_open_folder_button.clicked.connect(self._open_result_folder)
        quick_layout.addWidget(self.quick_open_folder_button)
        self.quick_actions.setVisible(False)
        outer.addWidget(self.quick_actions)

        progress_line = QHBoxLayout()
        self.status_progress = QProgressBar()
        self.status_progress.setObjectName("snapshotStatusProgress")
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        progress_line.addWidget(self.status_progress, 1)
        self.status_stop_button = QPushButton("■ 중지")
        self.status_stop_button.setObjectName("snapshotStatusStopButton")
        self.status_stop_button.clicked.connect(self._stop_operation)
        progress_line.addWidget(self.status_stop_button)
        outer.addLayout(progress_line)

        self.status_detail_frame = QFrame()
        self.status_detail_frame.setObjectName("snapshotStatusDetail")
        detail_layout = QVBoxLayout(self.status_detail_frame)
        detail_layout.setContentsMargins(12, 9, 12, 9)
        detail_layout.setSpacing(8)
        self.status_detail_label = QLabel("아직 결과가 없습니다.")
        self.status_detail_label.setObjectName("snapshotStatusDetailText")
        self.status_detail_label.setWordWrap(True)
        self.status_detail_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        detail_layout.addWidget(self.status_detail_label)

        detail_buttons = QHBoxLayout()
        self.open_result_button = QPushButton("결과 이미지 열기")
        self.open_result_button.setObjectName("secondaryButton")
        self.open_result_button.clicked.connect(self._open_result_file)
        detail_buttons.addWidget(self.open_result_button)
        self.open_folder_button = QPushButton("결과 폴더 열기")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.clicked.connect(self._open_result_folder)
        detail_buttons.addWidget(self.open_folder_button)
        self.open_log_button = QPushButton("로그 폴더 열기")
        self.open_log_button.setObjectName("secondaryButton")
        self.open_log_button.clicked.connect(self._open_log_folder)
        detail_buttons.addWidget(self.open_log_button)
        detail_buttons.addStretch()
        detail_layout.addLayout(detail_buttons)
        outer.addWidget(self.status_detail_frame)

        self.status_detail_frame.setVisible(False)
        self.status_progress.setVisible(False)
        self.status_stop_button.setVisible(False)
        self.open_result_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        return frame

    def _load_preferences_into_ui(self) -> None:
        p = self._preferences
        self.columns_spin.setValue(p.columns)
        self.rows_spin.setValue(p.rows)
        self.margin_spin.setValue(p.margin)
        self.target_size_spin.setValue(p.target_size)
        self.size_width_radio.setChecked(p.size_mode == SIZE_WIDTH)
        self.size_height_radio.setChecked(p.size_mode == SIZE_HEIGHT)
        self.show_info_check.setChecked(p.show_info)
        self.show_time_check.setChecked(p.show_time)
        self.font_combo.setCurrentFont(QFont(p.font_family))
        self.info_size_spin.setValue(p.info_font_size)
        self.time_size_spin.setValue(p.time_font_size)
        self.output_source_radio.setChecked(p.output_mode == OUTPUT_SOURCE)
        self.output_custom_radio.setChecked(p.output_mode == OUTPUT_CUSTOM)
        self.output_edit.setText(p.output_folder)
        self.subfolder_check.setChecked(p.create_subfolder)
        self.subfolder_edit.setText(p.subfolder_name)
        self._refresh_output_controls()
        self._refresh_total_shots()

    def _controls_changed(self, *_args: object) -> None:
        self._refresh_total_shots()
        self._refresh_section_summaries()
        self._schedule_save()

    def _output_mode_changed(self, *_args: object) -> None:
        self._refresh_output_controls()
        self._controls_changed()

    def _section_state_changed(self, _expanded: bool = False) -> None:
        self._schedule_save()

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_preferences(self) -> None:
        p = SnapshotPreferences(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            margin=self.margin_spin.value(),
            size_mode=SIZE_HEIGHT if self.size_height_radio.isChecked() else SIZE_WIDTH,
            target_size=self.target_size_spin.value(),
            show_info=self.show_info_check.isChecked(),
            show_time=self.show_time_check.isChecked(),
            font_family=self.font_combo.currentFont().family().strip() or "Malgun Gothic",
            info_font_size=self.info_size_spin.value(),
            time_font_size=self.time_size_spin.value(),
            output_mode=OUTPUT_CUSTOM if self.output_custom_radio.isChecked() else OUTPUT_SOURCE,
            output_folder=self.output_edit.text().strip(),
            create_subfolder=self.subfolder_check.isChecked(),
            subfolder_name=self.subfolder_edit.text().strip() or "Snapshot",
            single_expanded=self.single_section.expanded,
            batch_expanded=self.batch_section.expanded,
            layout_expanded=self.layout_section.expanded,
            display_expanded=self.display_section.expanded,
            output_expanded=self.output_section.expanded,
        )
        self._preferences = p
        save_snapshot_preferences(p)

    def _choose_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "스냅샷 영상 선택", "", VIDEO_FILTER)
        if path:
            self._set_input_file(path)

    def _set_input_file(self, path: str) -> None:
        candidate = Path(path)
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
            self._show_warning("지원하지 않는 영상", "MP4·MKV·WebM·MOV·AVI·M4V·TS 영상을 선택해 주세요.")
            return
        self._input_path = str(candidate)
        self._probe_result = None
        self.input_edit.setText(str(candidate))
        self.input_info_label.setText("영상 정보를 확인하는 중…")
        self._refresh_ui_state()
        worker = SnapshotProbeWorker(str(candidate))
        self._probe_worker = worker
        worker.succeeded.connect(self._probe_succeeded)
        worker.failed.connect(self._probe_failed)
        worker.finished.connect(self._probe_finished)
        worker.start()

    def _probe_succeeded(self, result: object) -> None:
        if not isinstance(result, SnapshotProbeResult):
            return
        self._probe_result = result
        self.input_info_label.setText(
            f"{result.width}×{result.height} · {self._format_duration(result.duration_seconds)} · {result.codec_name or 'VIDEO'}"
        )
        self._refresh_ui_state()

    def _probe_failed(self, message: str, detail: str) -> None:
        self.input_info_label.setText(message)
        self._set_status("● 확인 실패", message, detail=detail)

    def _probe_finished(self) -> None:
        self._probe_worker = None
        self._refresh_ui_state()

    def _reset_single_input(self) -> None:
        self._input_path = ""
        self._probe_result = None
        self.input_edit.clear()
        self.input_info_label.setText("영상을 선택하면 길이와 해상도를 확인합니다.")
        self._refresh_ui_state()

    def _choose_batch_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "여러 영상 추가", "", VIDEO_FILTER)
        self._add_batch_paths(paths)

    def _choose_batch_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "영상 폴더 선택")
        if not folder:
            return
        paths = [
            str(path)
            for path in sorted(Path(folder).iterdir(), key=lambda item: item.name.lower())
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS
        ]
        if not paths:
            self._show_info("영상 없음", "선택한 폴더 바로 아래에서 지원 영상을 찾지 못했습니다.")
            return
        self._add_batch_paths(paths)

    def _add_batch_paths(self, paths: list[str]) -> None:
        existing = {str(Path(path).resolve()).lower() for path in self._batch_paths}
        added = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_VIDEO_EXTENSIONS:
                continue
            key = str(path.resolve()).lower()
            if key in existing:
                continue
            existing.add(key)
            self._batch_paths.append(str(path))
            row = SnapshotTaskRow(str(path))
            row.remove_requested.connect(self._remove_batch_row)
            self._batch_rows.append(row)
            self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)
            added += 1
        if added:
            self._refresh_batch_state()

    def _remove_batch_row(self, row: SnapshotTaskRow) -> None:
        if self.has_active_operation:
            return
        try:
            index = self._batch_rows.index(row)
        except ValueError:
            return
        self._batch_rows.pop(index)
        self._batch_paths.pop(index)
        row.setParent(None)
        row.deleteLater()
        self._refresh_batch_state()

    def _clear_batch(self) -> None:
        if self.has_active_operation:
            return
        for row in self._batch_rows:
            row.setParent(None)
            row.deleteLater()
        self._batch_rows.clear()
        self._batch_paths.clear()
        self._refresh_batch_state()

    def _refresh_batch_state(self) -> None:
        count = len(self._batch_paths)
        self.queue_empty_label.setVisible(count == 0)
        self.batch_count_label.setText(f"{count}개 영상")
        self.batch_section.set_suffix(f"{count}개" if count else "")
        self.batch_start_button.setEnabled(count > 0 and not self.has_active_operation)
        self.batch_clear_button.setEnabled(count > 0 and not self.has_active_operation)


    def _choose_output_folder(self) -> None:
        start = self.output_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "스냅샷 저장 폴더", start)
        if folder:
            self.output_edit.setText(folder)
            self._controls_changed()

    def _start_single(self) -> None:
        if self.has_active_operation or not self._input_path or self._probe_result is None:
            return
        options = self._build_options()
        if options is None:
            return
        self._run_mode = "single"
        self._last_output_path = ""
        self.status_progress.setValue(0)
        self.open_result_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.quick_actions.setVisible(False)
        self._set_status(
            "● 생성 중",
            Path(self._input_path).name,
            detail="현재 작업 결과가 아직 없습니다.",
            show_progress=True,
        )

        worker = SnapshotWorker(self._input_path, self._probe_result, options)
        self._worker = worker
        self._set_controls_enabled(False)
        worker.progress_changed.connect(self.status_progress.setValue)
        worker.phase_changed.connect(lambda text: self.status_text.setText(text))
        worker.succeeded.connect(self._single_succeeded)
        worker.failed.connect(self._single_failed)
        worker.cancelled.connect(self._single_cancelled)
        worker.finished.connect(self._single_finished)
        worker.start()

    def _start_batch(self) -> None:
        if self.has_active_operation or not self._batch_paths:
            return
        options = self._build_options()
        if options is None:
            return
        self._run_mode = "batch"
        self._last_output_path = ""
        self._batch_success = 0
        self._batch_fail = 0
        self._batch_current = 0
        self._batch_total = len(self._batch_paths)
        for row in self._batch_rows:
            row.output_path = ""
            row.set_status("대기 중", "pending")
        self.status_progress.setValue(0)
        self.status_counter.setText(f"0 / {self._batch_total}")
        self.open_result_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self.quick_actions.setVisible(False)
        self._set_status(
            "● 여러 영상 생성 중",
            "첫 영상을 준비하는 중",
            detail="현재 작업 결과가 아직 없습니다.",
            show_progress=True,
        )

        worker = SnapshotBatchWorker(self._batch_paths, options)
        self._batch_worker = worker
        self._set_controls_enabled(False)
        worker.current_changed.connect(self._batch_current_changed)
        worker.item_started.connect(self._batch_item_started)
        worker.item_progress.connect(self._batch_item_progress)
        worker.item_phase.connect(self._batch_item_phase)
        worker.item_succeeded.connect(self._batch_item_succeeded)
        worker.item_failed.connect(self._batch_item_failed)
        worker.cancelled.connect(self._batch_cancelled)
        worker.completed.connect(self._batch_completed)
        worker.finished.connect(self._batch_finished)
        worker.start()

    def _build_options(self) -> SnapshotOptions | None:
        if self.output_custom_radio.isChecked() and not self.output_edit.text().strip():
            self._show_warning("출력 위치 확인", "지정 폴더를 선택해 주세요.")
            return None
        self._save_preferences()
        return SnapshotOptions(
            columns=self.columns_spin.value(),
            rows=self.rows_spin.value(),
            margin=self.margin_spin.value(),
            size_mode=SIZE_HEIGHT if self.size_height_radio.isChecked() else SIZE_WIDTH,
            target_size=self.target_size_spin.value(),
            show_info=self.show_info_check.isChecked(),
            show_time=self.show_time_check.isChecked(),
            font_family=self.font_combo.currentFont().family().strip() or "Malgun Gothic",
            info_font_size=self.info_size_spin.value(),
            time_font_size=self.time_size_spin.value(),
            output_mode=OUTPUT_CUSTOM if self.output_custom_radio.isChecked() else OUTPUT_SOURCE,
            output_folder=self.output_edit.text().strip(),
            create_subfolder=self.subfolder_check.isChecked(),
            subfolder_name=self.subfolder_edit.text().strip() or "Snapshot",
        )

    def _single_succeeded(self, result: object) -> None:
        if not isinstance(result, SnapshotResult):
            return
        self._last_output_path = result.output_path
        self.status_progress.setValue(100)
        self._set_status(
            "✓ 생성 완료",
            Path(result.output_path).name,
            detail=f"{result.shot_count}장 · {result.sheet_width}×{result.sheet_height}\n{result.output_path}",
            show_progress=False,
        )
        self.open_result_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self.quick_open_result_button.setVisible(True)
        self.quick_open_folder_button.setVisible(True)
        self.quick_actions.setVisible(True)
        self._reset_single_input()
        play_completion_sound()

    def _single_failed(self, message: str, detail: str) -> None:
        self._set_status("● 생성 실패", message, detail=detail, show_progress=False)

    def _single_cancelled(self, message: str) -> None:
        self._set_status("● 중지됨", message, show_progress=False)

    def _single_finished(self) -> None:
        self._worker = None
        self._run_mode = ""
        self._set_controls_enabled(True)
        self._refresh_ui_state()

    def _batch_current_changed(self, current: int, total: int, path: str) -> None:
        self._batch_current = current
        self._batch_total = total
        filename = Path(path).name
        self.status_counter.setText(f"{current} / {total}")
        self.status_text.setText(filename)
        self.status_detail_label.setText(
            f"현재 {current}/{total} · {filename}\n장면 추출 준비 중"
        )

    def _batch_item_started(self, index: int, _path: str) -> None:
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("처리 중", "running")

    def _batch_item_progress(self, index: int, value: int) -> None:
        self.status_progress.setValue(value)
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status(f"{value}%", "running")

    def _batch_item_phase(self, index: int, text: str) -> None:
        if 0 <= index < len(self._batch_rows):
            filename = Path(self._batch_rows[index].path).name
            self.status_text.setText(f"{text} · {filename}")
            match = re.search(r"장면\s+(\d+)/(\d+)", text)
            if match:
                self._batch_rows[index].set_status(f"{match.group(1)}/{match.group(2)}", "running")
            self.status_detail_label.setText(
                f"현재 {self._batch_current}/{self._batch_total} · {filename}\n{text}"
            )

    def _batch_item_succeeded(self, index: int, result: object) -> None:
        if not isinstance(result, SnapshotResult):
            return
        self._batch_success += 1
        self._last_output_path = result.output_path
        if 0 <= index < len(self._batch_rows):
            row = self._batch_rows[index]
            row.output_path = result.output_path
            row.set_status("완료", "done")
            self.status_detail_label.setText(
                f"{index + 1}/{self._batch_total} 완료 · {Path(row.path).name}\n{result.output_path}"
            )

    def _batch_item_failed(self, index: int, message: str, detail: str) -> None:
        self._batch_fail += 1
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("실패", "failed")
        self.status_detail_label.setText(f"{message}\n{detail}".strip())

    def _batch_cancelled(self, message: str) -> None:
        for row in self._batch_rows:
            if row.state == "running":
                row.set_status("중지됨", "stopped")
        self._set_status("● 중지됨", message, show_progress=False)

    def _batch_completed(self, success_count: int, fail_count: int) -> None:
        self._batch_success = success_count
        self._batch_fail = fail_count
        summary = f"성공 {success_count}개 · 실패 {fail_count}개"
        detail = summary
        if self._last_output_path:
            detail += f"\n마지막 결과: {self._last_output_path}"
        self._set_status("✓ 여러 영상 완료", summary, detail=detail, show_progress=False)
        self.open_result_button.setEnabled(bool(self._last_output_path))
        self.open_folder_button.setEnabled(bool(self._last_output_path))
        self.quick_open_result_button.setVisible(False)
        self.quick_open_folder_button.setVisible(bool(self._last_output_path))
        self.quick_actions.setVisible(bool(self._last_output_path))
        self.status_counter.setText(f"{self._batch_total} / {self._batch_total}")
        if success_count > 0 and fail_count == 0:
            play_completion_sound()

    def _batch_finished(self) -> None:
        self._batch_worker = None
        self._run_mode = ""
        self._set_controls_enabled(True)
        self._refresh_batch_state()
        self._refresh_ui_state()

    def _stop_operation(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self.status_text.setText("중지 요청 중…")
            self._worker.cancel()
        elif self._batch_worker is not None and self._batch_worker.isRunning():
            self.status_text.setText("중지 요청 중…")
            self._batch_worker.cancel()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.single_choose_button,
            self.batch_files_button,
            self.batch_folder_button,
            self.batch_clear_button,
            self.columns_spin,
            self.rows_spin,
            self.target_size_spin,
            self.margin_spin,
            self.size_width_radio,
            self.size_height_radio,
            self.show_info_check,
            self.show_time_check,
            self.font_combo,
            self.info_size_spin,
            self.time_size_spin,
            self.output_source_radio,
            self.output_custom_radio,
            self.subfolder_check,
            self.subfolder_edit,
            self.output_button,
        ):
            widget.setEnabled(enabled)
        for row in self._batch_rows:
            row.remove_button.setEnabled(enabled)
        self._refresh_ui_state()
        self._refresh_batch_state()
        self._refresh_output_controls()

    def _refresh_ui_state(self) -> None:
        busy = self.has_active_operation
        self.single_start_button.setEnabled(not busy and bool(self._input_path) and self._probe_result is not None)
        self.status_stop_button.setVisible(busy)
        self.status_progress.setVisible(busy)
        if not busy:
            self.status_stop_button.setVisible(False)

    def _refresh_total_shots(self) -> None:
        total = self.columns_spin.value() * self.rows_spin.value()
        self.total_shots_label.setText(f"총 {total}장")

    def _refresh_output_controls(self) -> None:
        source = self.output_source_radio.isChecked()
        self.subfolder_check.setEnabled(source and not self.has_active_operation)
        self.subfolder_edit.setEnabled(source and self.subfolder_check.isChecked() and not self.has_active_operation)
        self.output_edit.setEnabled(not source and not self.has_active_operation)
        self.output_button.setEnabled(not source and not self.has_active_operation)

    def _refresh_section_summaries(self) -> None:
        mode = "세로" if self.size_height_radio.isChecked() else "가로"
        total = self.columns_spin.value() * self.rows_spin.value()
        self.layout_section.set_suffix(
            f"{self.columns_spin.value()}×{self.rows_spin.value()} · {total}장 · {mode} {self.target_size_spin.value()}px · 여백 {self.margin_spin.value()}px"
        )
        display = []
        if self.show_info_check.isChecked():
            display.append("영상 정보")
        if self.show_time_check.isChecked():
            display.append("시간 표시")
        display_summary = " · ".join(display) if display else "표시 없음"
        self.display_section.set_suffix(f"{display_summary} · {self.font_combo.currentFont().family()}")

        if self.output_source_radio.isChecked():
            if self.subfolder_check.isChecked():
                name = self.subfolder_edit.text().strip() or "Snapshot"
                summary = f"영상 폴더\\{name}"
            else:
                summary = "영상과 같은 폴더"
        else:
            path = self.output_edit.text().strip()
            summary = path if path else "지정 폴더 선택 필요"
        self.output_section.set_suffix(summary)

    def _toggle_status_details(self, expanded: bool) -> None:
        self.status_detail_frame.setVisible(expanded)
        self.status_details_button.setText("자세히 ▴" if expanded else "자세히 ▾")

    def _set_status(
        self,
        title: str,
        summary: str,
        detail: str | None = None,
        *,
        show_progress: bool | None = None,
    ) -> None:
        self.status_title.setText(title)
        self.status_text.setText(summary)
        if detail is not None:
            self.status_detail_label.setText(detail or summary)
        if show_progress is not None:
            self.status_progress.setVisible(show_progress)
            self.status_stop_button.setVisible(show_progress)
        if not show_progress and self._run_mode != "batch":
            self.status_counter.setText("")

    def _open_result_file(self) -> None:
        if self._last_output_path and Path(self._last_output_path).is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_path))

    def _open_result_folder(self) -> None:
        if not self._last_output_path:
            return
        folder = Path(self._last_output_path).parent
        if folder.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RRV_LOGS_DIR)))

    def _show_warning(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(text)
        box.exec()

    def _show_info(self, title: str, text: str) -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle(title)
        box.setText(text)
        box.exec()

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
