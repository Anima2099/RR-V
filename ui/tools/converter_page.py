from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
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
    QSlider,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.converter_log import converter_log_path
from app.converter_preferences import (
    FORMAT_APNG,
    FORMAT_AVIF,
    FORMAT_GIF,
    FORMAT_WEBP,
    MODE_DIRECT,
    MODE_TARGET,
    OUTPUT_CUSTOM,
    OUTPUT_SOURCE,
    RESIZE_CUSTOM,
    RESIZE_HEIGHT,
    RESIZE_ORIGINAL,
    RESIZE_WIDTH,
    SUPPORTED_FORMATS,
    TARGET_STRATEGY_QUALITY,
    TARGET_STRATEGY_SCALE,
    default_format_preferences,
    load_converter_preferences,
    save_converter_preferences,
)
from app.general_preferences import FILE_COLLISION_OVERWRITE, load_general_preferences
from app.notifications import play_completion_sound
from app.paths import RRV_LOGS_DIR
from core.converter_models import ConversionOptions, VideoProbeResult
from ui.widgets.common import (
    NoWheelComboBox,
    NoWheelDoubleSpinBox,
    NoWheelSpinBox,
)
from workers.converter_worker import BatchConversionWorker, ConversionWorker, ProbeWorker


VIDEO_FILTER = "영상 파일 (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.ts)"
SUPPORTED_VIDEO_SUFFIXES = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".ts"}


class VideoDropFrame(QFrame):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("converterDropArea")
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


class ConverterCollapsibleSection(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        self._title = title
        self._expanded = bool(expanded)
        self._suffix = ""
        self.setObjectName("converterCollapsibleCard")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        self.header_button = QPushButton()
        self.header_button.setObjectName("converterCollapseButton")
        self.header_button.setCheckable(True)
        self.header_button.setChecked(self._expanded)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self.set_expanded)
        outer.addWidget(self.header_button)

        self.body = QWidget()
        self.body.setObjectName("converterCollapsibleBody")
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


class ConverterTaskRow(QFrame):
    remove_requested = Signal(object)

    def __init__(self, path: str) -> None:
        super().__init__()
        self.path = path
        self.state = "pending"
        self.output_path = ""
        self.setObjectName("converterTaskRow")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 9, 12, 9)
        layout.setSpacing(12)

        name = QLabel(Path(path).name)
        name.setObjectName("converterTaskTitle")
        name.setToolTip(path)
        layout.addWidget(name, 1)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("converterTaskStatus")
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


