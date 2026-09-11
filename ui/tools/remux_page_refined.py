from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QRadioButton,
)

from app.theme import THEME_DARK, active_theme_mode
from core.local_media_info import MediaFileInfo
from core.remux_models import REMUX_TARGET_LABELS, REMUX_TARGETS, RemuxCompatibility
from services.remux_service import assess_remux_compatibility
from ui.tools.remux_page import RemuxPage as _BaseRemuxPage
from ui.widgets.common import create_card


VIDEO_MEDIA_FILTER = (
    "영상 파일 (*.mp4 *.mkv *.mov *.m4v *.webm *.avi *.ts *.mts *.m2ts);;"
    "모든 파일 (*.*)"
)


class RemuxPage(_BaseRemuxPage):
    """RR-V 1.4 Remux UI 안정화 레이어."""

    def __init__(self) -> None:
        self._updating_targets = False
        super().__init__()

        outer_layout = self.layout()
        if outer_layout is not None:
            outer_layout.setContentsMargins(24, 14, 24, 14)
            outer_layout.setSpacing(10)

        drop_layout = self.drop_area.layout()
        if drop_layout is not None:
            drop_layout.setContentsMargins(14, 8, 14, 8)
            drop_layout.setSpacing(6)

        self.input_summary.setWordWrap(False)
        self.input_summary.setMinimumHeight(24)

    def _create_target_card(self) -> QFrame:
        card, layout = create_card()
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(9)

        heading = QLabel("출력 컨테이너")
        heading.setObjectName("settingsGroupTitle")
        layout.addWidget(heading)

        self.target_group = QButtonGroup(self)
        self.target_group.setExclusive(True)
        self.target_buttons: dict[str, QRadioButton] = {}
        target_row = QHBoxLayout()
        target_row.setSpacing(22)
        for target in REMUX_TARGETS:
            button = QRadioButton(REMUX_TARGET_LABELS[target])
            button.setObjectName("settingsRadioButton")
            button.setEnabled(False)
            button.toggled.connect(
                lambda checked, value=target: self._target_changed(value, checked)
            )
            self.target_group.addButton(button)
            self.target_buttons[target] = button
            target_row.addWidget(button)
        target_row.addStretch()
        layout.addLayout(target_row)

        description = QLabel("보존 가능한 컨테이너만 선택할 수 있습니다.")
        description.setObjectName("mutedText")
        description.setWordWrap(True)
        layout.addWidget(description)

        self.compatibility_label = QLabel("파일을 선택하면 호환성을 확인합니다.")
        self.compatibility_label.setObjectName("remuxCompatibilityStatus")
        self.compatibility_label.setWordWrap(True)
        self.compatibility_label.setMinimumHeight(38)
        layout.addWidget(self.compatibility_label)

        self.output_label = QLabel("출력 파일: 확인 전")
        self.output_label.setObjectName("mutedText")
        self.output_label.setWordWrap(False)
        self.output_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.output_label)
        return card

    def _choose_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Remux할 영상 파일 선택",
            str(Path.home()),
            VIDEO_MEDIA_FILTER,
        )
        if path:
            self._set_input_file(path)

    def _probe_done(self, media_info: object) -> None:
        super()._probe_done(media_info)
        if isinstance(media_info, MediaFileInfo) and not media_info.has_video:
            self.status_label.setText("지원하지 않는 입력 · 영상 파일을 선택해 주세요.")

    def _choose_recommended_target(self, media_info: MediaFileInfo) -> None:
        assessments = {
            target: assess_remux_compatibility(media_info, target)
            for target in REMUX_TARGETS
        }
        self._select_target(self._recommended_target(media_info, assessments))

    def _target_changed(self, _target: str, checked: bool) -> None:
        if checked and not self._updating_targets:
            self._refresh_target_state()

    def _current_target(self) -> str | None:
        for target, button in self.target_buttons.items():
            if button.isChecked():
                return target
        return None

    def _select_target(self, target: str | None) -> None:
        self._updating_targets = True
        try:
            if target is None:
                self.target_group.setExclusive(False)
                for button in self.target_buttons.values():
                    button.setChecked(False)
                self.target_group.setExclusive(True)
                return
            for value, button in self.target_buttons.items():
                button.setChecked(value == target)
        finally:
            self._updating_targets = False

    def _clear_target_selection(self) -> None:
        self._select_target(None)

    def _refresh_target_state(self) -> None:
        media_info = self._media_info
        busy = self.has_active_operation

        if media_info is None:
            self._clear_target_selection()
            for button in self.target_buttons.values():
                button.setEnabled(False)
                button.setToolTip("파일을 먼저 선택해 주세요.")
            self._set_compatibility_status(
                "파일을 선택하면 호환성을 확인합니다.", "neutral"
            )
            self.output_label.setText("출력 파일: 확인 전")
            self.output_label.setToolTip("")
            self.start_button.setEnabled(False)
            return

        assessments = {
            target: assess_remux_compatibility(media_info, target)
            for target in REMUX_TARGETS
        }
        for target, button in self.target_buttons.items():
            compatibility = assessments[target]
            button.setEnabled(compatibility.supported and not busy)
            button.setToolTip(
                "사용 가능" if compatibility.supported else compatibility.summary
            )

        if not media_info.has_video:
            self._clear_target_selection()
            for button in self.target_buttons.values():
                button.setEnabled(False)
                button.setToolTip("오디오 전용 파일은 지원하지 않습니다.")
            self._set_compatibility_status(
                "⚠ 지원하지 않는 입력 · 영상 스트림이 없는 오디오 전용 파일입니다.\n"
                "RR-V Remux는 영상이 포함된 파일만 지원합니다.",
                "error",
            )
            self.output_label.setText("출력 파일: 생성할 수 없음")
            self.output_label.setToolTip("")
            self.start_button.setEnabled(False)
            return

        current = self._current_target()
        if current is None or not assessments[current].supported:
            current = self._recommended_target(media_info, assessments)
            self._select_target(current)

        if current is None:
            self._set_compatibility_status(
                "⚠ 사용 가능한 출력 컨테이너가 없습니다.\n"
                + self._best_incompatibility_reason(media_info, assessments),
                "error",
            )
            self.output_label.setText("출력 파일: 생성할 수 없음")
            self.output_label.setToolTip("")
            self.start_button.setEnabled(False)
            return

        label = REMUX_TARGET_LABELS[current]
        self._set_compatibility_status(
            f"✓ 사용 가능 · {label} · 모든 트랙을 그대로 보존합니다.",
            "success",
        )
        output_path = self._service.suggested_output_path(media_info, current)
        self.output_label.setText(f"출력 파일: {Path(output_path).name}")
        self.output_label.setToolTip(str(output_path))
        self.start_button.setEnabled(not busy)

    @staticmethod
    def _recommended_target(
        media_info: MediaFileInfo,
        assessments: dict[str, RemuxCompatibility],
    ) -> str | None:
        source = Path(media_info.file_name).suffix.lstrip(".").lower()
        if source == "mkv":
            order = ("mp4", "mov", "mkv")
        elif source in {"mp4", "mov", "m4v"}:
            order = ("mkv", "mp4", "mov")
        else:
            order = ("mkv", "mp4", "mov")
        return next(
            (target for target in order if assessments[target].supported),
            None,
        )

    @staticmethod
    def _best_incompatibility_reason(
        media_info: MediaFileInfo,
        assessments: dict[str, RemuxCompatibility],
    ) -> str:
        source = Path(media_info.file_name).suffix.lstrip(".").lower()
        alternatives = [
            target
            for target in REMUX_TARGETS
            if target != source and assessments[target].issues
        ]
        if not alternatives:
            alternatives = [
                target for target in REMUX_TARGETS if assessments[target].issues
            ]
        if not alternatives:
            return "현재 트랙 구성을 그대로 보존할 수 없습니다."

        target = alternatives[0]
        compatibility = assessments[target]
        subtitle_issues = [
            issue
            for issue in compatibility.issues
            if issue.startswith("자막 스트림")
        ]
        if len(subtitle_issues) > 1:
            label = REMUX_TARGET_LABELS[target]
            return (
                f"{label}에서는 현재 자막 {len(subtitle_issues)}개를 그대로 "
                "보존할 수 없습니다. 원본 컨테이너를 유지해 주세요."
            )
        return compatibility.summary

    def _set_compatibility_status(self, text: str, state: str) -> None:
        self.compatibility_label.setText(text)
        line_count = max(1, text.count("\n") + 1)
        self.compatibility_label.setMinimumHeight(54 if line_count > 1 else 38)

        if state == "success":
            if active_theme_mode() == THEME_DARK:
                style = (
                    "QLabel { background-color: #2E4032; color: #AFD0AD; "
                    "border: 1px solid #48604B; border-radius: 8px; "
                    "padding: 6px 10px; font-weight: 700; }"
                )
            else:
                style = (
                    "QLabel { background-color: #DDEADB; color: #557955; "
                    "border: 1px solid #C5D9C1; border-radius: 8px; "
                    "padding: 6px 10px; font-weight: 700; }"
                )
        elif state == "error":
            if active_theme_mode() == THEME_DARK:
                style = (
                    "QLabel { background-color: #452F2F; color: #E0A19A; "
                    "border: 1px solid #664343; border-radius: 8px; "
                    "padding: 6px 10px; font-weight: 700; }"
                )
            else:
                style = (
                    "QLabel { background-color: #EBDDD9; color: #985E55; "
                    "border: 1px solid #D9C2BC; border-radius: 8px; "
                    "padding: 6px 10px; font-weight: 700; }"
                )
        else:
            style = ""
        self.compatibility_label.setStyleSheet(style)

    def _remux_done(self, output_path: str, size_bytes: int) -> None:
        super()._remux_done(output_path, size_bytes)
        self._reset_input_after_success()

    def _reset_input_after_success(self) -> None:
        self._input_path = ""
        self._media_info = None
        self.path_input.clear()
        self.input_summary.setText("아직 선택한 파일이 없습니다.")
        self._clear_target_selection()
        for button in self.target_buttons.values():
            button.setEnabled(False)
            button.setToolTip("파일을 먼저 선택해 주세요.")
        self._set_compatibility_status(
            "다음 파일을 선택하면 호환성을 다시 확인합니다.", "neutral"
        )
        self.output_label.setText("출력 파일: 새 파일을 선택해 주세요.")
        self.output_label.setToolTip("")
        self.start_button.setEnabled(False)

    @staticmethod
    def _summary_text(media_info: MediaFileInfo) -> str:
        video = media_info.primary_video
        if video is None:
            suffix = Path(media_info.file_name).suffix.lstrip(".").upper() or "MEDIA"
            return f"{suffix} · 오디오 전용 파일"

        container = Path(media_info.file_name).suffix.lstrip(".").upper() or "MEDIA"
        parts = [
            container,
            RemuxPage._codec_label(video.codec_name),
            video.resolution_text,
        ]
        if media_info.audio_tracks:
            audio = media_info.audio_tracks[0]
            channel_text = audio.channel_layout or (
                f"{audio.channels}ch" if audio.channels else ""
            )
            audio_text = RemuxPage._codec_label(audio.codec_name)
            if channel_text:
                audio_text += f" {channel_text}"
            parts.append(audio_text)

        parts.append(f"자막 {len(media_info.subtitle_tracks)}개")
        parts.append(f"챕터 {len(media_info.chapters)}개")
        return " · ".join(parts)

    @staticmethod
    def _codec_label(codec_name: str) -> str:
        codec = codec_name.strip().lower()
        labels = {
            "h264": "H.264",
            "hevc": "H.265 / HEVC",
            "av1": "AV1",
            "vp9": "VP9",
            "vp8": "VP8",
            "mpeg4": "MPEG-4",
            "aac": "AAC",
            "ac3": "AC-3",
            "eac3": "E-AC-3",
            "opus": "Opus",
            "mp3": "MP3",
        }
        return labels.get(codec, codec.upper() or "확인 불가")
