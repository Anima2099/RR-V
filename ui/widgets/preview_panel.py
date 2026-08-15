from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.download_preferences import (
    AUDIO_FORMAT_CHOICES,
    AUDIO_QUALITY_CHOICES,
    CODEC_CHOICES,
    CONTAINER_CHOICES,
    RESOLUTION_CHOICES,
    DownloadPreferences,
)
from app.preset_store import (
    DownloadPreset,
    load_preset_library,
    save_preset_library,
)
from core.media_info import MediaInfo
from ui.dialogs.warm_dialogs import prompt_warm_text, show_warm_message
from ui.dialogs.subtitle_selection_dialog import (
    SubtitleSelection,
    default_subtitle_selection,
    language_base,
    select_subtitles,
)
from ui.widgets.common import NoWheelComboBox


class PreviewPanel(QFrame):
    """영상 정보 확인과 이번 영상의 다운로드 설정을 보여주는 편집 패널."""

    cancel_requested = Signal()
    task_requested = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("previewPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self.media_info: MediaInfo | None = None
        self.thumbnail_data = b""
        self._technical_error = ""
        self._subtitle_selection = SubtitleSelection()
        self._subtitle_modified = False
        self._applying_preset = False
        self._preset_modified = False
        self._preset_library = load_preset_library()

        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.empty_frame = self._create_empty_frame()
        self.loading_frame = self._create_loading_frame()
        self.error_frame = self._create_error_frame()
        self.ready_frame = self._create_ready_frame()
        self._state_frames = (
            self.empty_frame,
            self.loading_frame,
            self.error_frame,
            self.ready_frame,
        )

        for frame in self._state_frames:
            frame.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Maximum,
            )
            root_layout.addWidget(
                frame,
                0,
                Qt.AlignmentFlag.AlignTop,
            )

        self.set_empty()

    # ------------------------------------------------------------------
    # 화면 구성
    # ------------------------------------------------------------------

    def _create_empty_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewStateCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        label = QLabel("확인할 영상 주소를 입력해 주세요.")
        label.setObjectName("mutedText")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        return frame

    def _create_loading_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewStateCard")
        layout = QHBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)

        self.loading_label = QLabel("영상 정보를 확인 중…")
        self.loading_label.setObjectName("previewLoadingText")
        self.loading_label.setWordWrap(True)

        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("smallSecondaryButton")
        cancel_button.clicked.connect(self.cancel_requested)

        layout.addWidget(self.loading_label, 1)
        layout.addWidget(cancel_button)
        return frame

    def _create_error_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewStateCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(10)

        self.error_title = QLabel("영상 정보를 확인하지 못했습니다.")
        self.error_title.setObjectName("previewErrorTitle")
        self.error_title.setWordWrap(True)

        hint = QLabel("주소, 로그인 상태, 쿠키 또는 네트워크 연결을 확인해 주세요.")
        hint.setObjectName("emptyDescription")
        hint.setWordWrap(True)

        button_row = QHBoxLayout()
        button_row.addStretch()
        detail_button = QPushButton("상세 내용")
        detail_button.setObjectName("smallSecondaryButton")
        detail_button.clicked.connect(self._show_error_detail)
        button_row.addWidget(detail_button)

        layout.addWidget(self.error_title)
        layout.addWidget(hint)
        layout.addLayout(button_row)
        return frame

    def _create_ready_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewStateCard")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        media_row = QHBoxLayout()
        media_row.setSpacing(16)
        media_row.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.thumbnail_label = QLabel("THUMBNAIL")
        self.thumbnail_label.setObjectName("previewThumbnail")
        self.thumbnail_label.setFixedSize(240, 135)
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        info_layout = QVBoxLayout()
        info_layout.setSpacing(7)
        info_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        self.title_label = QLabel()
        self.title_label.setObjectName("previewTitle")
        self.title_label.setWordWrap(True)
        self.title_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )

        self.source_label = QLabel()
        self.source_label.setObjectName("previewSource")
        self.source_label.setWordWrap(True)

        self.availability_label = QLabel()
        self.availability_label.setObjectName("previewAvailability")
        self.availability_label.setWordWrap(True)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.source_label)
        info_layout.addWidget(self.availability_label)

        media_row.addWidget(
            self.thumbnail_label,
            0,
            Qt.AlignmentFlag.AlignTop,
        )
        media_row.addLayout(info_layout, 1)
        layout.addLayout(media_row)

        self.settings_summary_frame = QFrame()
        self.settings_summary_frame.setObjectName("previewSummaryFrame")
        settings_header = QHBoxLayout(self.settings_summary_frame)
        settings_header.setContentsMargins(14, 10, 12, 10)
        settings_header.setSpacing(10)

        settings_title = QLabel("다운로드 설정")
        settings_title.setObjectName("previewSettingsTitle")

        self.settings_summary = QLabel()
        self.settings_summary.setObjectName("previewSettingsSummary")
        self.settings_summary.setWordWrap(True)

        self.settings_toggle_button = QPushButton("변경")
        self.settings_toggle_button.setObjectName("smallSecondaryButton")
        self.settings_toggle_button.clicked.connect(self._toggle_settings)

        settings_header.addWidget(settings_title)
        settings_header.addWidget(self.settings_summary, 1)
        settings_header.addWidget(self.settings_toggle_button)
        layout.addWidget(self.settings_summary_frame)

        self.settings_frame = self._create_settings_frame()
        self.settings_frame.hide()
        layout.addWidget(self.settings_frame)

        button_row = QHBoxLayout()
        button_row.addStretch()

        add_button = QPushButton("목록에 추가")
        add_button.setObjectName("secondaryButton")
        add_button.clicked.connect(lambda: self.task_requested.emit(False))

        start_button = QPushButton("지금 다운로드")
        start_button.setObjectName("primaryButton")
        start_button.clicked.connect(lambda: self.task_requested.emit(True))

        button_row.addWidget(add_button)
        button_row.addWidget(start_button)
        layout.addLayout(button_row)

        self._connect_option_signals()
        return frame

    def _create_settings_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("previewSettingsFrame")
        layout = QVBoxLayout(frame)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(11)

        preset_grid = QGridLayout()
        preset_grid.setHorizontalSpacing(12)
        preset_grid.setVerticalSpacing(10)

        preset_label = QLabel("선호 프리셋")
        preset_label.setObjectName("previewOptionName")
        self.preset_combo = self._create_combo()
        self.preset_status_label = QLabel()
        self.preset_status_label.setObjectName("previewPresetStatus")
        self.save_as_preset_button = QPushButton("프리셋으로 저장")
        self.save_as_preset_button.setObjectName("secondaryButton")
        self.save_as_preset_button.setToolTip("현재 영상에서 바꾼 옵션을 새 프리셋으로 저장")
        self.save_as_preset_button.clicked.connect(self._save_current_as_preset)
        self.save_as_preset_button.hide()
        self._refresh_preset_combo(self._preset_library.default_preset_id)

        preset_grid.addWidget(preset_label, 0, 0)
        preset_grid.addWidget(self.preset_combo, 0, 1)
        preset_grid.addWidget(self.preset_status_label, 0, 2)
        preset_grid.addWidget(self.save_as_preset_button, 0, 3)
        preset_grid.setColumnStretch(1, 1)
        layout.addLayout(preset_grid)

        self.video_options_frame = QFrame()
        self.video_options_frame.setObjectName("transparentFrame")
        video_grid = QGridLayout(self.video_options_frame)
        video_grid.setContentsMargins(0, 0, 0, 0)
        video_grid.setHorizontalSpacing(12)
        video_grid.setVerticalSpacing(10)

        self.resolution_combo = self._create_combo()
        self.container_combo = self._create_combo(list(CONTAINER_CHOICES))
        self.codec_combo = self._create_combo(list(CODEC_CHOICES))
        self.subtitle_button = QPushButton("자막 없음")
        self.subtitle_button.setObjectName("subtitleSelectButton")
        self.subtitle_button.clicked.connect(self._choose_subtitles)

        for row, (name, widget) in enumerate(
            (
                ("화질", self.resolution_combo),
                ("파일 형식", self.container_combo),
                ("코덱 우선", self.codec_combo),
                ("자막", self.subtitle_button),
            )
        ):
            label = QLabel(name)
            label.setObjectName("previewOptionName")
            video_grid.addWidget(label, row, 0)
            video_grid.addWidget(widget, row, 1)
        video_grid.setColumnStretch(1, 1)
        layout.addWidget(self.video_options_frame)

        self.audio_options_frame = QFrame()
        self.audio_options_frame.setObjectName("transparentFrame")
        audio_grid = QGridLayout(self.audio_options_frame)
        audio_grid.setContentsMargins(0, 0, 0, 0)
        audio_grid.setHorizontalSpacing(12)
        audio_grid.setVerticalSpacing(10)

        self.audio_format_combo = self._create_combo(list(AUDIO_FORMAT_CHOICES))
        self.audio_quality_combo = self._create_combo(list(AUDIO_QUALITY_CHOICES))
        for row, (name, widget) in enumerate(
            (
                ("오디오 형식", self.audio_format_combo),
                ("오디오 음질", self.audio_quality_combo),
            )
        ):
            label = QLabel(name)
            label.setObjectName("previewOptionName")
            audio_grid.addWidget(label, row, 0)
            audio_grid.addWidget(widget, row, 1)
        audio_grid.setColumnStretch(1, 1)
        self.audio_options_frame.hide()
        layout.addWidget(self.audio_options_frame)

        check_row = QHBoxLayout()
        check_row.setSpacing(18)

        self.embed_subtitles_checkbox = QCheckBox("자막을 영상에 내장")
        self.embed_subtitles_checkbox.setObjectName("previewCheckBox")
        self.metadata_checkbox = QCheckBox("메타데이터 보존")
        self.metadata_checkbox.setObjectName("previewCheckBox")
        self.audio_only_checkbox = QCheckBox("오디오만 다운로드")
        self.audio_only_checkbox.setObjectName("previewCheckBox")
        self.embed_thumbnail_checkbox = QCheckBox("영상 안에 썸네일 내장")
        self.embed_thumbnail_checkbox.setObjectName("previewCheckBox")
        self.save_thumbnail_checkbox = QCheckBox("썸네일 JPG 별도 저장")
        self.save_thumbnail_checkbox.setObjectName("previewCheckBox")

        check_row.addWidget(self.embed_subtitles_checkbox)
        check_row.addWidget(self.metadata_checkbox)
        check_row.addWidget(self.audio_only_checkbox)
        check_row.addStretch()
        layout.addLayout(check_row)

        thumbnail_row = QHBoxLayout()
        thumbnail_row.setSpacing(18)
        thumbnail_row.addWidget(self.embed_thumbnail_checkbox)
        thumbnail_row.addWidget(self.save_thumbnail_checkbox)
        thumbnail_row.addStretch()
        layout.addLayout(thumbnail_row)
        return frame

    @staticmethod
    def _create_combo(items: list[str] | None = None) -> QComboBox:
        combo = NoWheelComboBox()
        combo.setObjectName("previewCombo")
        if items:
            combo.addItems(items)
        return combo

    def _connect_option_signals(self) -> None:
        self.preset_combo.currentIndexChanged.connect(self._apply_preset)
        for combo in (
            self.resolution_combo,
            self.container_combo,
            self.codec_combo,
            self.audio_format_combo,
            self.audio_quality_combo,
        ):
            combo.currentTextChanged.connect(self._option_changed)

        self.embed_subtitles_checkbox.toggled.connect(self._option_changed)
        self.embed_thumbnail_checkbox.toggled.connect(self._option_changed)
        self.save_thumbnail_checkbox.toggled.connect(self._option_changed)
        self.metadata_checkbox.toggled.connect(self._option_changed)
        self.audio_only_checkbox.toggled.connect(self._audio_only_changed)

    # ------------------------------------------------------------------
    # 상태 전환
    # ------------------------------------------------------------------

    def _show_state(self, target: QFrame) -> None:
        for frame in self._state_frames:
            frame.setVisible(frame is target)
        self.updateGeometry()

    def set_empty(self) -> None:
        self.media_info = None
        self.thumbnail_data = b""
        self._technical_error = ""
        self._subtitle_selection = SubtitleSelection()
        self._subtitle_modified = False
        self._preset_modified = False
        self._update_preset_status()
        self.settings_frame.hide()
        self.settings_toggle_button.setText("변경")
        self._show_state(self.empty_frame)

    def set_loading(self, message: str = "영상 정보를 확인 중…") -> None:
        self.loading_label.setText(message)
        self._show_state(self.loading_frame)

    def update_loading_message(self, message: str) -> None:
        self.loading_label.setText(message)

    def set_error(self, message: str, technical_detail: str) -> None:
        self.media_info = None
        self.thumbnail_data = b""
        self.error_title.setText(message)
        self._technical_error = technical_detail
        self._show_state(self.error_frame)

    def set_media(self, media_info: MediaInfo, thumbnail_data: bytes) -> None:
        self.media_info = media_info
        self.thumbnail_data = thumbnail_data
        self.title_label.setText(media_info.title)
        self.title_label.setToolTip(media_info.title)
        self.source_label.setText(media_info.source_text)

        resolution_text = (
            f"감지된 화질 {len(media_info.resolutions)}개"
            if media_info.resolutions
            else "화질 목록을 감지하지 못함"
        )
        manual_count = len(media_info.manual_subtitle_languages)
        automatic_count = len(media_info.automatic_subtitle_languages)
        subtitle_text = (
            f"제공 자막 {manual_count}개 · 자동 자막 {automatic_count}개"
            if manual_count or automatic_count
            else "자막 정보 없음"
        )
        self.availability_label.setText(f"{resolution_text} · {subtitle_text}")

        self._preset_library = load_preset_library()
        preferences = self._preset_library.default_preset.to_preferences()
        self._select_default_subtitles(preferences)

        self._set_thumbnail(thumbnail_data)
        self._populate_options(media_info)
        self._refresh_preset_combo(preferences.preset_id)
        self._apply_preferences(preferences)
        self.settings_frame.hide()
        self.settings_toggle_button.setText("변경")
        self._show_state(self.ready_frame)

    # ------------------------------------------------------------------
    # 선택값
    # ------------------------------------------------------------------

    def selected_options(self) -> dict[str, object]:
        return {
            "preset": self._current_preset().name,
            "resolution": self.resolution_combo.currentText() or "최고 화질",
            "container": self.container_combo.currentText() or "MP4",
            "codec": self.codec_combo.currentText() or "H.264",
            "subtitle": self._subtitle_selection.summary,
            "subtitle_tracks": self._subtitle_selection.encoded_tracks,
            "embed_subtitles": self.embed_subtitles_checkbox.isChecked(),
            "embed_thumbnail": self.embed_thumbnail_checkbox.isChecked(),
            "save_thumbnail": self.save_thumbnail_checkbox.isChecked(),
            "audio_only": self.audio_only_checkbox.isChecked(),
            "audio_format": self.audio_format_combo.currentText() or "M4A",
            "audio_quality": self.audio_quality_combo.currentText() or "최고",
            "preserve_metadata": self.metadata_checkbox.isChecked(),
        }

    def _populate_options(self, media_info: MediaInfo) -> None:
        aliases = {"4320p": "8K (4320p)", "2160p": "4K (2160p)"}
        choices = list(RESOLUTION_CHOICES)
        for resolution in media_info.resolutions:
            display = aliases.get(resolution, resolution)
            if display not in choices:
                choices.append(display)

        self.resolution_combo.blockSignals(True)
        self.resolution_combo.clear()
        self.resolution_combo.addItems(choices)
        self.resolution_combo.blockSignals(False)

        has_subtitles = bool(media_info.subtitle_languages)
        self.subtitle_button.setEnabled(has_subtitles)
        self.subtitle_button.setText(
            self._subtitle_selection.summary if has_subtitles else "자막 없음"
        )
        self.embed_subtitles_checkbox.setEnabled(
            has_subtitles and not self._subtitle_selection.is_empty
        )

    def _apply_preferences(self, preferences: DownloadPreferences) -> None:
        self._applying_preset = True
        self._preset_modified = False
        try:
            preset_index = self.preset_combo.findData(preferences.preset_id)
            if preset_index >= 0:
                self.preset_combo.setCurrentIndex(preset_index)
            self._set_combo_text(
                self.resolution_combo,
                preferences.resolution,
                fallback="최고 화질",
            )
            self._set_combo_text(
                self.container_combo,
                preferences.container,
                fallback="MP4",
            )
            self._set_combo_text(
                self.codec_combo,
                preferences.codec,
                fallback="H.264",
            )
            self._set_combo_text(
                self.audio_format_combo,
                preferences.audio_format,
                fallback="M4A",
            )
            self._set_combo_text(
                self.audio_quality_combo,
                preferences.audio_quality,
                fallback="최고",
            )
            self.embed_subtitles_checkbox.setChecked(
                preferences.embed_subtitles
                and not self._subtitle_selection.is_empty
            )
            self.embed_thumbnail_checkbox.setChecked(
                preferences.embed_thumbnail
            )
            self.save_thumbnail_checkbox.setChecked(
                preferences.save_thumbnail
            )
            self.metadata_checkbox.setChecked(preferences.preserve_metadata)
            self.audio_only_checkbox.setChecked(preferences.audio_only)
            # setChecked()가 같은 값이면 toggled가 발생하지 않으므로 표시 상태는
            # 한 번 명시적으로 동기화한다. _applying_preset=True인 동안 호출해
            # 프로그램 적용을 사용자 수정으로 오인하지 않게 한다.
            self._audio_only_changed(preferences.audio_only)
        finally:
            self._applying_preset = False

        self._subtitle_modified = False
        self._update_preset_status()
        self._update_settings_summary()

    @staticmethod
    def _set_combo_text(
        combo: QComboBox,
        value: str,
        fallback: str | None = None,
    ) -> None:
        target = value if combo.findText(value) >= 0 else fallback
        if target is not None and combo.findText(target) >= 0:
            combo.setCurrentText(target)

    def _refresh_preset_combo(self, selected_id: str = "") -> None:
        if not selected_id:
            selected_id = self._preset_library.default_preset_id

        self._applying_preset = True
        try:
            self.preset_combo.clear()
            selected_index = 0
            for index, preset in enumerate(self._preset_library.presets):
                prefix = "★ " if preset.preset_id == self._preset_library.default_preset_id else ""
                self.preset_combo.addItem(f"{prefix}{preset.name}", preset.preset_id)
                if preset.preset_id == selected_id:
                    selected_index = index
            self.preset_combo.setCurrentIndex(selected_index)
        finally:
            self._applying_preset = False

    def _current_preset(self) -> DownloadPreset:
        preset_id = str(self.preset_combo.currentData() or "")
        return self._preset_library.get(preset_id) or self._preset_library.default_preset

    def _select_default_subtitles(self, preferences: DownloadPreferences) -> None:
        if (
            self.media_info is None
            or not preferences.receive_subtitles
            or preferences.audio_only
        ):
            self._subtitle_selection = SubtitleSelection()
        else:
            self._subtitle_selection = default_subtitle_selection(
                self.media_info.manual_subtitle_languages,
                self.media_info.automatic_subtitle_languages,
                preferences.preferred_subtitles,
                preferences.allow_automatic_subtitles,
            )
        self._subtitle_modified = False
        if hasattr(self, "subtitle_button"):
            has_subtitles = bool(self.media_info and self.media_info.subtitle_languages)
            self.subtitle_button.setText(
                self._subtitle_selection.summary if has_subtitles else "자막 없음"
            )
            self.embed_subtitles_checkbox.setEnabled(
                has_subtitles and not self._subtitle_selection.is_empty
            )

    def _save_current_as_preset(self) -> None:
        base_preset = self._current_preset()
        suggested = f"{base_preset.name} 복사본"
        number = 2
        while self._preset_library.has_name(suggested):
            suggested = f"{base_preset.name} 복사본 {number}"
            number += 1

        name, ok = prompt_warm_text(
            self,
            "현재 설정을 프리셋으로 저장",
            "새 프리셋 이름",
            suggested,
        )
        if not ok:
            return
        name = name.strip()
        if not name:
            show_warm_message(self, "프리셋 저장", "프리셋 이름을 입력해 주세요.")
            return
        if len(name) > 60:
            show_warm_message(self, "프리셋 저장", "프리셋 이름은 60자 이하로 입력해 주세요.")
            return
        if self._preset_library.has_name(name):
            show_warm_message(self, "프리셋 저장", "같은 이름의 프리셋이 이미 있습니다.")
            return

        base_preferences = base_preset.to_preferences()
        preferred = base_preferences.preferred_subtitles
        receive_subtitles = base_preferences.receive_subtitles
        allow_automatic = base_preferences.allow_automatic_subtitles
        if self._subtitle_modified:
            selected_codes = self._subtitle_selection.manual + self._subtitle_selection.automatic
            selected_bases: list[str] = []
            for code in selected_codes:
                base = language_base(code)
                if base and base not in selected_bases:
                    selected_bases.append(base)
            preferred = tuple(selected_bases)
            receive_subtitles = not self._subtitle_selection.is_empty
            allow_automatic = (
                base_preferences.allow_automatic_subtitles
                or bool(self._subtitle_selection.automatic)
            )

        values = self.selected_options()
        preferences = DownloadPreferences(
            preset=name,
            resolution=str(values["resolution"]),
            container=str(values["container"]),
            codec=str(values["codec"]),
            receive_subtitles=receive_subtitles,
            preferred_subtitles=preferred,
            allow_automatic_subtitles=allow_automatic,
            embed_subtitles=bool(values["embed_subtitles"]),
            embed_thumbnail=bool(values["embed_thumbnail"]),
            save_thumbnail=bool(values["save_thumbnail"]),
            preserve_metadata=bool(values["preserve_metadata"]),
            audio_only=bool(values["audio_only"]),
            audio_format=str(values["audio_format"]),
            audio_quality=str(values["audio_quality"]),
        )
        preset = DownloadPreset.from_preferences(name, preferences)
        try:
            self._preset_library.add_preset(preset)
            save_preset_library(self._preset_library)
        except (OSError, ValueError) as error:
            show_warm_message(self, "프리셋 저장 실패", str(error))
            return

        self._refresh_preset_combo(preset.preset_id)
        self._select_default_subtitles(preset.to_preferences())
        self._apply_preferences(preset.to_preferences())
        self.preset_status_label.setText("저장됨")

    def _set_thumbnail(self, data: bytes) -> None:
        pixmap = QPixmap()
        if data and pixmap.loadFromData(data):
            scaled = pixmap.scaled(
                self.thumbnail_label.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail_label.setPixmap(scaled)
            self.thumbnail_label.setText("")
        else:
            self.thumbnail_label.setPixmap(QPixmap())
            self.thumbnail_label.setText("썸네일 없음")

    # ------------------------------------------------------------------
    # 사용자 조작
    # ------------------------------------------------------------------

    def _toggle_settings(self) -> None:
        visible = not self.settings_frame.isVisible()
        if visible:
            previous_id = str(self.preset_combo.currentData() or "")
            previous_exists = self._preset_library.get(previous_id) is not None
            self._preset_library = load_preset_library()
            selected_id = (
                previous_id
                if self._preset_library.get(previous_id) is not None
                else self._preset_library.default_preset_id
            )
            self._refresh_preset_combo(selected_id)

            # 설정 화면에서 해당 프리셋이 수정/삭제되었을 수 있다. 이번 영상에
            # 직접 손댄 값이 없다면 최신 저장본을 적용하고, 수정 중이라면 현재
            # 영상의 임시 변경값을 보존한다. 삭제된 프리셋은 기본 프리셋으로
            # 안전하게 돌아간다.
            if not self._preset_modified or not previous_exists:
                preset = self._current_preset()
                preferences = preset.to_preferences()
                self._select_default_subtitles(preferences)
                self._apply_preferences(preferences)

        self.settings_frame.setVisible(visible)
        self.settings_toggle_button.setText("접기" if visible else "변경")
        self.updateGeometry()

    def _choose_subtitles(self) -> None:
        if self.media_info is None:
            return

        selection = select_subtitles(
            self.media_info.manual_subtitle_languages,
            self.media_info.automatic_subtitle_languages,
            self._subtitle_selection,
            self,
        )
        if selection is None:
            return

        self._subtitle_selection = selection
        self._subtitle_modified = True
        self.subtitle_button.setText(selection.summary)
        self.embed_subtitles_checkbox.setEnabled(not selection.is_empty)
        if selection.is_empty:
            self.embed_subtitles_checkbox.setChecked(False)
        self._option_changed()

    def _apply_preset(self, _index: int) -> None:
        if self._applying_preset or self.preset_combo.currentIndex() < 0:
            return

        preset = self._current_preset()
        preferences = preset.to_preferences()
        self._select_default_subtitles(preferences)
        self._apply_preferences(preferences)

    def _option_changed(self, *_args: object) -> None:
        if not self._applying_preset:
            self._preset_modified = True
        self._update_preset_status()
        self._update_settings_summary()

    def _audio_only_changed(self, checked: bool) -> None:
        self.video_options_frame.setVisible(not checked)
        self.audio_options_frame.setVisible(checked)
        self.embed_subtitles_checkbox.setVisible(not checked)
        if checked:
            self.embed_subtitles_checkbox.setChecked(False)
        if not self._applying_preset:
            self._preset_modified = True
        self._update_preset_status()
        self._update_settings_summary()
        self.updateGeometry()

    def _update_preset_status(self) -> None:
        self.preset_status_label.setText(
            "수정됨" if self._preset_modified else ""
        )
        self.save_as_preset_button.setVisible(self._preset_modified)

    def _update_settings_summary(self) -> None:
        values = self.selected_options()
        preset = str(values["preset"])
        if self._preset_modified:
            preset += " · 수정됨"

        if bool(values["audio_only"]):
            summary_items = [
                preset,
                "오디오만",
                str(values["audio_format"]),
                str(values["audio_quality"]),
            ]
        else:
            summary_items = [
                preset,
                str(values["resolution"]),
                str(values["container"]),
                str(values["codec"]),
                str(values["subtitle"]),
            ]
            if bool(values["embed_subtitles"]):
                summary_items.append("자막 내장")

        if bool(values["embed_thumbnail"]):
            summary_items.append("썸네일 내장")
        if bool(values["save_thumbnail"]):
            summary_items.append("JPG 썸네일")
        if bool(values["preserve_metadata"]):
            summary_items.append("메타데이터")
        self.settings_summary.setText(" · ".join(summary_items))

    def _show_error_detail(self) -> None:
        detail = self._technical_error.strip() or "추가 오류 정보가 없습니다."
        message_box = QMessageBox(self)
        message_box.setObjectName("warmMessageBox")
        message_box.setWindowTitle("영상 정보 확인 상세 내용")
        message_box.setIcon(QMessageBox.Icon.Warning)
        message_box.setText(self.error_title.text())
        message_box.setDetailedText(detail)
        message_box.exec()