class ConverterPage(QWidget):
    FORMAT_LABELS = {
        FORMAT_WEBP: "WebP",
        FORMAT_GIF: "GIF",
        FORMAT_APNG: "APNG",
        FORMAT_AVIF: "AVIF",
    }
    FPS_CHOICES = ("원본", "60", "30", "24", "20", "15", "12", "10", "8")
    RESIZE_ITEMS = (
        ("원본 유지", RESIZE_ORIGINAL),
        ("너비 기준", RESIZE_WIDTH),
        ("높이 기준", RESIZE_HEIGHT),
        ("직접 입력", RESIZE_CUSTOM),
    )

    def __init__(self) -> None:
        super().__init__()
        self._preferences = load_converter_preferences()
        self._current_format = self._preferences.last_format
        self._input_path = ""
        self._probe_result: VideoProbeResult | None = None
        self._probe_worker: ProbeWorker | None = None
        self._conversion_worker: ConversionWorker | None = None
        self._batch_worker: BatchConversionWorker | None = None
        self._loading_controls = False
        self._last_output_path = ""
        self._batch_paths: list[str] = []
        self._batch_rows: list[ConverterTaskRow] = []
        self._run_mode = ""
        self._batch_success_count = 0
        self._batch_fail_count = 0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_preferences)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)

        title = QLabel("영상 → 움직이는 이미지")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "영상을 WebP·GIF·APNG·AVIF로 변환합니다. 자주 쓰는 설정은 접어두고 현재 값만 한 줄로 확인할 수 있습니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)
        outer.addWidget(self._create_format_bar())

        scroll = QScrollArea()
        scroll.setObjectName("converterScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(0, 2, 0, 4)
        layout.setSpacing(10)

        self.single_section = self._create_single_section()
        self.batch_section = self._create_batch_section()
        self.settings_section = self._create_settings_section()
        self.output_section = self._create_output_section()
        for section in (
            self.single_section,
            self.batch_section,
            self.settings_section,
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

        self._load_format_into_controls(self._current_format)
        self._load_global_controls()
        self._refresh_batch_state()
        self._refresh_section_summaries()
        self._refresh_ui_state()

    @property
    def has_active_operation(self) -> bool:
        single = self._conversion_worker is not None and self._conversion_worker.isRunning()
        batch = self._batch_worker is not None and self._batch_worker.isRunning()
        return single or batch

    def shutdown(self) -> None:
        self._save_preferences()
        if self._conversion_worker is not None and self._conversion_worker.isRunning():
            self._conversion_worker.cancel()
            self._conversion_worker.wait(4000)
        if self._batch_worker is not None and self._batch_worker.isRunning():
            self._batch_worker.cancel()
            self._batch_worker.wait(5000)
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
            self._probe_worker.wait(1500)

    def _create_format_bar(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("converterFormatBar")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(7)
        label = QLabel("출력 형식")
        label.setObjectName("converterFormatLabel")
        layout.addWidget(label)

        self.format_button_group = QButtonGroup(self)
        self.format_button_group.setExclusive(True)
        self.format_buttons: dict[str, QPushButton] = {}
        for output_format in SUPPORTED_FORMATS:
            button = QPushButton(self.FORMAT_LABELS[output_format])
            button.setObjectName("converterCompactFormatButton")
            button.setCheckable(True)
            button.clicked.connect(
                lambda checked=False, fmt=output_format: self._change_format(fmt)
            )
            self.format_button_group.addButton(button)
            self.format_buttons[output_format] = button
            layout.addWidget(button)
        layout.addStretch()
        return frame

    def _create_single_section(self) -> ConverterCollapsibleSection:
        section = ConverterCollapsibleSection("단일 영상", self._preferences.single_expanded)
        layout = section.body_layout

        self.drop_area = VideoDropFrame()
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(14, 12, 14, 12)
        drop_layout.setSpacing(8)

        self.input_path_edit = QLineEdit()
        self.input_path_edit.setObjectName("converterPathInput")
        self.input_path_edit.setReadOnly(True)
        self.input_path_edit.setPlaceholderText("영상 파일을 끌어놓거나 영상 선택 버튼 사용")
        select_button = QPushButton("영상 선택")
        select_button.setObjectName("secondaryButton")
        select_button.clicked.connect(self._choose_input_file)
        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.input_path_edit, 1)
        row.addWidget(select_button)
        self.input_select_button = select_button

        self.input_info_label = QLabel("아직 선택한 영상이 없습니다.")
        self.input_info_label.setObjectName("mutedText")
        self.input_info_label.setWordWrap(True)
        drop_layout.addLayout(row)
        drop_layout.addWidget(self.input_info_label)
        self.drop_area.file_dropped.connect(self._set_input_file)
        layout.addWidget(self.drop_area)

        action = QHBoxLayout()
        action.addStretch()
        self.single_start_button = QPushButton("변환 시작")
        self.single_start_button.setObjectName("primaryButton")
        self.single_start_button.clicked.connect(self._start_conversion)
        action.addWidget(self.single_start_button)
        layout.addLayout(action)
        return section

    def _create_batch_section(self) -> ConverterCollapsibleSection:
        section = ConverterCollapsibleSection("여러 영상", self._preferences.batch_expanded)
        layout = section.body_layout

        header = QHBoxLayout()
        self.batch_count_label = QLabel("0개")
        self.batch_count_label.setObjectName("mutedText")
        self.add_files_button = QPushButton("파일 여러 개 추가")
        self.add_files_button.setObjectName("secondaryButton")
        self.add_files_button.clicked.connect(self._choose_batch_files)
        self.add_folder_button = QPushButton("폴더 추가")
        self.add_folder_button.setObjectName("secondaryButton")
        self.add_folder_button.clicked.connect(self._choose_batch_folder)
        self.clear_batch_button = QPushButton("목록 지우기")
        self.clear_batch_button.setObjectName("secondaryButton")
        self.clear_batch_button.clicked.connect(self._clear_batch)
        header.addWidget(self.batch_count_label)
        header.addStretch()
        header.addWidget(self.add_files_button)
        header.addWidget(self.add_folder_button)
        header.addWidget(self.clear_batch_button)
        layout.addLayout(header)

        hint = QLabel(
            "선택한 폴더 바로 아래의 지원 영상만 추가합니다. 모든 영상에 현재 출력 형식·변환 설정·출력 위치를 똑같이 적용합니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.batch_scroll = QScrollArea()
        self.batch_scroll.setObjectName("converterQueueScroll")
        self.batch_scroll.setWidgetResizable(True)
        self.batch_scroll.setMinimumHeight(150)
        self.batch_scroll.setMaximumHeight(300)
        self.batch_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.batch_content = QWidget()
        self.batch_layout = QVBoxLayout(self.batch_content)
        self.batch_layout.setContentsMargins(4, 4, 4, 4)
        self.batch_layout.setSpacing(7)
        self.batch_empty_label = QLabel("아직 추가한 영상이 없습니다.")
        self.batch_empty_label.setObjectName("converterQueueEmpty")
        self.batch_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.batch_layout.addWidget(self.batch_empty_label)
        self.batch_layout.addStretch()
        self.batch_scroll.setWidget(self.batch_content)
        layout.addWidget(self.batch_scroll)

        action = QHBoxLayout()
        action.addStretch()
        self.batch_start_button = QPushButton("여러 영상 변환 시작")
        self.batch_start_button.setObjectName("primaryButton")
        self.batch_start_button.clicked.connect(self._start_batch)
        action.addWidget(self.batch_start_button)
        layout.addLayout(action)
        return section

    def _create_settings_section(self) -> ConverterCollapsibleSection:
        section = ConverterCollapsibleSection("변환 설정", self._preferences.settings_expanded)
        layout = section.body_layout

        top = QHBoxLayout()
        mode_row = QHBoxLayout()
        mode_row.setSpacing(8)
        self.direct_mode_button = QPushButton("직접 설정")
        self.target_mode_button = QPushButton("목표 용량")
        for button in (self.direct_mode_button, self.target_mode_button):
            button.setObjectName("converterModeButton")
            button.setCheckable(True)
            mode_row.addWidget(button)
        self.mode_button_group = QButtonGroup(self)
        self.mode_button_group.setExclusive(True)
        self.mode_button_group.addButton(self.direct_mode_button)
        self.mode_button_group.addButton(self.target_mode_button)
        self.direct_mode_button.clicked.connect(lambda: self._set_mode(MODE_DIRECT))
        self.target_mode_button.clicked.connect(lambda: self._set_mode(MODE_TARGET))
        top.addLayout(mode_row)
        top.addStretch()
        reset = QPushButton("기본값 복원")
        reset.setObjectName("secondaryButton")
        reset.clicked.connect(self._restore_current_defaults)
        top.addWidget(reset)
        layout.addLayout(top)

        common_frame = QFrame()
        common_frame.setObjectName("converterSettingsPanel")
        grid = QGridLayout(common_frame)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(11)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        quality_name = QLabel("품질")
        quality_name.setObjectName("previewOptionName")
        self.quality_slider = QSlider(Qt.Orientation.Horizontal)
        self.quality_slider.setObjectName("converterQualitySlider")
        self.quality_slider.setRange(1, 100)
        self.quality_slider.valueChanged.connect(self._quality_changed)
        self.quality_value_label = QLabel()
        self.quality_value_label.setObjectName("converterValueLabel")
        quality_box = QHBoxLayout()
        quality_box.setSpacing(10)
        quality_box.addWidget(self.quality_slider, 1)
        quality_box.addWidget(self.quality_value_label)

        fps_name = QLabel("FPS")
        fps_name.setObjectName("previewOptionName")
        self.fps_combo = NoWheelComboBox()
        self.fps_combo.setObjectName("previewCombo")
        self.fps_combo.addItems(self.FPS_CHOICES)
        self.fps_combo.currentTextChanged.connect(self._controls_changed)

        resize_name = QLabel("해상도")
        resize_name.setObjectName("previewOptionName")
        self.resize_combo = NoWheelComboBox()
        self.resize_combo.setObjectName("previewCombo")
        for label, value in self.RESIZE_ITEMS:
            self.resize_combo.addItem(label, value)
        self.resize_combo.currentIndexChanged.connect(self._resize_mode_changed)

        size_name = QLabel("크기")
        size_name.setObjectName("previewOptionName")
        self.width_spin = NoWheelSpinBox()
        self.width_spin.setObjectName("converterSpinBox")
        self.width_spin.setRange(2, 16384)
        self.width_spin.setSuffix(" px")
        self.height_spin = NoWheelSpinBox()
        self.height_spin.setObjectName("converterSpinBox")
        self.height_spin.setRange(2, 16384)
        self.height_spin.setSuffix(" px")
        self.width_spin.valueChanged.connect(self._controls_changed)
        self.height_spin.valueChanged.connect(self._controls_changed)
        size_box = QHBoxLayout()
        size_box.setSpacing(8)
        size_box.addWidget(self.width_spin)
        size_box.addWidget(QLabel("×"))
        size_box.addWidget(self.height_spin)

        self.resize_guide_label = QLabel()
        self.resize_guide_label.setObjectName("mutedText")
        self.resize_guide_label.setWordWrap(True)

        grid.addWidget(quality_name, 0, 0)
        grid.addLayout(quality_box, 0, 1, 1, 3)
        grid.addWidget(fps_name, 1, 0)
        grid.addWidget(self.fps_combo, 1, 1)
        grid.addWidget(resize_name, 1, 2)
        grid.addWidget(self.resize_combo, 1, 3)
        grid.addWidget(size_name, 2, 0)
        grid.addLayout(size_box, 2, 1, 1, 3)
        grid.addWidget(self.resize_guide_label, 3, 0, 1, 4)
        layout.addWidget(common_frame)

        self.mode_stack = QStackedWidget()
        self.mode_stack.addWidget(self._create_direct_mode_panel())
        self.mode_stack.addWidget(self._create_target_mode_panel())
        layout.addWidget(self.mode_stack)
        return section

    def _create_direct_mode_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("converterInfoPanel")
        box = QVBoxLayout(frame)
        box.setContentsMargins(14, 10, 14, 10)
        label = QLabel("설정한 품질·FPS·해상도로 한 번 변환합니다.")
        label.setObjectName("mutedText")
        box.addWidget(label)
        return frame

    def _create_target_mode_panel(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("converterTargetPanel")
        grid = QGridLayout(frame)
        grid.setContentsMargins(16, 14, 16, 14)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)

        size_name = QLabel("최대 용량")
        size_name.setObjectName("previewOptionName")
        self.target_size_spin = NoWheelDoubleSpinBox()
        self.target_size_spin.setObjectName("converterDoubleSpinBox")
        self.target_size_spin.setRange(0.1, 2048.0)
        self.target_size_spin.setDecimals(1)
        self.target_size_spin.setSingleStep(1.0)
        self.target_size_spin.setSuffix(" MB 이하")
        self.target_size_spin.valueChanged.connect(self._controls_changed)

        strategy_name = QLabel("조정 방식")
        strategy_name.setObjectName("previewOptionName")
        self.quality_strategy_radio = QRadioButton("해상도 유지, 품질 조절")
        self.scale_strategy_radio = QRadioButton("품질 유지, 이미지 크기 조절")
        self.quality_strategy_radio.setObjectName("settingsRadioButton")
        self.scale_strategy_radio.setObjectName("settingsRadioButton")
        self.strategy_group = QButtonGroup(self)
        self.strategy_group.setExclusive(True)
        self.strategy_group.addButton(self.quality_strategy_radio)
        self.strategy_group.addButton(self.scale_strategy_radio)
        self.quality_strategy_radio.toggled.connect(self._target_strategy_changed)
        self.scale_strategy_radio.toggled.connect(self._target_strategy_changed)
        strategy_box = QVBoxLayout()
        strategy_box.setSpacing(6)
        strategy_box.addWidget(self.quality_strategy_radio)
        strategy_box.addWidget(self.scale_strategy_radio)

        attempts_name = QLabel("최대 시도 횟수")
        attempts_name.setObjectName("previewOptionName")
        self.target_attempts_spin = NoWheelSpinBox()
        self.target_attempts_spin.setObjectName("converterSpinBox")
        self.target_attempts_spin.setRange(3, 10)
        self.target_attempts_spin.setSuffix(" 회")
        self.target_attempts_spin.valueChanged.connect(self._controls_changed)

        self.target_help_label = QLabel()
        self.target_help_label.setObjectName("mutedText")
        self.target_help_label.setWordWrap(True)
        grid.addWidget(size_name, 0, 0)
        grid.addWidget(self.target_size_spin, 0, 1)
        grid.addWidget(strategy_name, 1, 0, Qt.AlignmentFlag.AlignTop)
        grid.addLayout(strategy_box, 1, 1)
        grid.addWidget(attempts_name, 2, 0)
        grid.addWidget(self.target_attempts_spin, 2, 1)
        grid.addWidget(self.target_help_label, 3, 0, 1, 2)
        return frame

    def _create_output_section(self) -> ConverterCollapsibleSection:
        section = ConverterCollapsibleSection("출력 위치", self._preferences.output_expanded)
        layout = section.body_layout
        self.source_output_radio = QRadioButton("원본 영상과 같은 폴더")
        self.custom_output_radio = QRadioButton("직접 지정한 폴더")
        self.source_output_radio.setObjectName("settingsRadioButton")
        self.custom_output_radio.setObjectName("settingsRadioButton")
        self.output_group = QButtonGroup(self)
        self.output_group.setExclusive(True)
        self.output_group.addButton(self.source_output_radio)
        self.output_group.addButton(self.custom_output_radio)
        self.source_output_radio.toggled.connect(self._output_mode_changed)
        self.custom_output_radio.toggled.connect(self._output_mode_changed)
        radio_row = QHBoxLayout()
        radio_row.setSpacing(18)
        radio_row.addWidget(self.source_output_radio)
        radio_row.addWidget(self.custom_output_radio)
        radio_row.addStretch()
        layout.addLayout(radio_row)

        self.output_path_edit = QLineEdit()
        self.output_path_edit.setObjectName("converterPathInput")
        self.output_path_edit.textChanged.connect(self._controls_changed)
        self.output_choose_button = QPushButton("폴더 선택")
        self.output_choose_button.setObjectName("secondaryButton")
        self.output_choose_button.clicked.connect(self._choose_output_folder)
        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        path_row.addWidget(self.output_path_edit, 1)
        path_row.addWidget(self.output_choose_button)
        layout.addLayout(path_row)

        self.collision_label = QLabel()
        self.collision_label.setObjectName("mutedText")
        self.collision_label.setWordWrap(True)
        layout.addWidget(self.collision_label)
        return section

    def _create_status_bar(self) -> QFrame:
        card = QFrame()
        card.setObjectName("converterStatusBar")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(7)

        summary = QHBoxLayout()
        summary.setSpacing(10)
        title = QLabel("처리 상태")
        title.setObjectName("converterStatusTitle")
        summary.addWidget(title)
        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("converterStatusText")
        self.status_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        summary.addWidget(self.status_label, 1)
        self.status_counter = QLabel("")
        self.status_counter.setObjectName("converterStatusCounter")
        summary.addWidget(self.status_counter)
        self.details_button = QPushButton("자세히 ▾")
        self.details_button.setObjectName("converterStatusDetailsButton")
        self.details_button.setCheckable(True)
        self.details_button.toggled.connect(self._toggle_status_details)
        summary.addWidget(self.details_button)
        layout.addLayout(summary)

        self.progress_row_widget = QWidget()
        progress_row = QHBoxLayout(self.progress_row_widget)
        progress_row.setContentsMargins(0, 0, 0, 0)
        progress_row.setSpacing(10)
        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("converterStatusProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        progress_row.addWidget(self.progress_bar, 1)
        self.stop_button = QPushButton("■ 중지")
        self.stop_button.setObjectName("converterStatusStopButton")
        self.stop_button.clicked.connect(self._stop_operation)
        progress_row.addWidget(self.stop_button)
        self.progress_row_widget.setVisible(False)
        layout.addWidget(self.progress_row_widget)

        self.status_detail_frame = QFrame()
        self.status_detail_frame.setObjectName("converterStatusDetail")
        detail = QVBoxLayout(self.status_detail_frame)
        detail.setContentsMargins(10, 9, 10, 9)
        detail.setSpacing(8)
        self.status_detail_label = QLabel("아직 상세 작업 내용이 없습니다.")
        self.status_detail_label.setObjectName("converterStatusDetailText")
        self.status_detail_label.setWordWrap(True)
        detail.addWidget(self.status_detail_label)
        buttons = QHBoxLayout()
        buttons.addStretch()
        self.open_file_button = QPushButton("결과 열기")
        self.open_file_button.setObjectName("secondaryButton")
        self.open_file_button.clicked.connect(self._open_result_file)
        self.open_file_button.setEnabled(False)
        self.open_folder_button = QPushButton("결과 폴더 열기")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.clicked.connect(self._open_result_folder)
        self.open_folder_button.setEnabled(False)
        self.log_button = QPushButton("로그 폴더 열기")
        self.log_button.setObjectName("secondaryButton")
        self.log_button.clicked.connect(self._open_log_folder)
        buttons.addWidget(self.open_file_button)
        buttons.addWidget(self.open_folder_button)
        buttons.addWidget(self.log_button)
        detail.addLayout(buttons)
        self.status_detail_frame.setVisible(False)
        layout.addWidget(self.status_detail_frame)
        return card

    def _choose_input_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "변환할 영상 선택", "", VIDEO_FILTER)
        if path:
            self._set_input_file(path)

    def _set_input_file(self, path: str) -> None:
        if self.has_active_operation:
            return
        file = Path(path)
        if not file.is_file() or file.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            self._show_warning("파일 확인", "지원하는 영상 파일을 선택해 주세요.")
            return
        self._input_path = str(file)
        self._probe_result = None
        self.input_path_edit.setText(self._input_path)
        self.input_info_label.setText("영상 정보를 확인 중…")
        self._set_status("영상 정보를 확인 중…", self._input_path)
        self.progress_bar.setValue(0)
        worker = ProbeWorker(self._input_path)
        self._probe_worker = worker
        worker.succeeded.connect(self._probe_succeeded)
        worker.failed.connect(self._probe_failed)
        worker.finished.connect(self._probe_finished)
        worker.start()
        self._refresh_ui_state()

    def _probe_succeeded(self, result: object) -> None:
        if not isinstance(result, VideoProbeResult):
            self._probe_failed("영상 정보를 해석하지 못했습니다.", repr(result))
            return
        self._probe_result = result
        duration = self._format_duration(result.duration)
        fps_text = f"{result.fps:.2f}".rstrip("0").rstrip(".")
        self.input_info_label.setText(
            f"{result.width}×{result.height} · {fps_text} FPS · {duration} · {result.video_codec.upper()}"
        )
        self._set_status("변환 준비 완료", f"{Path(self._input_path).name}\n변환 설정을 확인하고 시작해 주세요.")
        self._refresh_resize_guide()
        self._refresh_ui_state()

    def _probe_failed(self, message: str, detail: str) -> None:
        self._probe_result = None
        self.input_info_label.setText(message)
        self._set_status(message, detail or message)
        self._refresh_ui_state()
        self._show_warning("영상 정보 확인 실패", f"{message}\n\n{detail}" if detail else message)

    def _probe_finished(self) -> None:
        worker = self._probe_worker
        if worker is not None:
            worker.deleteLater()
        self._probe_worker = None

    def _reset_single_input(self) -> None:
        self._input_path = ""
        self._probe_result = None
        self.input_path_edit.clear()
        self.input_info_label.setText("아직 선택한 영상이 없습니다.")
        self._refresh_resize_guide()
        self._refresh_ui_state()

    def _choose_batch_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "여러 영상 추가", "", VIDEO_FILTER)
        self._add_batch_paths(paths)

    def _choose_batch_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "영상 폴더 선택", "")
        if not folder:
            return
        root = Path(folder)
        paths = [
            str(path)
            for path in sorted(root.iterdir(), key=lambda p: p.name.casefold())
            if path.is_file() and path.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES
        ]
        self._add_batch_paths(paths)
        if not paths:
            self._set_status("추가할 영상 없음", str(root))

    def _add_batch_paths(self, paths: list[str]) -> None:
        existing = {str(Path(p).resolve()).lower() for p in self._batch_paths}
        added = 0
        for raw in paths:
            path = Path(raw)
            if not path.is_file() or path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
                continue
            try:
                key = str(path.resolve()).lower()
            except OSError:
                key = str(path).lower()
            if key in existing:
                continue
            existing.add(key)
            self._batch_paths.append(str(path))
            row = ConverterTaskRow(str(path))
            row.remove_requested.connect(self._remove_batch_row)
            self._batch_rows.append(row)
            self.batch_layout.insertWidget(self.batch_layout.count() - 1, row)
            added += 1
        if added:
            self._set_status(f"여러 영상 목록에 {added}개 추가됨")
        self._refresh_batch_state()

    def _remove_batch_row(self, row: ConverterTaskRow) -> None:
        if self.has_active_operation:
            return
        if row not in self._batch_rows:
            return
        index = self._batch_rows.index(row)
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
        self.batch_count_label.setText(f"{count}개")
        self.batch_empty_label.setVisible(count == 0)
        self.batch_section.set_suffix(f"{count}개" if count else "")
        active = self.has_active_operation
        self.batch_start_button.setEnabled(count > 0 and not active)
        self.clear_batch_button.setEnabled(count > 0 and not active)

    def _change_format(self, output_format: str) -> None:
        if output_format == self._current_format:
            return
        self._save_current_controls()
        self._current_format = output_format
        self._preferences.last_format = output_format
        self._load_format_into_controls(output_format)
        self._schedule_save()

    def _load_format_into_controls(self, output_format: str) -> None:
        self._loading_controls = True
        try:
            settings = self._preferences.formats.get(output_format, default_format_preferences(output_format))
            self._preferences.formats[output_format] = settings
            for fmt, button in self.format_buttons.items():
                button.setChecked(fmt == output_format)
            self.quality_slider.setValue(settings.quality)
            self.fps_combo.setCurrentText(settings.fps)
            index = self.resize_combo.findData(settings.resize_mode)
            self.resize_combo.setCurrentIndex(max(0, index))
            self.width_spin.setValue(settings.width)
            self.height_spin.setValue(settings.height)
            self.target_size_spin.setValue(settings.target_mb)
            self.target_attempts_spin.setValue(settings.target_attempts)
            target = settings.mode == MODE_TARGET
            self.direct_mode_button.setChecked(not target)
            self.target_mode_button.setChecked(target)
            self.mode_stack.setCurrentIndex(1 if target else 0)
            if settings.target_strategy == TARGET_STRATEGY_SCALE:
                self.scale_strategy_radio.setChecked(True)
            else:
                self.quality_strategy_radio.setChecked(True)
        finally:
            self._loading_controls = False
        self._refresh_quality_label()
        self._refresh_resize_controls()
        self._refresh_target_controls()
        self._refresh_section_summaries()
        self._refresh_ui_state()

    def _load_global_controls(self) -> None:
        self._loading_controls = True
        try:
            if self._preferences.output_mode == OUTPUT_CUSTOM:
                self.custom_output_radio.setChecked(True)
            else:
                self.source_output_radio.setChecked(True)
            self.output_path_edit.setText(self._preferences.output_folder)
        finally:
            self._loading_controls = False
        self._refresh_output_controls()
        self._refresh_collision_text()
        self._refresh_section_summaries()

    def _set_mode(self, mode: str) -> None:
        if self._loading_controls:
            return
        self.mode_stack.setCurrentIndex(1 if mode == MODE_TARGET else 0)
        self._controls_changed()
        self._refresh_target_controls()

    def _quality_changed(self) -> None:
        self._refresh_quality_label()
        self._controls_changed()

    def _resize_mode_changed(self) -> None:
        self._refresh_resize_controls()
        self._controls_changed()

    def _target_strategy_changed(self) -> None:
        if self._loading_controls:
            return
        self._refresh_target_controls()
        self._controls_changed()

    def _output_mode_changed(self) -> None:
        if self._loading_controls:
            return
        self._refresh_output_controls()
        self._controls_changed()

    def _controls_changed(self, *_args: object) -> None:
        if self._loading_controls:
            return
        self._save_current_controls()
        self._schedule_save()
        self._refresh_section_summaries()
        self._refresh_ui_state()

    def _section_state_changed(self, _expanded: bool = False) -> None:
        self._save_preferences()

    def _save_current_controls(self) -> None:
        if self._loading_controls:
            return
        settings = self._preferences.formats.get(self._current_format, default_format_preferences(self._current_format))
        settings.mode = MODE_TARGET if self.target_mode_button.isChecked() else MODE_DIRECT
        settings.quality = self.quality_slider.value()
        settings.fps = self.fps_combo.currentText()
        settings.resize_mode = str(self.resize_combo.currentData())
        settings.width = self.width_spin.value()
        settings.height = self.height_spin.value()
        settings.target_mb = self.target_size_spin.value()
        settings.target_attempts = self.target_attempts_spin.value()
        settings.target_strategy = TARGET_STRATEGY_SCALE if self.scale_strategy_radio.isChecked() else TARGET_STRATEGY_QUALITY
        if self._current_format == FORMAT_APNG:
            settings.target_strategy = TARGET_STRATEGY_SCALE
        self._preferences.formats[self._current_format] = settings
        self._preferences.last_format = self._current_format
        self._preferences.output_mode = OUTPUT_CUSTOM if self.custom_output_radio.isChecked() else OUTPUT_SOURCE
        self._preferences.output_folder = self.output_path_edit.text().strip()
        self._preferences.single_expanded = self.single_section.expanded
        self._preferences.batch_expanded = self.batch_section.expanded
        self._preferences.settings_expanded = self.settings_section.expanded
        self._preferences.output_expanded = self.output_section.expanded

    def _schedule_save(self) -> None:
        self._save_timer.start()

    def _save_preferences(self) -> None:
        self._save_current_controls()
        save_converter_preferences(self._preferences)

    def _restore_current_defaults(self) -> None:
        answer = self._ask_question(
            "기본값 복원",
            f"{self.FORMAT_LABELS[self._current_format]} 설정을 기본값으로 되돌리시겠습니까?",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self._preferences.formats[self._current_format] = default_format_preferences(self._current_format)
        self._load_format_into_controls(self._current_format)
        self._save_preferences()

    def _choose_output_folder(self) -> None:
        initial = self.output_path_edit.text().strip() or str(Path.home())
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더 선택", initial)
        if folder:
            self.output_path_edit.setText(folder)
            self.custom_output_radio.setChecked(True)

    def _start_conversion(self) -> None:
        if self.has_active_operation:
            return
        if self._probe_result is None or not self._input_path:
            self._show_info("입력 영상", "먼저 변환할 영상 파일을 선택해 주세요.")
            return
        options = self._prepare_options()
        if options is None:
            return
        self._run_mode = "single"
        worker = ConversionWorker(self._input_path, self._probe_result, options)
        self._conversion_worker = worker
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.phase_changed.connect(lambda text: self._set_status(text, text, show_progress=True))
        worker.attempt_changed.connect(self._single_attempt_changed)
        worker.succeeded.connect(self._conversion_succeeded)
        worker.failed.connect(self._conversion_failed)
        worker.cancelled.connect(self._conversion_cancelled)
        worker.finished.connect(self._conversion_finished)
        self.progress_bar.setValue(0)
        self.status_counter.setText("")
        self._set_status("변환을 준비 중…", Path(self._input_path).name, show_progress=True)
        self._last_output_path = ""
        self.open_file_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        self._set_controls_enabled(False)
        worker.start()

    def _start_batch(self) -> None:
        if self.has_active_operation or not self._batch_paths:
            return
        options = self._prepare_options()
        if options is None:
            return
        self._run_mode = "batch"
        self._batch_success_count = 0
        self._batch_fail_count = 0
        for row in self._batch_rows:
            if row.state in {"done", "failed", "stopped", "running"}:
                row.set_status("대기 중", "pending")
            row.remove_button.setEnabled(False)
        worker = BatchConversionWorker(list(self._batch_paths), options)
        self._batch_worker = worker
        worker.current_changed.connect(self._batch_current_changed)
        worker.item_started.connect(self._batch_item_started)
        worker.item_progress.connect(self._batch_item_progress)
        worker.item_phase.connect(self._batch_item_phase)
        worker.item_attempt.connect(self._batch_item_attempt)
        worker.item_succeeded.connect(self._batch_item_succeeded)
        worker.item_failed.connect(self._batch_item_failed)
        worker.cancelled.connect(self._batch_cancelled)
        worker.finished.connect(self._batch_finished)
        self.progress_bar.setValue(0)
        self._set_status("여러 영상 변환 준비 중…", f"총 {len(self._batch_paths)}개", show_progress=True)
        self._set_controls_enabled(False)
        worker.start()

    def _prepare_options(self) -> ConversionOptions | None:
        self._save_current_controls()
        self._save_preferences()
        options = self._build_options()
        if options.output_mode == OUTPUT_CUSTOM and not options.output_folder:
            self._show_warning("출력 폴더", "직접 지정할 출력 폴더를 선택해 주세요.")
            return None
        return options

    def _single_attempt_changed(self, attempt: int, maximum: int, detail: str) -> None:
        self.status_counter.setText("" if maximum <= 1 else f"{attempt}/{maximum}차")
        self.progress_bar.setValue(0)
        self._set_status(detail, detail, show_progress=True)

    def _conversion_succeeded(self, output_path: str, size_bytes: int, attempts: int) -> None:
        self._last_output_path = output_path
        size = self._format_file_size(size_bytes)
        trial = f" · {attempts}회 시험" if attempts > 1 else ""
        self.progress_bar.setValue(100)
        self.status_counter.setText("")
        self._set_status(
            f"✓ 변환 완료 · {size}{trial}",
            f"{output_path}\n완료 후 단일 영상 입력을 초기화했습니다.",
            show_progress=False,
        )
        self.open_file_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self._reset_single_input()
        play_completion_sound()

    def _conversion_failed(self, message: str, detail: str) -> None:
        self.progress_bar.setValue(0)
        body = f"{message}\n\n{detail}" if detail else message
        body += f"\n\n변환 로그: {converter_log_path()}"
        self._set_status(f"변환 실패 · {message}", body, show_progress=False)
        self._show_warning("변환 실패", body)

    def _conversion_cancelled(self, message: str) -> None:
        self.progress_bar.setValue(0)
        self._set_status(message, message, show_progress=False)

    def _conversion_finished(self) -> None:
        worker = self._conversion_worker
        if worker is not None:
            worker.deleteLater()
        self._conversion_worker = None
        self._run_mode = ""
        self._set_controls_enabled(True)
        self._refresh_ui_state()

    def _batch_current_changed(self, current: int, total: int, path: str) -> None:
        self.status_counter.setText(f"{current}/{total}")
        self.progress_bar.setValue(0)
        self._set_status(f"변환 중 · {Path(path).name}", path, show_progress=True)

    def _batch_item_started(self, index: int, _path: str) -> None:
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("변환 중", "running")

    def _batch_item_progress(self, index: int, value: int) -> None:
        del index
        self.progress_bar.setValue(value)

    def _batch_item_phase(self, index: int, text: str) -> None:
        if 0 <= index < len(self._batch_paths):
            self._set_status(f"변환 중 · {Path(self._batch_paths[index]).name}", text, show_progress=True)

    def _batch_item_attempt(self, index: int, attempt: int, maximum: int, detail: str) -> None:
        if 0 <= index < len(self._batch_paths):
            total = len(self._batch_paths)
            self.status_counter.setText(f"{index + 1}/{total} · {attempt}/{maximum}차")
            self.progress_bar.setValue(0)
            self._set_status(f"변환 중 · {Path(self._batch_paths[index]).name}", detail, show_progress=True)

    def _batch_item_succeeded(self, index: int, output_path: str, size_bytes: int, attempts: int) -> None:
        self._batch_success_count += 1
        self._last_output_path = output_path
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].output_path = output_path
            self._batch_rows[index].set_status("완료", "done")
        self.open_file_button.setEnabled(True)
        self.open_folder_button.setEnabled(True)
        self.status_detail_label.setText(
            f"{Path(output_path).name} · {self._format_file_size(size_bytes)} · {attempts}회 처리"
        )

    def _batch_item_failed(self, index: int, message: str, detail: str) -> None:
        self._batch_fail_count += 1
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("실패", "failed")
        self.status_detail_label.setText(f"{message}\n{detail}".strip())

    def _batch_cancelled(self, message: str) -> None:
        for row in self._batch_rows:
            if row.state == "running":
                row.set_status("중지됨", "stopped")
        self._set_status(message, message, show_progress=False)

    def _batch_finished(self) -> None:
        worker = self._batch_worker
        if worker is not None:
            worker.deleteLater()
        self._batch_worker = None
        for row in self._batch_rows:
            row.remove_button.setEnabled(True)
        batch_all_succeeded = (
            bool(self._batch_paths)
            and self._batch_fail_count == 0
            and self._batch_success_count == len(self._batch_paths)
        )
        if self._run_mode == "batch" and not self.progress_row_widget.isHidden():
            self.progress_bar.setValue(100 if self._batch_fail_count == 0 else self.progress_bar.value())
            self._set_status(
                f"✓ 여러 영상 변환 완료 · 성공 {self._batch_success_count} · 실패 {self._batch_fail_count}",
                f"총 {len(self._batch_paths)}개 처리 · 성공 {self._batch_success_count} · 실패 {self._batch_fail_count}",
                show_progress=False,
            )
        self._run_mode = ""
        self.status_counter.setText("")
        self._set_controls_enabled(True)
        self._refresh_batch_state()
        self._refresh_ui_state()
        if batch_all_succeeded:
            play_completion_sound()

    def _stop_operation(self) -> None:
        if self._conversion_worker is not None and self._conversion_worker.isRunning():
            self._set_status("변환 중지 중…", show_progress=True)
            self._conversion_worker.cancel()
            return
        if self._batch_worker is not None and self._batch_worker.isRunning():
            self._set_status("여러 영상 변환 중지 중…", show_progress=True)
            self._batch_worker.cancel()

    def _build_options(self) -> ConversionOptions:
        settings = self._preferences.formats[self._current_format]
        return ConversionOptions(
            output_format=self._current_format,
            mode=settings.mode,
            quality=settings.quality,
            fps=settings.fps,
            resize_mode=settings.resize_mode,
            width=settings.width,
            height=settings.height,
            target_mb=settings.target_mb,
            target_strategy=settings.target_strategy,
            target_attempts=settings.target_attempts,
            output_mode=self._preferences.output_mode,
            output_folder=self._preferences.output_folder,
        )

    def _set_controls_enabled(self, enabled: bool) -> None:
        self.drop_area.setEnabled(enabled)
        self.input_select_button.setEnabled(enabled)
        for button in self.format_buttons.values():
            button.setEnabled(enabled)
        self.direct_mode_button.setEnabled(enabled)
        self.target_mode_button.setEnabled(enabled)
        self.quality_slider.setEnabled(enabled and self._current_format != FORMAT_APNG)
        self.fps_combo.setEnabled(enabled)
        self.resize_combo.setEnabled(enabled)
        self.target_size_spin.setEnabled(enabled)
        self.target_attempts_spin.setEnabled(enabled)
        self.quality_strategy_radio.setEnabled(enabled and self._current_format != FORMAT_APNG)
        self.scale_strategy_radio.setEnabled(enabled)
        self.source_output_radio.setEnabled(enabled)
        self.custom_output_radio.setEnabled(enabled)
        self.add_files_button.setEnabled(enabled)
        self.add_folder_button.setEnabled(enabled)
        if enabled:
            self._refresh_resize_controls()
            self._refresh_target_controls()
            self._refresh_output_controls()
        else:
            self.width_spin.setEnabled(False)
            self.height_spin.setEnabled(False)
            self.output_path_edit.setEnabled(False)
            self.output_choose_button.setEnabled(False)
        self._refresh_batch_state()

    def _refresh_ui_state(self) -> None:
        active = self.has_active_operation
        ready = self._probe_result is not None and bool(self._input_path)
        self.single_start_button.setEnabled(ready and not active)
        self.batch_start_button.setEnabled(bool(self._batch_paths) and not active)
        self.progress_row_widget.setVisible(active)
        self._refresh_batch_state()

    def _refresh_quality_label(self) -> None:
        quality = self.quality_slider.value()
        if self._current_format == FORMAT_APNG:
            self.quality_value_label.setText("무손실")
        elif self._current_format == FORMAT_GIF:
            colors = max(16, min(256, round(16 + quality / 100 * 240)))
            self.quality_value_label.setText(f"{quality} · 약 {colors}색")
        else:
            level = "낮음" if quality < 40 else "균형" if quality < 80 else "높음"
            self.quality_value_label.setText(f"{quality} · {level}")

    def _refresh_resize_controls(self) -> None:
        mode = self.resize_combo.currentData()
        active = self.has_active_operation
        self.width_spin.setEnabled(not active and mode in {RESIZE_WIDTH, RESIZE_CUSTOM})
        self.height_spin.setEnabled(not active and mode in {RESIZE_HEIGHT, RESIZE_CUSTOM})
        self._refresh_resize_guide()

    def _refresh_resize_guide(self) -> None:
        mode = self.resize_combo.currentData()
        probe = self._probe_result
        if mode == RESIZE_ORIGINAL:
            text = "원본 영상의 가로·세로 크기를 그대로 사용합니다."
        elif mode == RESIZE_WIDTH:
            text = "입력한 너비에 맞춰 높이를 자동 계산하고 원본 비율을 유지합니다."
            if probe is not None:
                height = round(self.width_spin.value() * probe.height / probe.width)
                text += f" 예상 크기: {self.width_spin.value()}×{height}"
        elif mode == RESIZE_HEIGHT:
            text = "입력한 높이에 맞춰 너비를 자동 계산하고 원본 비율을 유지합니다."
            if probe is not None:
                width = round(self.height_spin.value() * probe.width / probe.height)
                text += f" 예상 크기: {width}×{self.height_spin.value()}"
        else:
            text = "가로와 세로를 직접 지정합니다. 원본 비율과 다르면 영상이 늘어나거나 눌릴 수 있습니다."
        self.resize_guide_label.setText(text)

    def _refresh_target_controls(self) -> None:
        target = self.target_mode_button.isChecked()
        self.mode_stack.setCurrentIndex(1 if target else 0)
        apng = self._current_format == FORMAT_APNG
        active = self.has_active_operation
        self.quality_slider.setEnabled(not apng and not active)
        self.quality_strategy_radio.setEnabled(not apng and not active)
        self.target_size_spin.setEnabled(target and not active)
        self.target_attempts_spin.setEnabled(target and not active)
        if apng and not self.scale_strategy_radio.isChecked():
            self._loading_controls = True
            self.scale_strategy_radio.setChecked(True)
            self._loading_controls = False
            self._save_current_controls()
        if self.scale_strategy_radio.isChecked():
            self.target_help_label.setText("품질을 유지하고 이미지 크기를 조절해 목표 용량 이하의 가장 큰 결과를 찾습니다.")
        else:
            self.target_help_label.setText("해상도를 유지하고 품질을 조절해 목표 용량 이하에서 가장 높은 품질을 찾습니다.")

    def _refresh_output_controls(self) -> None:
        custom = self.custom_output_radio.isChecked()
        enabled = custom and not self.has_active_operation
        self.output_path_edit.setEnabled(enabled)
        self.output_choose_button.setEnabled(enabled)

    def _refresh_collision_text(self) -> None:
        mode = load_general_preferences().file_collision_mode
        if mode == FILE_COLLISION_OVERWRITE:
            self.collision_label.setText("같은 이름의 결과가 있으면 일반 설정에 따라 기존 파일을 덮어씁니다.")
        else:
            self.collision_label.setText("같은 이름의 결과가 있으면 일반 설정에 따라 (2), (3)을 붙여 새 파일로 저장합니다.")

    def _refresh_section_summaries(self) -> None:
        if not hasattr(self, "settings_section"):
            return
        settings = self._preferences.formats.get(self._current_format, default_format_preferences(self._current_format))
        if settings.mode == MODE_TARGET:
            strategy = "품질 조절" if settings.target_strategy == TARGET_STRATEGY_QUALITY else "크기 조절"
            summary = f"{settings.target_mb:g}MB 이하 · {strategy} · 최대 {settings.target_attempts}회"
        else:
            resize = {
                RESIZE_ORIGINAL: "원본 크기",
                RESIZE_WIDTH: f"너비 {settings.width}px",
                RESIZE_HEIGHT: f"높이 {settings.height}px",
                RESIZE_CUSTOM: f"{settings.width}×{settings.height}px",
            }.get(settings.resize_mode, "원본 크기")
            quality = "무손실" if self._current_format == FORMAT_APNG else f"품질 {settings.quality}"
            summary = f"{quality} · {settings.fps}FPS · {resize}"
        self.settings_section.set_suffix(summary)

        if self._preferences.output_mode == OUTPUT_CUSTOM:
            output = self._preferences.output_folder or "직접 지정"
        else:
            output = "원본 영상과 같은 폴더"
        self.output_section.set_suffix(output)

    def _toggle_status_details(self, expanded: bool) -> None:
        self.status_detail_frame.setVisible(bool(expanded))
        self.details_button.setText("자세히 ▴" if expanded else "자세히 ▾")

    def _set_status(self, summary: str, detail: str | None = None, *, show_progress: bool | None = None) -> None:
        self.status_label.setText(summary)
        self.status_detail_label.setText(detail or summary)
        if show_progress is not None:
            self.progress_row_widget.setVisible(show_progress)

    def _open_result_file(self) -> None:
        path = Path(self._last_output_path)
        if not path.is_file():
            self._show_info("결과 파일", "완료된 결과 파일을 찾을 수 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _open_result_folder(self) -> None:
        path = Path(self._last_output_path)
        if path.is_file():
            folder = path.parent
        elif self._input_path:
            folder = Path(self._input_path).parent
        else:
            folder = Path(self._preferences.output_folder)
        if not folder.is_dir():
            self._show_info("결과 폴더", "결과 폴더를 찾을 수 없습니다.")
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

    def _ask_question(self, title: str, text: str) -> QMessageBox.StandardButton:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle(title)
        box.setText(title)
        box.setInformativeText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return QMessageBox.StandardButton(box.exec())

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(round(seconds)))
        hours, remainder = divmod(total, 3600)
        minutes, seconds_value = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{seconds_value:02d}" if hours else f"{minutes}:{seconds_value:02d}"

    @staticmethod
    def _format_file_size(size_bytes: int) -> str:
        if size_bytes >= 1024 * 1024:
            return f"{size_bytes / (1024 * 1024):.1f}MB"
        return f"{size_bytes / 1024:.1f}KB"
