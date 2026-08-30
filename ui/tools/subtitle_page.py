from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent, QFontMetrics, QIcon
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
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
    QVBoxLayout,
    QWidget,
)

from app.notifications import play_completion_sound
from app.paths import RRV_LOGS_DIR, SPIN_DOWN_ICON_PATH, SPIN_UP_ICON_PATH
from app.theme import themed_icon_path
from app.subtitle_log import subtitle_log_path
from app.subtitle_preferences import SubtitlePreferences, load_subtitle_preferences, save_subtitle_preferences
from core.subtitle_models import (
    EXTRACT_ASS,
    EXTRACT_ORIGINAL,
    EXTRACT_SRT,
    OP_EXTRACT,
    OP_INSERT,
    OP_REMOVE,
    OP_SYNC,
    OUTPUT_CUSTOM,
    OUTPUT_NEW_FILE,
    OUTPUT_OVERWRITE,
    OUTPUT_SOURCE,
    SubtitleOptions,
    SubtitleProbeResult,
    SubtitleResult,
    SubtitleTask,
)
from services.subtitle_service import (
    INSERT_VIDEO_EXTENSIONS,
    SUPPORTED_SUBTITLE_EXTENSIONS,
    SUPPORTED_TEXT_SUBTITLE_EXTENSIONS,
    SUPPORTED_VIDEO_EXTENSIONS,
    detect_subtitle_language,
    find_matching_subtitle,
    scan_folder_for_insert_tasks,
)
from ui.widgets.common import NoWheelSpinBox
from workers.subtitle_worker import SubtitleBatchWorker, SubtitleProbeWorker, SubtitleWorker

VIDEO_FILTER = "영상 파일 (*.mp4 *.m4v *.mov *.mkv *.webm *.avi *.ts *.m2ts)"
INSERT_VIDEO_FILTER = "영상 파일 (*.mp4 *.m4v *.mov *.mkv)"
SUBTITLE_FILTER = "자막 파일 (*.srt *.ass *.ssa *.vtt *.sup)"
TEXT_SUBTITLE_FILTER = "텍스트 자막 (*.srt *.ass *.ssa *.vtt)"
BATCH_INSERT_FILTER = "영상/자막 파일 (*.mp4 *.m4v *.mov *.mkv *.srt *.ass *.ssa *.vtt *.sup)"

MODE_LABELS = {
    OP_EXTRACT: "추출",
    OP_INSERT: "삽입",
    OP_SYNC: "싱크",
    OP_REMOVE: "제거",
}

LANGUAGE_NAMES = {
    "kor": "한국어",
    "eng": "English",
    "jpn": "日本語",
    "chi": "中文",
    "zho": "中文",
    "und": "언어 미지정",
}


class SubtitleDropFrame(QFrame):
    files_dropped = Signal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("subtitleDropArea")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event: QDropEvent) -> None:
        paths = [url.toLocalFile() for url in event.mimeData().urls() if url.isLocalFile()]
        if not paths:
            event.ignore()
            return
        self.files_dropped.emit(paths)
        event.acceptProposedAction()


class SubtitleCollapsibleSection(QFrame):
    toggled = Signal(bool)

    def __init__(self, title: str, expanded: bool) -> None:
        super().__init__()
        self._title = title
        self._expanded = bool(expanded)
        self._suffix = ""
        self.setObjectName("subtitleCollapsibleCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        self.header_button = QPushButton()
        self.header_button.setObjectName("subtitleCollapseButton")
        self.header_button.setCheckable(True)
        self.header_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_button.clicked.connect(self.set_expanded)
        outer.addWidget(self.header_button)
        self.body = QWidget()
        self.body.setObjectName("subtitleCollapsibleBody")
        self.body_layout = QVBoxLayout(self.body)
        self.body_layout.setContentsMargins(18, 14, 18, 18)
        self.body_layout.setSpacing(12)
        outer.addWidget(self.body)
        self._apply()

    @property
    def expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expanded: bool) -> None:
        expanded = bool(expanded)
        changed = expanded != self._expanded
        self._expanded = expanded
        self._apply()
        if changed:
            self.toggled.emit(expanded)

    def set_suffix(self, suffix: str) -> None:
        self._suffix = suffix.strip()
        self._apply()

    def set_title(self, title: str) -> None:
        self._title = title
        self._apply()

    def _apply(self) -> None:
        self.header_button.setChecked(self._expanded)
        arrow = "▼" if self._expanded else "▶"
        suffix = f"   {self._suffix}" if self._suffix else ""
        self.header_button.setText(f"{arrow}  {self._title}{suffix}")
        self.body.setVisible(self._expanded)


class SubtitleElidedLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__("")
        self._full_text = text
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self._apply()

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self._apply()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._apply()

    def sizeHint(self):
        hint = super().sizeHint()
        hint.setWidth(0)
        return hint

    def minimumSizeHint(self):
        hint = super().minimumSizeHint()
        hint.setWidth(0)
        return hint

    def _apply(self) -> None:
        width = max(20, self.contentsRect().width())
        self.setText(QFontMetrics(self.font()).elidedText(self._full_text, Qt.TextElideMode.ElideRight, width))


class SubtitleTaskRow(QFrame):
    remove_requested = Signal(object)

    def __init__(self, task: SubtitleTask, show_match_status: bool = False) -> None:
        super().__init__()
        self.task = task
        self.show_match_status = show_match_status
        self.state = "pending"
        self.output_paths: tuple[str, ...] = ()
        self.setObjectName("subtitleTaskRow")
        self.setMinimumWidth(0)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 8, 10, 8)
        layout.setSpacing(10)

        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        self.name_label = SubtitleElidedLabel()
        self.name_label.setObjectName("subtitleTaskTitle")
        text_layout.addWidget(self.name_label)
        self.match_label = SubtitleElidedLabel()
        self.match_label.setObjectName("subtitleTaskMatch")
        text_layout.addWidget(self.match_label)
        layout.addWidget(text_box, 1)

        self.status_label = QLabel("대기 중")
        self.status_label.setObjectName("subtitleTaskStatus")
        self.status_label.setMinimumWidth(82)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)
        self.remove_button = QPushButton("×")
        self.remove_button.setObjectName("iconTextButton")
        self.remove_button.setFixedWidth(32)
        self.remove_button.setToolTip("목록에서 제거")
        self.remove_button.clicked.connect(lambda: self.remove_requested.emit(self))
        layout.addWidget(self.remove_button)
        self.set_task(task)

    def set_task(self, task: SubtitleTask) -> None:
        self.task = task
        self.name_label.set_full_text(Path(task.primary_path).name)
        if self.show_match_status:
            if task.secondary_path:
                subtitle_name = Path(task.secondary_path).name
                self.match_label.set_full_text(f"자막 매칭 · {subtitle_name}")
                self.match_label.setProperty("matchState", "matched")
                self.status_label.setText("대기 중")
                self.status_label.setProperty("taskState", "pending")
                tip = f"영상\n{task.primary_path}\n\n자막\n{task.secondary_path}"
            else:
                self.match_label.set_full_text("자막 없음 · 자막 파일을 추가하거나 이 영상을 목록에서 제거해 주세요")
                self.match_label.setProperty("matchState", "missing")
                self.status_label.setText("자막 없음")
                self.status_label.setProperty("taskState", "warning")
                tip = f"영상\n{task.primary_path}\n\n매칭된 자막이 없습니다."
            self.match_label.setVisible(True)
            self.match_label.setToolTip(tip)
            self.name_label.setToolTip(tip)
            self.match_label.style().unpolish(self.match_label)
            self.match_label.style().polish(self.match_label)
            self.status_label.style().unpolish(self.status_label)
            self.status_label.style().polish(self.status_label)
        else:
            self.match_label.setVisible(False)
            self.name_label.setToolTip(task.primary_path)

    def set_status(self, text: str, state: str) -> None:
        self.state = state
        self.status_label.setText(text)
        self.status_label.setProperty("taskState", state)
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)


class SubtitlePage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._preferences = load_subtitle_preferences()
        self._operation = self._preferences.operation
        self._primary_path = ""
        self._secondary_path = ""
        self._probe_result: SubtitleProbeResult | None = None
        self._probe_worker: SubtitleProbeWorker | None = None
        self._worker: SubtitleWorker | None = None
        self._batch_worker: SubtitleBatchWorker | None = None
        self._batch_tasks: list[SubtitleTask] = []
        self._batch_rows: list[SubtitleTaskRow] = []
        self._track_checks: list[tuple[int, QCheckBox]] = []
        self._last_output_paths: tuple[str, ...] = ()
        self._batch_current = 0
        self._batch_total = 0

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self._save_preferences)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(10)
        title = QLabel("영상 자막 관리")
        title.setObjectName("sectionTitle")
        description = QLabel("영상의 자막을 추출·삽입·제거하거나 외부 자막의 전체 싱크를 간단하게 조정합니다.")
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        mode_row = QHBoxLayout()
        mode_row.setSpacing(7)
        mode_row.addWidget(QLabel("작업"))
        self.mode_group = QButtonGroup(self)
        self.mode_group.setExclusive(True)
        self.mode_buttons: dict[str, QPushButton] = {}
        for operation in (OP_EXTRACT, OP_INSERT, OP_SYNC, OP_REMOVE):
            button = QPushButton(MODE_LABELS[operation])
            button.setObjectName("subtitleModeButton")
            button.setCheckable(True)
            button.clicked.connect(lambda checked=False, op=operation: self._set_operation(op))
            self.mode_group.addButton(button)
            self.mode_buttons[operation] = button
            mode_row.addWidget(button)
        mode_row.addStretch()
        outer.addLayout(mode_row)

        scroll = QScrollArea()
        scroll.setObjectName("subtitleScroll")
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
        for section in (self.single_section, self.batch_section, self.settings_section, self.output_section):
            section.toggled.connect(self._section_state_changed)
            layout.addWidget(section)
        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)
        self.status_bar = self._create_status_bar()
        self.status_bar.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        outer.addWidget(self.status_bar)

        self._load_preferences_into_ui()
        self._apply_operation_ui(reset_inputs=False)
        self._refresh_batch_state()
        self._refresh_ui_state()
        subtitle_log_path()

    @property
    def has_active_operation(self) -> bool:
        return bool((self._worker and self._worker.isRunning()) or (self._batch_worker and self._batch_worker.isRunning()))

    def shutdown(self) -> None:
        self._save_preferences()
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            self._worker.wait(5000)
        if self._batch_worker and self._batch_worker.isRunning():
            self._batch_worker.cancel()
            self._batch_worker.wait(5000)
        if self._probe_worker and self._probe_worker.isRunning():
            self._probe_worker.requestInterruption()
            self._probe_worker.wait(1000)

    def _create_single_section(self) -> SubtitleCollapsibleSection:
        section = SubtitleCollapsibleSection("단일 영상", self._preferences.single_expanded)
        layout = section.body_layout
        self.primary_drop = SubtitleDropFrame()
        self.primary_drop.files_dropped.connect(self._handle_single_drop)
        drop_layout = QHBoxLayout(self.primary_drop)
        drop_layout.setContentsMargins(14, 12, 12, 12)
        self.primary_edit = QLineEdit()
        self.primary_edit.setObjectName("subtitlePathInput")
        self.primary_edit.setReadOnly(True)
        drop_layout.addWidget(self.primary_edit, 1)
        self.primary_choose_button = QPushButton("영상 선택")
        self.primary_choose_button.setObjectName("secondaryButton")
        self.primary_choose_button.clicked.connect(self._choose_primary_file)
        drop_layout.addWidget(self.primary_choose_button)
        layout.addWidget(self.primary_drop)

        self.secondary_row = SubtitleDropFrame()
        self.secondary_row.files_dropped.connect(self._handle_single_drop)
        sec_layout = QHBoxLayout(self.secondary_row)
        sec_layout.setContentsMargins(14, 10, 12, 10)
        sec_layout.setSpacing(10)
        sec_layout.addWidget(QLabel("외부 자막"))
        self.secondary_edit = QLineEdit()
        self.secondary_edit.setObjectName("subtitlePathInput")
        self.secondary_edit.setReadOnly(True)
        self.secondary_edit.setPlaceholderText("삽입할 SRT/ASS/SSA/VTT/SUP 자막을 선택해 주세요")
        sec_layout.addWidget(self.secondary_edit, 1)
        self.secondary_choose_button = QPushButton("자막 선택")
        self.secondary_choose_button.setObjectName("secondaryButton")
        self.secondary_choose_button.clicked.connect(self._choose_secondary_file)
        sec_layout.addWidget(self.secondary_choose_button)
        layout.addWidget(self.secondary_row)

        self.input_info_label = QLabel("파일을 선택하면 자막 정보를 확인합니다.")
        self.input_info_label.setObjectName("mutedText")
        self.input_info_label.setWordWrap(True)
        layout.addWidget(self.input_info_label)

        self.sync_settings = QWidget()
        sy = QHBoxLayout(self.sync_settings)
        sy.setContentsMargins(0, 0, 0, 0)
        sy.setSpacing(7)
        sy.addWidget(QLabel("싱크 조정"))
        self.sync_spin = NoWheelSpinBox()
        self.sync_spin.setObjectName("converterSpinBox")
        self.sync_spin.setRange(-3_600_000, 3_600_000)
        self.sync_spin.setSingleStep(100)
        self.sync_spin.setSuffix(" ms")
        self.sync_spin.valueChanged.connect(self._controls_changed)
        sy.addWidget(self.sync_spin)
        for text, value in (("-1초", -1000), ("-0.1초", -100), ("0", 0), ("+0.1초", 100), ("+1초", 1000)):
            button = QPushButton(text)
            button.setObjectName("compactButton")
            if value == 0:
                button.clicked.connect(lambda checked=False: self.sync_spin.setValue(0))
            else:
                button.clicked.connect(lambda checked=False, delta=value: self.sync_spin.setValue(self.sync_spin.value() + delta))
            sy.addWidget(button)
        sy.addStretch()
        layout.addWidget(self.sync_settings)

        self.sync_direction_label = QLabel("0.000초 · 자막 시간을 이동하지 않습니다.")
        self.sync_direction_label.setObjectName("mutedText")
        layout.addWidget(self.sync_direction_label)

        self.track_box = QFrame()
        self.track_box.setObjectName("subtitleTrackBox")
        track_layout = QVBoxLayout(self.track_box)
        track_layout.setContentsMargins(12, 10, 12, 10)
        track_layout.setSpacing(7)
        top = QHBoxLayout()
        self.track_title_label = QLabel("내장 자막")
        self.track_title_label.setObjectName("subtitleTrackTitle")
        top.addWidget(self.track_title_label)
        top.addStretch()
        self.select_all_button = QPushButton("모두 선택")
        self.select_all_button.setObjectName("compactButton")
        self.select_all_button.clicked.connect(self._select_all_tracks)
        top.addWidget(self.select_all_button)
        self.deselect_all_button = QPushButton("모두 해제")
        self.deselect_all_button.setObjectName("compactButton")
        self.deselect_all_button.clicked.connect(self._deselect_all_tracks)
        top.addWidget(self.deselect_all_button)
        track_layout.addLayout(top)
        self.track_items_widget = QWidget()
        self.track_items_layout = QVBoxLayout(self.track_items_widget)
        self.track_items_layout.setContentsMargins(0, 0, 0, 0)
        self.track_items_layout.setSpacing(5)
        track_layout.addWidget(self.track_items_widget)
        layout.addWidget(self.track_box)

        actions = QHBoxLayout()
        actions.addStretch()
        self.single_start_button = QPushButton("자막 추출")
        self.single_start_button.setObjectName("primaryButton")
        self.single_start_button.clicked.connect(self._start_single)
        actions.addWidget(self.single_start_button)
        layout.addLayout(actions)
        return section

    def _create_batch_section(self) -> SubtitleCollapsibleSection:
        section = SubtitleCollapsibleSection("여러 영상", self._preferences.batch_expanded)
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

        self.batch_drop = SubtitleDropFrame()
        self.batch_drop.files_dropped.connect(self._handle_batch_drop)
        batch_drop_layout = QHBoxLayout(self.batch_drop)
        batch_drop_layout.setContentsMargins(12, 9, 12, 9)
        self.batch_drop_label = QLabel("영상·자막·폴더를 여기에 끌어놓아도 됩니다.")
        self.batch_drop_label.setObjectName("mutedText")
        batch_drop_layout.addWidget(self.batch_drop_label)
        batch_drop_layout.addStretch()
        layout.addWidget(self.batch_drop)

        self.batch_sync_hint = QLabel("현재 싱크 조정값을 여러 자막에 동일하게 적용합니다.")
        self.batch_sync_hint.setObjectName("mutedText")
        self.batch_sync_hint.setWordWrap(True)
        layout.addWidget(self.batch_sync_hint)

        self.queue_scroll = QScrollArea()
        self.queue_scroll.setObjectName("subtitleQueueScroll")
        self.queue_scroll.setWidgetResizable(True)
        self.queue_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.queue_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.queue_scroll.setMinimumHeight(185)
        self.queue_scroll.setMaximumHeight(310)
        queue_content = QWidget()
        self.queue_layout = QVBoxLayout(queue_content)
        self.queue_layout.setContentsMargins(0, 0, 0, 0)
        self.queue_layout.setSpacing(7)
        self.queue_empty_label = QLabel("아직 추가된 작업이 없습니다.")
        self.queue_empty_label.setObjectName("subtitleQueueEmpty")
        self.queue_empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.queue_layout.addWidget(self.queue_empty_label)
        self.queue_layout.addStretch()
        self.queue_scroll.setWidget(queue_content)
        layout.addWidget(self.queue_scroll)

        bottom = QHBoxLayout()
        self.batch_count_label = QLabel("0개 작업")
        self.batch_count_label.setObjectName("mutedText")
        bottom.addWidget(self.batch_count_label)
        bottom.addStretch()
        self.batch_start_button = QPushButton("여러 영상 자막 추출")
        self.batch_start_button.setObjectName("primaryButton")
        self.batch_start_button.clicked.connect(self._start_batch)
        bottom.addWidget(self.batch_start_button)
        layout.addLayout(bottom)
        return section

    def _create_settings_section(self) -> SubtitleCollapsibleSection:
        section = SubtitleCollapsibleSection("작업 설정", self._preferences.settings_expanded)
        layout = section.body_layout

        self.extract_settings = QWidget()
        ex = QHBoxLayout(self.extract_settings)
        ex.setContentsMargins(0, 0, 0, 0)
        ex.addWidget(QLabel("추출 형식"))
        self.extract_format_combo = QComboBox()
        self.extract_format_combo.setObjectName("settingsComboBox")
        self.extract_format_combo.addItem("원본 형식 유지", EXTRACT_ORIGINAL)
        self.extract_format_combo.addItem("SRT로 변환", EXTRACT_SRT)
        self.extract_format_combo.addItem("ASS로 변환", EXTRACT_ASS)
        self.extract_format_combo.currentIndexChanged.connect(self._controls_changed)
        ex.addWidget(self.extract_format_combo)
        note = QLabel("이미지형 PGS/DVD 자막은 원본 형식으로만 안전하게 추출합니다.")
        note.setObjectName("mutedText")
        note.setWordWrap(True)
        ex.addWidget(note, 1)
        layout.addWidget(self.extract_settings)

        self.insert_settings = QWidget()
        ins = QGridLayout(self.insert_settings)
        ins.setContentsMargins(0, 0, 0, 0)
        ins.setHorizontalSpacing(12)
        ins.setVerticalSpacing(8)
        ins.addWidget(QLabel("언어"), 0, 0)
        self.language_combo = QComboBox()
        self.language_combo.setObjectName("settingsComboBox")
        self.language_combo.setEditable(False)
        for label, code in (("자동 감지 (권장)", "auto"), ("한국어 (kor)", "kor"), ("English (eng)", "eng"), ("日本語 (jpn)", "jpn"), ("中文 (chi)", "chi"), ("미지정 (und)", "und")):
            self.language_combo.addItem(label, code)
        self.language_combo.currentIndexChanged.connect(self._controls_changed)
        ins.addWidget(self.language_combo, 0, 1)
        ins.addWidget(QLabel("트랙 이름 (선택)"), 0, 2)
        self.track_name_edit = QLineEdit()
        self.track_name_edit.setPlaceholderText("비워두면 언어 이름을 자동 사용")
        self.track_name_edit.textChanged.connect(self._controls_changed)
        ins.addWidget(self.track_name_edit, 0, 3)

        self.language_detect_label = QLabel("자동 감지는 파일명 언어 코드와 자막 내용을 순서대로 확인합니다.")
        self.language_detect_label.setObjectName("mutedText")
        self.language_detect_label.setWordWrap(True)
        ins.addWidget(self.language_detect_label, 1, 0, 1, 4)

        self.default_check = QCheckBox("기본으로 선택")
        self.forced_check = QCheckBox("강제 표시용")
        self.default_check.setObjectName("previewCheckBox")
        self.forced_check.setObjectName("previewCheckBox")
        self.default_check.toggled.connect(self._controls_changed)
        self.forced_check.toggled.connect(self._controls_changed)
        ins.addWidget(self.default_check, 2, 0, 1, 2)
        ins.addWidget(self.forced_check, 2, 2, 1, 2)
        default_help = QLabel("영상을 열 때 플레이어가 기본 자막 후보로 취급하도록 표시합니다.")
        default_help.setObjectName("mutedText")
        default_help.setWordWrap(True)
        forced_help = QLabel("외국어 대사·표지판처럼 강제로 표시할 자막에 forced 플래그를 지정합니다.")
        forced_help.setObjectName("mutedText")
        forced_help.setWordWrap(True)
        ins.addWidget(default_help, 3, 0, 1, 2)
        ins.addWidget(forced_help, 3, 2, 1, 2)

        self.delete_external_check = QCheckBox("삽입 완료 후 외부 자막 파일 삭제")
        self.delete_external_check.setObjectName("previewCheckBox")
        self.delete_external_check.toggled.connect(self._controls_changed)
        ins.addWidget(self.delete_external_check, 4, 0, 1, 4)
        delete_help = QLabel("결과 영상에서 새 자막 트랙을 확인한 뒤에만 SRT/ASS 같은 원본 자막 파일을 삭제합니다.")
        delete_help.setObjectName("mutedText")
        delete_help.setWordWrap(True)
        ins.addWidget(delete_help, 5, 0, 1, 4)
        layout.addWidget(self.insert_settings)
        return section

    def _create_output_section(self) -> SubtitleCollapsibleSection:
        section = SubtitleCollapsibleSection("출력 위치", self._preferences.output_expanded)
        layout = section.body_layout
        self.output_mode_widget = QWidget()
        mode_layout = QHBoxLayout(self.output_mode_widget)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.overwrite_radio = QRadioButton("원본에 안전하게 적용")
        self.new_file_radio = QRadioButton("새 파일로 저장")
        self.overwrite_radio.setObjectName("settingsRadioButton")
        self.new_file_radio.setObjectName("settingsRadioButton")
        self.output_mode_group = QButtonGroup(self)
        self.output_mode_group.addButton(self.overwrite_radio)
        self.output_mode_group.addButton(self.new_file_radio)
        self.overwrite_radio.toggled.connect(self._controls_changed)
        self.new_file_radio.toggled.connect(self._controls_changed)
        mode_layout.addWidget(self.overwrite_radio)
        mode_layout.addWidget(self.new_file_radio)
        mode_layout.addStretch()
        layout.addWidget(self.output_mode_widget)

        folder_row = QHBoxLayout()
        self.source_folder_radio = QRadioButton("원본과 같은 폴더")
        self.custom_folder_radio = QRadioButton("지정 폴더")
        self.source_folder_radio.setObjectName("settingsRadioButton")
        self.custom_folder_radio.setObjectName("settingsRadioButton")
        self.folder_group = QButtonGroup(self)
        self.folder_group.addButton(self.source_folder_radio)
        self.folder_group.addButton(self.custom_folder_radio)
        self.source_folder_radio.toggled.connect(self._controls_changed)
        self.custom_folder_radio.toggled.connect(self._controls_changed)
        folder_row.addWidget(self.source_folder_radio)
        folder_row.addWidget(self.custom_folder_radio)
        self.output_edit = QLineEdit()
        self.output_edit.setObjectName("subtitlePathInput")
        self.output_edit.textChanged.connect(self._controls_changed)
        folder_row.addWidget(self.output_edit, 1)
        self.output_choose_button = QPushButton("폴더 선택")
        self.output_choose_button.setObjectName("secondaryButton")
        self.output_choose_button.clicked.connect(self._choose_output_folder)
        folder_row.addWidget(self.output_choose_button)
        layout.addLayout(folder_row)
        return section

    def _create_status_bar(self) -> QFrame:
        bar = QFrame()
        bar.setObjectName("subtitleStatusBar")
        outer = QVBoxLayout(bar)
        outer.setContentsMargins(14, 10, 14, 10)
        outer.setSpacing(7)
        top = QHBoxLayout()
        self.status_title = QLabel("● 대기 중")
        self.status_title.setObjectName("subtitleStatusTitle")
        top.addWidget(self.status_title)
        self.status_text = SubtitleElidedLabel("자막 작업을 선택하고 파일을 추가합니다.")
        self.status_text.setObjectName("subtitleStatusText")
        top.addWidget(self.status_text, 1)
        self.status_counter = QLabel("")
        self.status_counter.setObjectName("subtitleStatusCounter")
        top.addWidget(self.status_counter)
        self.quick_actions = QWidget()
        qa = QHBoxLayout(self.quick_actions)
        qa.setContentsMargins(0, 0, 0, 0)
        qa.setSpacing(5)
        self.quick_open_result_button = QPushButton("결과 열기")
        self.quick_open_result_button.setObjectName("subtitleQuickActionButton")
        self.quick_open_result_button.clicked.connect(self._open_result)
        qa.addWidget(self.quick_open_result_button)
        self.quick_open_folder_button = QPushButton("폴더 열기")
        self.quick_open_folder_button.setObjectName("subtitleQuickActionButton")
        self.quick_open_folder_button.clicked.connect(self._open_result_folder)
        qa.addWidget(self.quick_open_folder_button)
        self.quick_actions.setVisible(False)
        top.addWidget(self.quick_actions)
        self.status_details_button = QPushButton("자세히")
        self.status_details_button.setObjectName("subtitleStatusDetailsButton")
        self.status_details_button.setIcon(
            QIcon(str(themed_icon_path(SPIN_DOWN_ICON_PATH)))
        )
        self.status_details_button.setIconSize(QSize(12, 8))
        self.status_details_button.setCheckable(True)
        self.status_details_button.clicked.connect(self._toggle_status_detail)
        top.addWidget(self.status_details_button)
        outer.addLayout(top)
        progress_row = QHBoxLayout()
        self.status_progress = QProgressBar()
        self.status_progress.setObjectName("subtitleStatusProgress")
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.setTextVisible(True)
        self.status_progress.setVisible(False)
        progress_row.addWidget(self.status_progress, 1)
        self.status_stop_button = QPushButton("■ 중지")
        self.status_stop_button.setObjectName("subtitleStatusStopButton")
        self.status_stop_button.clicked.connect(self._stop_operation)
        self.status_stop_button.setVisible(False)
        progress_row.addWidget(self.status_stop_button)
        outer.addLayout(progress_row)
        self.status_detail = QFrame()
        self.status_detail.setObjectName("subtitleStatusDetail")
        detail_layout = QVBoxLayout(self.status_detail)
        detail_layout.setContentsMargins(10, 8, 10, 8)
        self.status_detail_label = QLabel("아직 작업 결과가 없습니다.")
        self.status_detail_label.setObjectName("subtitleStatusDetailText")
        self.status_detail_label.setWordWrap(True)
        detail_layout.addWidget(self.status_detail_label)
        detail_buttons = QHBoxLayout()
        self.open_result_button = QPushButton("결과 열기")
        self.open_result_button.setObjectName("secondaryButton")
        self.open_result_button.clicked.connect(self._open_result)
        self.open_result_button.setEnabled(False)
        detail_buttons.addWidget(self.open_result_button)
        self.open_folder_button = QPushButton("결과 폴더 열기")
        self.open_folder_button.setObjectName("secondaryButton")
        self.open_folder_button.clicked.connect(self._open_result_folder)
        self.open_folder_button.setEnabled(False)
        detail_buttons.addWidget(self.open_folder_button)
        log_button = QPushButton("로그 폴더 열기")
        log_button.setObjectName("secondaryButton")
        log_button.clicked.connect(self._open_log_folder)
        detail_buttons.addWidget(log_button)
        detail_buttons.addStretch()
        detail_layout.addLayout(detail_buttons)
        self.status_detail.setVisible(False)
        outer.addWidget(self.status_detail)
        return bar

    def _set_operation(self, operation: str) -> None:
        if self.has_active_operation or operation == self._operation:
            return
        self._operation = operation
        self._clear_single_input()
        self._clear_batch()
        self._apply_operation_ui(reset_inputs=False)
        self._controls_changed()

    def _apply_operation_ui(self, reset_inputs: bool = False) -> None:
        self.mode_buttons[self._operation].setChecked(True)
        is_sync = self._operation == OP_SYNC
        is_insert = self._operation == OP_INSERT
        is_tracks = self._operation in {OP_EXTRACT, OP_REMOVE}
        self.single_section.set_title("단일 자막" if is_sync else "단일 영상")
        self.batch_section.set_title("여러 자막" if is_sync else "여러 영상")
        self.primary_choose_button.setText("자막 선택" if is_sync else "영상 선택")
        self.primary_edit.setPlaceholderText("자막 파일을 끌어놓거나 선택해 주세요" if is_sync else "영상 파일을 끌어놓거나 선택해 주세요")
        self.secondary_row.setVisible(is_insert)
        self.track_box.setVisible(is_tracks and self._probe_result is not None)
        self.sync_settings.setVisible(is_sync)
        self.sync_direction_label.setVisible(is_sync)
        self.batch_sync_hint.setVisible(is_sync)
        self.extract_settings.setVisible(self._operation == OP_EXTRACT)
        self.insert_settings.setVisible(is_insert)
        self.settings_section.setVisible(self._operation in {OP_EXTRACT, OP_INSERT})
        settings_titles = {
            OP_EXTRACT: "추출 설정",
            OP_INSERT: "삽입 설정",
        }
        if self._operation in settings_titles:
            self.settings_section.set_title(settings_titles[self._operation])
        self.output_mode_widget.setVisible(self._operation in {OP_INSERT, OP_REMOVE, OP_SYNC})
        self.batch_files_button.setVisible(True)
        self.batch_files_button.setText("파일 추가" if is_insert else ("자막 여러 개 추가" if is_sync else "파일 여러 개 추가"))
        self.batch_folder_button.setText("폴더 자동 매칭" if is_insert else "폴더 추가")
        self.batch_drop.setVisible(True)
        self.batch_drop_label.setText("영상·자막·폴더를 함께 끌어놓으면 자동으로 매칭합니다." if is_insert else ("자막 파일이나 폴더를 여기에 끌어놓아도 됩니다." if is_sync else "영상 파일이나 폴더를 여기에 끌어놓아도 됩니다."))
        action = MODE_LABELS[self._operation]
        self.single_start_button.setText(f"자막 {action}" if self._operation != OP_SYNC else "싱크 보정")
        self.batch_start_button.setText(
            "여러 자막 싱크 보정" if is_sync else f"여러 영상 자막 {action}"
        )
        if is_sync:
            self.sync_spin.setValue(0)
        self._refresh_section_summaries()
        self._refresh_output_controls()
        self._refresh_ui_state()

    def _choose_primary_file(self) -> None:
        if self._operation == OP_SYNC:
            path, _ = QFileDialog.getOpenFileName(self, "자막 선택", "", TEXT_SUBTITLE_FILTER)
        else:
            filter_text = INSERT_VIDEO_FILTER if self._operation == OP_INSERT else VIDEO_FILTER
            path, _ = QFileDialog.getOpenFileName(self, "영상 선택", "", filter_text)
        if path:
            self._set_primary_file(path)

    def _handle_single_drop(self, paths: object) -> None:
        if self.has_active_operation:
            return
        if not isinstance(paths, (list, tuple)):
            return
        local_paths = [str(Path(p)) for p in paths if isinstance(p, str) and Path(p).is_file()]
        if not local_paths:
            return
        if self._operation == OP_SYNC:
            for path in local_paths:
                if Path(path).suffix.lower() in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS:
                    self._set_primary_file(path)
                    return
            self._show_warning("자막 파일 확인", "싱크는 SRT/ASS/SSA/VTT 자막을 지원합니다.")
            return
        if self._operation == OP_INSERT:
            video_path = ""
            subtitle_path = ""
            for path in local_paths:
                suffix = Path(path).suffix.lower()
                if not video_path and suffix in INSERT_VIDEO_EXTENSIONS:
                    video_path = path
                elif not subtitle_path and suffix in SUPPORTED_SUBTITLE_EXTENSIONS:
                    subtitle_path = path
            if video_path:
                self._set_primary_file(video_path)
            if subtitle_path:
                self._set_secondary_file(subtitle_path)
            if not video_path and not subtitle_path:
                self._show_warning("파일 형식 확인", "영상 또는 SRT/ASS/SSA/VTT/SUP 자막을 끌어놓아 주세요.")
            return
        for path in local_paths:
            if Path(path).suffix.lower() in SUPPORTED_VIDEO_EXTENSIONS:
                self._set_primary_file(path)
                return
        self._show_warning("영상 형식 확인", "지원하는 영상 파일을 끌어놓아 주세요.")

    def _set_primary_file(self, path: str) -> None:
        if self.has_active_operation:
            return
        p = Path(path)
        if self._operation == OP_SYNC:
            if p.suffix.lower() not in SUPPORTED_TEXT_SUBTITLE_EXTENSIONS:
                self._show_warning("자막 파일 확인", "싱크는 SRT/ASS/SSA/VTT 자막을 지원합니다.")
                return
            self._primary_path = str(p)
            self.sync_spin.setValue(0)
            self.primary_edit.setText(str(p))
            self.input_info_label.setText(f"{p.name} · 전체 자막 시간을 한 번에 이동합니다.")
            self._probe_result = None
            self.track_box.setVisible(False)
            self._refresh_ui_state()
            return
        allowed = INSERT_VIDEO_EXTENSIONS if self._operation == OP_INSERT else SUPPORTED_VIDEO_EXTENSIONS
        if p.suffix.lower() not in allowed:
            self._show_warning("영상 형식 확인", "이 작업에서 지원하지 않는 영상 형식입니다.")
            return
        self._primary_path = str(p)
        self.primary_edit.setText(str(p))
        self._probe_result = None
        self._clear_track_checks()
        self.input_info_label.setText("영상과 내장 자막 정보를 확인하는 중…")
        self._start_probe(str(p))

    def _start_probe(self, path: str) -> None:
        if self._probe_worker and self._probe_worker.isRunning():
            return
        worker = SubtitleProbeWorker(path)
        self._probe_worker = worker
        worker.succeeded.connect(self._probe_succeeded)
        worker.failed.connect(self._probe_failed)
        worker.finished.connect(lambda: setattr(self, "_probe_worker", None))
        worker.start()

    def _probe_succeeded(self, result: object) -> None:
        if not isinstance(result, SubtitleProbeResult) or result.video_path != self._primary_path:
            return
        self._probe_result = result
        duration = self._format_duration(result.duration)
        self.input_info_label.setText(f"{result.width}×{result.height} · {duration} · {result.video_codec} · 내장 자막 {len(result.tracks)}개")
        if self._operation in {OP_EXTRACT, OP_REMOVE}:
            self._build_track_checks(result)
            self.track_box.setVisible(True)
        elif self._operation == OP_INSERT and not self._secondary_path:
            match = find_matching_subtitle(self._primary_path)
            if match:
                self._set_secondary_file(match)
        self._refresh_ui_state()

    def _probe_failed(self, message: str, detail: str) -> None:
        self._probe_result = None
        self.input_info_label.setText(message)
        self._show_warning("자막 분석 실패", message, detail)
        self._refresh_ui_state()

    def _build_track_checks(self, result: SubtitleProbeResult) -> None:
        self._clear_track_checks()
        if not result.tracks:
            label = QLabel("내장 자막이 없습니다.")
            label.setObjectName("mutedText")
            self.track_items_layout.addWidget(label)
            return
        for track in result.tracks:
            lang = LANGUAGE_NAMES.get(track.language.lower(), track.language or "und")
            kind = "이미지" if track.is_image else "텍스트"
            flags = []
            if track.is_default:
                flags.append("기본")
            if track.is_forced:
                flags.append("강제")
            suffix = f" · {' · '.join(flags)}" if flags else ""
            title = f"{track.subtitle_index + 1}. {lang} · {track.codec_name.upper()} · {kind}{suffix}"
            if track.title:
                title += f" · {track.title}"
            check = QCheckBox(title)
            check.setObjectName("previewCheckBox")
            check.setChecked(True)
            check.toggled.connect(self._refresh_ui_state)
            self.track_items_layout.addWidget(check)
            self._track_checks.append((track.stream_index, check))

    def _clear_track_checks(self) -> None:
        while self.track_items_layout.count():
            item = self.track_items_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._track_checks.clear()

    def _select_all_tracks(self) -> None:
        for _, check in self._track_checks:
            check.setChecked(True)

    def _deselect_all_tracks(self) -> None:
        for _, check in self._track_checks:
            check.setChecked(False)

    def _choose_secondary_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "외부 자막 선택", "", SUBTITLE_FILTER)
        if path:
            self._set_secondary_file(path)

    def _set_secondary_file(self, path: str) -> None:
        p = Path(path)
        if not p.is_file() or p.suffix.lower() not in SUPPORTED_SUBTITLE_EXTENSIONS:
            self._show_warning("자막 파일 확인", "SRT/ASS/SSA/VTT/SUP 자막을 선택해 주세요.")
            return
        if self._primary_path and Path(self._primary_path).suffix.lower() in {".mp4", ".m4v", ".mov"} and p.suffix.lower() == ".sup":
            self._show_warning("자막 형식 확인", "MP4 계열에는 SUP 이미지 자막을 안전하게 넣을 수 없습니다.", "MKV 영상을 사용해 주세요.")
            return
        self._secondary_path = str(p)
        self.secondary_edit.setText(str(p))
        code, title, source = detect_subtitle_language(str(p))
        source_label = {"filename": "파일명", "content": "자막 내용", "unknown": "판단 단서 없음"}.get(source, source)
        detected = "언어 미지정" if code == "und" else f"{title or code} ({code})"
        self.language_detect_label.setText(f"자동 감지 예상: {detected} · 기준: {source_label}")
        if self._primary_path and Path(self._primary_path).suffix.lower() in {".mp4", ".m4v", ".mov"} and p.suffix.lower() in {".ass", ".ssa"}:
            base = self.input_info_label.text().split("\nMP4에 넣을 때", 1)[0]
            self.input_info_label.setText(base + "\nMP4에 넣을 때 ASS 스타일은 단순 자막으로 변환될 수 있습니다.")
        self._refresh_ui_state()

    def _choose_batch_files(self) -> None:
        if self._operation == OP_INSERT:
            paths, _ = QFileDialog.getOpenFileNames(self, "영상/자막 파일 선택", "", BATCH_INSERT_FILTER)
            self._handle_batch_drop(paths)
            return
        if self._operation == OP_SYNC:
            paths, _ = QFileDialog.getOpenFileNames(self, "자막 여러 개 선택", "", TEXT_SUBTITLE_FILTER)
        else:
            paths, _ = QFileDialog.getOpenFileNames(self, "영상 여러 개 선택", "", VIDEO_FILTER)
        self._add_batch_paths(paths)

    def _handle_batch_drop(self, paths: object) -> None:
        if self.has_active_operation or not isinstance(paths, (list, tuple)):
            return
        raw_paths = [Path(str(p)) for p in paths if isinstance(p, str)]
        if not raw_paths:
            return

        if self._operation == OP_INSERT:
            dropped_subtitles: list[str] = []
            dropped_videos: list[str] = []
            for path in raw_paths:
                if path.is_dir():
                    self._add_batch_tasks(scan_folder_for_insert_tasks(str(path)))
                    continue
                if not path.is_file():
                    continue
                if path.suffix.lower() in INSERT_VIDEO_EXTENSIONS:
                    dropped_videos.append(str(path))
                elif path.suffix.lower() in SUPPORTED_SUBTITLE_EXTENSIONS:
                    dropped_subtitles.append(str(path))

            new_tasks: list[SubtitleTask] = []
            for video in dropped_videos:
                match = find_matching_subtitle(video, dropped_subtitles) or find_matching_subtitle(video)
                new_tasks.append(SubtitleTask(video, match))
            self._add_batch_tasks(new_tasks)

            if dropped_subtitles:
                for index, task in enumerate(list(self._batch_tasks)):
                    if task.secondary_path:
                        continue
                    match = find_matching_subtitle(task.primary_path, dropped_subtitles) or find_matching_subtitle(task.primary_path)
                    if match:
                        updated = SubtitleTask(task.primary_path, match)
                        self._batch_tasks[index] = updated
                        self._batch_rows[index].set_task(updated)
                self._refresh_batch_state()
            return

        for path in raw_paths:
            if path.is_dir():
                extensions = SUPPORTED_TEXT_SUBTITLE_EXTENSIONS if self._operation == OP_SYNC else SUPPORTED_VIDEO_EXTENSIONS
                self._add_batch_paths([str(p) for p in sorted(path.iterdir(), key=lambda x: x.name.lower()) if p.is_file() and p.suffix.lower() in extensions])
            elif path.is_file():
                self._add_batch_paths([str(path)])

    def _choose_batch_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "폴더 선택", "")
        if not folder:
            return
        root = Path(folder)
        if self._operation == OP_INSERT:
            self._add_batch_tasks(scan_folder_for_insert_tasks(folder))
            return
        extensions = SUPPORTED_TEXT_SUBTITLE_EXTENSIONS if self._operation == OP_SYNC else SUPPORTED_VIDEO_EXTENSIONS
        self._add_batch_paths([str(p) for p in sorted(root.iterdir(), key=lambda x: x.name.lower()) if p.is_file() and p.suffix.lower() in extensions])

    def _add_batch_paths(self, paths: list[str]) -> None:
        extensions = SUPPORTED_TEXT_SUBTITLE_EXTENSIONS if self._operation == OP_SYNC else SUPPORTED_VIDEO_EXTENSIONS
        tasks = [SubtitleTask(str(Path(p))) for p in paths if Path(p).is_file() and Path(p).suffix.lower() in extensions]
        self._add_batch_tasks(tasks)

    def _add_batch_tasks(self, tasks: list[SubtitleTask]) -> None:
        primary_to_index = {Path(t.primary_path).resolve().as_posix().casefold(): i for i, t in enumerate(self._batch_tasks)}
        existing_pairs = {
            (Path(t.primary_path).resolve().as_posix().casefold(), Path(t.secondary_path).resolve().as_posix().casefold() if t.secondary_path else "")
            for t in self._batch_tasks
        }
        for task in tasks:
            primary_key = Path(task.primary_path).resolve().as_posix().casefold()
            if self._operation == OP_INSERT and primary_key in primary_to_index:
                index = primary_to_index[primary_key]
                existing_task = self._batch_tasks[index]
                if not existing_task.secondary_path and task.secondary_path:
                    self._batch_tasks[index] = task
                    self._batch_rows[index].set_task(task)
                continue
            pair_key = (primary_key, Path(task.secondary_path).resolve().as_posix().casefold() if task.secondary_path else "")
            if pair_key in existing_pairs:
                continue
            existing_pairs.add(pair_key)
            primary_to_index[primary_key] = len(self._batch_tasks)
            self._batch_tasks.append(task)
            row = SubtitleTaskRow(task, show_match_status=self._operation == OP_INSERT)
            row.remove_requested.connect(self._remove_batch_row)
            self._batch_rows.append(row)
            self.queue_layout.insertWidget(self.queue_layout.count() - 1, row)
        self._refresh_batch_state()

    def _remove_batch_row(self, row: SubtitleTaskRow) -> None:
        if self.has_active_operation:
            return
        try:
            index = self._batch_rows.index(row)
        except ValueError:
            return
        self._batch_rows.pop(index)
        self._batch_tasks.pop(index)
        row.deleteLater()
        self._refresh_batch_state()

    def _clear_batch(self) -> None:
        if self.has_active_operation:
            return
        for row in self._batch_rows:
            row.deleteLater()
        self._batch_rows.clear()
        self._batch_tasks.clear()
        self._refresh_batch_state()

    def _refresh_batch_state(self) -> None:
        count = len(self._batch_tasks)
        self.queue_empty_label.setVisible(count == 0)
        if self._operation == OP_INSERT and count:
            matched = sum(1 for task in self._batch_tasks if task.secondary_path)
            missing = count - matched
            text = f"{count}개 영상 · 매칭 {matched}개"
            if missing:
                text += f" · 자막 없음 {missing}개"
            self.batch_count_label.setText(text)
            self.batch_section.set_suffix(f"{count}개 · 매칭 {matched}개")
            ready = matched == count
        else:
            self.batch_count_label.setText(f"{count}개 작업")
            self.batch_section.set_suffix(f"{count}개" if count else "")
            ready = count > 0
        self.batch_start_button.setEnabled(ready and not self.has_active_operation)
        self.batch_clear_button.setEnabled(count > 0 and not self.has_active_operation)

    def _choose_output_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "출력 폴더", self.output_edit.text().strip() or str(Path.home()))
        if folder:
            self.output_edit.setText(folder)

    def _start_single(self) -> None:
        if self.has_active_operation:
            return
        task, options = self._build_single_task_and_options()
        if task is None or options is None:
            return
        self._last_output_paths = ()
        self.quick_actions.setVisible(False)
        self.open_result_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        action = MODE_LABELS[self._operation]
        self._set_status(f"● 자막 {action} 중", Path(task.primary_path).name, "현재 작업 결과가 아직 없습니다.", True)
        worker = SubtitleWorker(task, options)
        self._worker = worker
        self._set_controls_enabled(False)
        worker.phase_changed.connect(lambda text: self.status_text.set_full_text(text))
        worker.progress_changed.connect(self._single_progress_changed)
        worker.succeeded.connect(self._single_succeeded)
        worker.failed.connect(self._single_failed)
        worker.cancelled.connect(self._single_cancelled)
        worker.finished.connect(self._single_finished)
        worker.start()

    def _start_batch(self) -> None:
        if self.has_active_operation or not self._batch_tasks:
            return
        options = self._build_options(batch=True)
        if options is None:
            return
        self._last_output_paths = ()
        self._batch_current = 0
        self._batch_total = len(self._batch_tasks)
        for row in self._batch_rows:
            row.output_paths = ()
            row.set_status("대기 중", "pending")
        self.status_counter.setText(f"0 / {self._batch_total}")
        self.quick_actions.setVisible(False)
        self.open_result_button.setEnabled(False)
        self.open_folder_button.setEnabled(False)
        action = "싱크 보정" if self._operation == OP_SYNC else f"자막 {MODE_LABELS[self._operation]}"
        self._set_status(f"● 여러 {action} 중", "첫 작업을 준비하는 중", "현재 작업 결과가 아직 없습니다.", True)
        worker = SubtitleBatchWorker(self._batch_tasks, options)
        self._batch_worker = worker
        self._set_controls_enabled(False)
        worker.current_changed.connect(self._batch_current_changed)
        worker.item_started.connect(self._batch_item_started)
        worker.item_progress.connect(self._batch_item_progress)
        worker.item_succeeded.connect(self._batch_item_succeeded)
        worker.item_failed.connect(self._batch_item_failed)
        worker.cancelled.connect(self._batch_cancelled)
        worker.completed.connect(self._batch_completed)
        worker.finished.connect(self._batch_finished)
        worker.start()

    def _build_single_task_and_options(self) -> tuple[SubtitleTask | None, SubtitleOptions | None]:
        if not self._primary_path:
            return None, None
        if self._operation == OP_INSERT and not self._secondary_path:
            self._show_warning("자막 선택", "삽입할 외부 자막을 선택해 주세요.")
            return None, None
        options = self._build_options(batch=False)
        if options is None:
            return None, None
        return SubtitleTask(self._primary_path, self._secondary_path if self._operation == OP_INSERT else ""), options

    def _build_options(self, batch: bool) -> SubtitleOptions | None:
        if self.custom_folder_radio.isChecked() and not self.output_edit.text().strip():
            self._show_warning("출력 위치", "지정 출력 폴더를 선택해 주세요.")
            return None
        selected: tuple[int, ...] = ()
        if not batch and self._operation in {OP_EXTRACT, OP_REMOVE}:
            selected = tuple(index for index, check in self._track_checks if check.isChecked())
            if not selected:
                self._show_warning("자막 선택", "작업할 내장 자막 트랙을 선택해 주세요.")
                return None
        language = str(self.language_combo.currentData() or "auto").strip()
        self._save_preferences()
        return SubtitleOptions(
            operation=self._operation,
            selected_stream_indices=selected,
            extract_format=str(self.extract_format_combo.currentData() or EXTRACT_ORIGINAL),
            language=language,
            track_title=self.track_name_edit.text().strip(),
            make_default=self.default_check.isChecked(),
            make_forced=self.forced_check.isChecked(),
            delete_external_after_insert=self.delete_external_check.isChecked(),
            sync_offset_ms=self.sync_spin.value(),
            output_mode=OUTPUT_NEW_FILE if self.new_file_radio.isChecked() else OUTPUT_OVERWRITE,
            output_folder_mode=OUTPUT_CUSTOM if self.custom_folder_radio.isChecked() else OUTPUT_SOURCE,
            output_folder=self.output_edit.text().strip(),
        )

    def _single_succeeded(self, result: object) -> None:
        if not isinstance(result, SubtitleResult):
            return
        self._last_output_paths = result.output_paths
        filename = Path(result.output_paths[0]).name if result.output_paths else result.message
        self._set_status("완료", filename, result.message + ("\n" + "\n".join(result.output_paths) if result.output_paths else ""), False)
        self._show_quick_actions()
        if self._operation == OP_SYNC:
            self.sync_spin.setValue(0)
        self._clear_single_input()
        play_completion_sound()

    def _single_progress_changed(self, percent: int, detail: str) -> None:
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(max(0, min(100, int(percent))))
        self.status_progress.setFormat(f"{max(0, min(100, int(percent)))}%")
        self.status_text.set_full_text(detail)
        self.status_detail_label.setText(detail)

    def _single_failed(self, message: str, detail: str) -> None:
        self._set_status("● 실패", message, f"{message}\n{detail}".strip(), False)

    def _single_cancelled(self, message: str) -> None:
        self._set_status("● 중지됨", message, message, False)

    def _single_finished(self) -> None:
        self._worker = None
        self._set_controls_enabled(True)
        self._refresh_ui_state()

    def _batch_current_changed(self, current: int, total: int, task: object) -> None:
        if not isinstance(task, SubtitleTask):
            return
        self._batch_current = current
        self._batch_total = total
        name = Path(task.primary_path).name
        phase = {
            OP_EXTRACT: "영상에서 자막 읽는 중",
            OP_INSERT: "영상·음성을 그대로 복사해 새 파일 구성 중",
            OP_REMOVE: "자막을 제외하고 새 영상 구성 중",
            OP_SYNC: "자막 시간 정보를 조정하는 중",
        }.get(self._operation, "자막 작업 중")
        self.status_counter.setText(f"{current} / {total}")
        self.status_text.set_full_text(f"{phase} · {name}")
        self.status_detail_label.setText(f"현재 {current}/{total} · {name}\n{phase}")
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(0)
        self.status_progress.setFormat("0%")

    def _batch_item_started(self, index: int, _task: object) -> None:
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("처리 중", "running")

    def _batch_item_progress(self, index: int, percent: int, detail: str) -> None:
        value = max(0, min(100, int(percent)))
        self.status_progress.setRange(0, 100)
        self.status_progress.setValue(value)
        self.status_progress.setFormat(f"{value}%")
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status(f"{value}%", "running")
        current_name = Path(self._batch_tasks[index].primary_path).name if 0 <= index < len(self._batch_tasks) else ""
        self.status_text.set_full_text(f"{detail} · {current_name}" if current_name else detail)
        self.status_detail_label.setText(f"현재 {self._batch_current}/{self._batch_total} · {current_name}\n{detail}".strip())

    def _batch_item_succeeded(self, index: int, result: object) -> None:
        if not isinstance(result, SubtitleResult):
            return
        self._last_output_paths = result.output_paths or self._last_output_paths
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].output_paths = result.output_paths
            self._batch_rows[index].set_status("완료", "done")
        self.status_detail_label.setText(result.message + ("\n" + "\n".join(result.output_paths) if result.output_paths else ""))

    def _batch_item_failed(self, index: int, message: str, detail: str) -> None:
        if 0 <= index < len(self._batch_rows):
            self._batch_rows[index].set_status("실패", "failed")
        self.status_detail_label.setText(f"{message}\n{detail}".strip())

    def _batch_cancelled(self, message: str) -> None:
        for row in self._batch_rows:
            if row.state == "running":
                row.set_status("중지됨", "stopped")
        self._set_status("● 중지됨", message, message, False)

    def _batch_completed(self, success: int, failed: int) -> None:
        summary = f"성공 {success}개 · 실패 {failed}개"
        self._set_status("여러 작업 완료", summary, summary, False)
        self.status_counter.setText(f"{self._batch_total} / {self._batch_total}")
        self._show_quick_actions(batch=True)
        if success > 0 and failed == 0:
            play_completion_sound()

    def _batch_finished(self) -> None:
        self._batch_worker = None
        self._set_controls_enabled(True)
        self._refresh_batch_state()
        self._refresh_ui_state()

    def _stop_operation(self) -> None:
        self.status_text.set_full_text("중지 요청 중…")
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
        if self._batch_worker and self._batch_worker.isRunning():
            self._batch_worker.cancel()

    def _set_status(self, title: str, text: str, detail: str, busy: bool) -> None:
        self.status_title.setText(title)
        self.status_text.set_full_text(text)
        self.status_detail_label.setText(detail)
        self.status_progress.setVisible(busy)
        self.status_stop_button.setVisible(busy)
        if busy:
            self.status_progress.setRange(0, 100)
            self.status_progress.setValue(0)
            self.status_progress.setFormat("0%")
        if not busy and not self._batch_worker:
            self.status_counter.setText("")

    def _show_quick_actions(self, batch: bool = False) -> None:
        enabled = bool(self._last_output_paths)
        self.open_result_button.setEnabled(enabled)
        self.open_folder_button.setEnabled(enabled)
        self.quick_open_result_button.setVisible(enabled and not batch)
        self.quick_open_folder_button.setVisible(enabled)
        self.quick_actions.setVisible(enabled)

    def _toggle_status_detail(self, checked: bool) -> None:
        self.status_detail.setVisible(bool(checked))
        icon_path = SPIN_UP_ICON_PATH if checked else SPIN_DOWN_ICON_PATH

        self.status_details_button.setIcon(QIcon(str(themed_icon_path(icon_path))))

    def _open_result(self) -> None:
        if self._last_output_paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(self._last_output_paths[0]))

    def _open_result_folder(self) -> None:
        if self._last_output_paths:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(self._last_output_paths[0]).parent)))

    def _open_log_folder(self) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(RRV_LOGS_DIR / "subtitles")))

    def _clear_single_input(self) -> None:
        self._primary_path = ""
        self._secondary_path = ""
        self._probe_result = None
        self.primary_edit.clear()
        self.secondary_edit.clear()
        self._clear_track_checks()
        self.track_box.setVisible(False)
        self.input_info_label.setText("자막 파일을 선택합니다." if self._operation == OP_SYNC else "영상을 선택하면 자막 정보를 확인합니다.")
        if hasattr(self, "language_detect_label"):
            self.language_detect_label.setText("자동 감지는 파일명 언어 코드와 자막 내용을 순서대로 확인합니다.")
        self._refresh_ui_state()

    def _set_controls_enabled(self, enabled: bool) -> None:
        for widget in (
            self.primary_choose_button, self.secondary_choose_button,
            self.batch_files_button, self.batch_folder_button, self.batch_clear_button,
            self.extract_format_combo, self.language_combo, self.track_name_edit,
            self.default_check, self.forced_check, self.delete_external_check, self.sync_spin,
            self.overwrite_radio, self.new_file_radio, self.source_folder_radio,
            self.custom_folder_radio, self.output_edit, self.output_choose_button,
        ):
            widget.setEnabled(enabled)
        for _, check in self._track_checks:
            check.setEnabled(enabled)
        for row in self._batch_rows:
            row.remove_button.setEnabled(enabled)
        self._refresh_ui_state()

    def _refresh_ui_state(self) -> None:
        busy = self.has_active_operation
        ready = bool(self._primary_path)
        if self._operation != OP_SYNC:
            ready = ready and self._probe_result is not None
        if self._operation == OP_INSERT:
            ready = ready and bool(self._secondary_path)
        if self._operation in {OP_EXTRACT, OP_REMOVE}:
            ready = ready and any(check.isChecked() for _, check in self._track_checks)
        self.single_start_button.setEnabled(ready and not busy)
        self._refresh_batch_state()
        self.status_stop_button.setVisible(busy)
        self.status_progress.setVisible(busy)
        self._refresh_output_controls()

    def _refresh_output_controls(self) -> None:
        custom = self.custom_folder_radio.isChecked()
        self.output_edit.setEnabled(custom and not self.has_active_operation)
        self.output_choose_button.setEnabled(custom and not self.has_active_operation)

    def _refresh_section_summaries(self) -> None:
        if self._operation == OP_EXTRACT:
            text = self.extract_format_combo.currentText() if hasattr(self, "extract_format_combo") else "원본 형식 유지"
        elif self._operation == OP_INSERT:
            language = self.language_combo.currentData() if hasattr(self, "language_combo") else "auto"
            text = "언어 자동" if language == "auto" else f"언어 {language or 'und'}"
            if hasattr(self, "default_check") and self.default_check.isChecked():
                text += " · 기본"
            if hasattr(self, "delete_external_check") and self.delete_external_check.isChecked():
                text += " · 삽입 후 자막 삭제"
        elif self._operation == OP_SYNC:
            value = self.sync_spin.value() if hasattr(self, "sync_spin") else 0
            text = f"{value / 1000:+.3f}초"
        else:
            text = ""
        if hasattr(self, "settings_section") and text:
            self.settings_section.set_suffix(text)
        if hasattr(self, "sync_direction_label"):
            value = self.sync_spin.value() if hasattr(self, "sync_spin") else 0
            seconds = value / 1000.0
            if value < 0:
                direction = f"{abs(seconds):.3f}초 앞으로 이동합니다."
            elif value > 0:
                direction = f"{seconds:.3f}초 뒤로 이동합니다."
            else:
                direction = "자막 시간을 이동하지 않습니다."
            self.sync_direction_label.setText(f"{seconds:+.3f}초 · {direction}")
        if hasattr(self, "batch_sync_hint"):
            value = self.sync_spin.value() if hasattr(self, "sync_spin") else 0
            self.batch_sync_hint.setText(f"현재 싱크 조정값 {value / 1000:+.3f}초를 여러 자막에 동일하게 적용합니다.")
        if hasattr(self, "output_section"):
            folder = "지정 폴더" if self.custom_folder_radio.isChecked() else "원본 폴더"
            if self._operation in {OP_INSERT, OP_REMOVE, OP_SYNC}:
                mode = "원본 적용" if self.overwrite_radio.isChecked() else "새 파일"
                self.output_section.set_suffix(f"{mode} · {folder}")
            else:
                self.output_section.set_suffix(folder)

    def _controls_changed(self, *args) -> None:
        self._refresh_section_summaries()
        self._refresh_output_controls()
        self._save_timer.start()

    def _section_state_changed(self, _expanded: bool) -> None:
        self._save_timer.start()

    def _load_preferences_into_ui(self) -> None:
        p = self._preferences
        for index in range(self.extract_format_combo.count()):
            if self.extract_format_combo.itemData(index) == p.extract_format:
                self.extract_format_combo.setCurrentIndex(index)
                break
        for index in range(self.language_combo.count()):
            if self.language_combo.itemData(index) == p.language:
                self.language_combo.setCurrentIndex(index)
                break
        self.track_name_edit.setText(p.track_title)
        self.default_check.setChecked(p.make_default)
        self.forced_check.setChecked(p.make_forced)
        self.delete_external_check.setChecked(p.delete_external_after_insert)
        self.sync_spin.setValue(0)
        self.overwrite_radio.setChecked(p.output_mode == OUTPUT_OVERWRITE)
        self.new_file_radio.setChecked(p.output_mode == OUTPUT_NEW_FILE)
        self.source_folder_radio.setChecked(p.output_folder_mode == OUTPUT_SOURCE)
        self.custom_folder_radio.setChecked(p.output_folder_mode == OUTPUT_CUSTOM)
        self.output_edit.setText(p.output_folder)
        self.mode_buttons[self._operation].setChecked(True)

    def _save_preferences(self) -> None:
        language = str(self.language_combo.currentData() or "auto")
        p = SubtitlePreferences(
            operation=self._operation,
            extract_format=str(self.extract_format_combo.currentData() or EXTRACT_ORIGINAL),
            language=language,
            track_title=self.track_name_edit.text().strip(),
            make_default=self.default_check.isChecked(),
            make_forced=self.forced_check.isChecked(),
            delete_external_after_insert=self.delete_external_check.isChecked(),
            sync_offset_ms=0,
            output_mode=OUTPUT_NEW_FILE if self.new_file_radio.isChecked() else OUTPUT_OVERWRITE,
            output_folder_mode=OUTPUT_CUSTOM if self.custom_folder_radio.isChecked() else OUTPUT_SOURCE,
            output_folder=self.output_edit.text().strip(),
            single_expanded=self.single_section.expanded,
            batch_expanded=self.batch_section.expanded,
            settings_expanded=self.settings_section.expanded,
            output_expanded=self.output_section.expanded,
        )
        save_subtitle_preferences(p)
        self._preferences = p

    @staticmethod
    def _format_duration(seconds: float) -> str:
        total = max(0, int(seconds))
        h, rem = divmod(total, 3600)
        m, s = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{s:02d}"

    def _show_warning(self, title: str, message: str, detail: str = "") -> None:
        box = QMessageBox(self)
        box.setObjectName("warmMessageBox")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle(title)
        box.setText(message)
        if detail:
            box.setDetailedText(detail)
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()
