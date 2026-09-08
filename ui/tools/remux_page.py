from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from app.notifications import play_completion_sound
from core.local_media_info import MediaFileInfo
from core.remux_models import REMUX_TARGET_LABELS, REMUX_TARGETS
from services.remux_service import RemuxService, assess_remux_compatibility
from ui.dialogs.warm_dialogs import show_warm_message
from ui.widgets.common import create_card
from workers.media_probe_worker import MediaProbeWorker
from workers.remux_worker import RemuxWorker


MEDIA_FILTER = (
    "미디어 파일 (*.mp4 *.mkv *.mov *.m4v *.webm *.avi *.ts *.mts *.m2ts "
    "*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus);;모든 파일 (*.*)"
)


class RemuxDropFrame(QFrame):
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


class RemuxPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._input_path = ""
        self._media_info: MediaFileInfo | None = None
        self._probe_worker: MediaProbeWorker | None = None
        self._remux_worker: RemuxWorker | None = None
        self._last_output_path = ""
        self._service = RemuxService()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(12)

        title = QLabel("Remux · 컨테이너 변경")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "영상과 음성을 다시 인코딩하지 않고 컨테이너만 바꿉니다. "
            "가능한 경우 모든 트랙·메타데이터·챕터를 그대로 보존합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        outer.addWidget(self._create_input_card())
        outer.addWidget(self._create_target_card())
        outer.addStretch()
        outer.addWidget(self._create_status_card())

        self._refresh_target_state()

    @property
    def has_active_operation(self) -> bool:
        probing = self._probe_worker is not None and self._probe_worker.isRunning()
        remuxing = self._remux_worker is not None and self._remux_worker.isRunning()
        return probing or remuxing

    def shutdown(self) -> None:
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.cancel()
            self._probe_worker.wait(1800)
        if self._remux_worker is not None and self._remux_worker.isRunning():
            self._remux_worker.cancel()
            self._remux_worker.wait(4000)

    def _create_input_card(self) -> QFrame:
        card, layout = create_card()

        heading = QLabel("입력 파일")
        heading.setObjectName("settingsGroupTitle")
        hint = QLabel("파일을 끌어놓거나 직접 선택하면 RR-V가 먼저 트랙 구성을 확인합니다.")
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        self.drop_area = RemuxDropFrame()
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(14, 12, 14, 12)
        drop_layout.setSpacing(8)

        self.path_input = QLineEdit()
        self.path_input.setObjectName("converterPathInput")
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("미디어 파일을 끌어놓거나 파일 선택 버튼 사용")

        self.select_button = QPushButton("파일 선택")
        self.select_button.setObjectName("secondaryButton")
        self.select_button.clicked.connect(self._choose_file)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.path_input, 1)
        row.addWidget(self.select_button)

        self.input_summary = QLabel("아직 선택한 파일이 없습니다.")
        self.input_summary.setObjectName("mutedText")
        self.input_summary.setWordWrap(True)

        drop_layout.addLayout(row)
        drop_layout.addWidget(self.input_summary)
        self.drop_area.file_dropped.connect(self._set_input_file)

        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(self.drop_area)
        return card

    def _create_target_card(self) -> QFrame:
        card, layout = create_card()

        heading = QLabel("출력 컨테이너")
        heading.setObjectName("settingsGroupTitle")
        description = QLabel(
            "호환되지 않는 트랙을 몰래 삭제하지 않습니다. 모든 트랙을 그대로 담을 수 있을 때만 Remux를 허용합니다."
        )
        description.setObjectName("mutedText")
        description.setWordWrap(True)

        self.target_group = QButtonGroup(self)
        self.target_group.setExclusive(True)
        self.target_buttons: dict[str, QRadioButton] = {}
        target_row = QHBoxLayout()
        target_row.setSpacing(22)
        for target in REMUX_TARGETS:
            button = QRadioButton(REMUX_TARGET_LABELS[target])
            button.setObjectName("settingsRadioButton")
            button.toggled.connect(
                lambda checked, value=target: self._target_changed(value, checked)
            )
            self.target_group.addButton(button)
            self.target_buttons[target] = button
            target_row.addWidget(button)
        target_row.addStretch()
        self.target_buttons["mkv"].setChecked(True)

        self.compatibility_label = QLabel("파일을 선택하면 호환성을 확인합니다.")
        self.compatibility_label.setObjectName("mutedText")
        self.compatibility_label.setWordWrap(True)

        self.output_label = QLabel("출력 파일: 확인 전")
        self.output_label.setObjectName("mutedText")
        self.output_label.setWordWrap(True)
        self.output_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout.addWidget(heading)
        layout.addWidget(description)
        layout.addLayout(target_row)
        layout.addWidget(self.compatibility_label)
        layout.addWidget(self.output_label)
        return card

    def _create_status_card(self) -> QFrame:
        card, layout = create_card()

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)

        self.status_label = QLabel("파일을 선택해 주세요.")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)

        self.open_output_button = QPushButton("결과 폴더 열기")
        self.open_output_button.setObjectName("secondaryButton")
        self.open_output_button.setEnabled(False)
        self.open_output_button.clicked.connect(self._open_output_folder)

        self.stop_button = QPushButton("중지")
        self.stop_button.setObjectName("secondaryButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._cancel_remux)

        self.start_button = QPushButton("Remux 시작")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start_remux)

        action_row = QHBoxLayout()
        action_row.setSpacing(8)
        action_row.addWidget(self.status_label, 1)
        action_row.addWidget(self.open_output_button)
        action_row.addWidget(self.stop_button)
        action_row.addWidget(self.start_button)

        layout.addWidget(self.progress_bar)
        layout.addLayout(action_row)
        return card

    def _choose_file(self) -> None:
        path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "Remux할 미디어 파일 선택",
            str(Path.home()),
            MEDIA_FILTER,
        )
        if path:
            self._set_input_file(path)

    def _set_input_file(self, path: str) -> None:
        candidate = Path(path).expanduser()
        if not candidate.is_file():
            show_warm_message(self, "파일 확인", "선택한 파일을 찾을 수 없습니다.")
            return
        if self.has_active_operation:
            show_warm_message(
                self,
                "Remux 작업 중",
                "현재 분석 또는 Remux 작업이 끝난 뒤 다른 파일을 선택해 주세요.",
            )
            return

        self._input_path = str(candidate)
        self._media_info = None
        self._last_output_path = ""
        self.path_input.setText(self._input_path)
        self.input_summary.setText("미디어 트랙을 확인하는 중…")
        self.status_label.setText("파일 분석 중…")
        self.progress_bar.setValue(0)
        self.open_output_button.setEnabled(False)
        self._refresh_target_state()

        worker = MediaProbeWorker(self._input_path)
        self._probe_worker = worker
        worker.succeeded.connect(self._probe_done)
        worker.failed.connect(self._probe_failed)
        worker.cancelled.connect(self._probe_cancelled)
        worker.finished.connect(self._probe_finished)
        worker.start()

    def _probe_done(self, media_info: object) -> None:
        if not isinstance(media_info, MediaFileInfo):
            self._probe_failed(
                "미디어 정보 형식이 올바르지 않습니다.",
                repr(media_info),
            )
            return
        self._media_info = media_info
        self.input_summary.setText(self._summary_text(media_info))
        self.status_label.setText("분석 완료 · 출력 컨테이너를 확인해 주세요.")
        self._choose_recommended_target(media_info)
        self._refresh_target_state()

    def _probe_failed(self, message: str, detail: str) -> None:
        self._media_info = None
        self.input_summary.setText(message)
        self.status_label.setText("파일 분석 실패")
        self._refresh_target_state()
        show_warm_message(
            self,
            "미디어 분석 실패",
            message if not detail else f"{message}\n\n{detail[:1200]}",
        )

    def _probe_cancelled(self, message: str) -> None:
        self.status_label.setText(message or "파일 분석 중지됨")

    def _probe_finished(self) -> None:
        self._probe_worker = None
        self._refresh_target_state()

    def _choose_recommended_target(self, media_info: MediaFileInfo) -> None:
        source = Path(media_info.file_name).suffix.lstrip(".").lower()
        if source == "mkv":
            order = ("mp4", "mov", "mkv")
        elif source in {"mp4", "mov", "m4v"}:
            order = ("mkv", "mp4", "mov")
        else:
            order = ("mkv", "mp4", "mov")

        fallback = next((item for item in order if item != source), order[0])
        selected = fallback
        for target in order:
            if target == source:
                continue
            if assess_remux_compatibility(media_info, target).supported:
                selected = target
                break
        self.target_buttons[selected].setChecked(True)

    def _target_changed(self, _target: str, checked: bool) -> None:
        if checked:
            self._refresh_target_state()

    def _current_target(self) -> str:
        for target, button in self.target_buttons.items():
            if button.isChecked():
                return target
        return "mkv"

    def _refresh_target_state(self) -> None:
        media_info = self._media_info
        if media_info is None:
            self.compatibility_label.setText("파일을 선택하면 호환성을 확인합니다.")
            self.output_label.setText("출력 파일: 확인 전")
            self.start_button.setEnabled(False)
            return

        target = self._current_target()
        compatibility = assess_remux_compatibility(media_info, target)
        label = REMUX_TARGET_LABELS[target]
        if compatibility.supported:
            self.compatibility_label.setText(
                f"사용 가능 · {label} · {compatibility.summary}"
            )
            output_path = self._service.suggested_output_path(media_info, target)
            self.output_label.setText(f"출력 파일: {output_path}")
        else:
            self.compatibility_label.setText(
                f"사용 불가 · {label} · {compatibility.summary}"
            )
            self.output_label.setText("출력 파일: 호환성 문제를 먼저 해결해 주세요.")

        busy = self.has_active_operation
        self.start_button.setEnabled(compatibility.supported and not busy)

    def _start_remux(self) -> None:
        media_info = self._media_info
        if media_info is None or self.has_active_operation:
            return
        target = self._current_target()
        compatibility = assess_remux_compatibility(media_info, target)
        if not compatibility.supported:
            show_warm_message(self, "Remux 호환성", compatibility.summary)
            return

        self._last_output_path = ""
        self.progress_bar.setValue(0)
        self.status_label.setText("Remux 준비 중…")
        self.select_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.open_output_button.setEnabled(False)
        for button in self.target_buttons.values():
            button.setEnabled(False)

        worker = RemuxWorker(media_info, target)
        self._remux_worker = worker
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.phase_changed.connect(self.status_label.setText)
        worker.succeeded.connect(self._remux_done)
        worker.failed.connect(self._remux_failed)
        worker.cancelled.connect(self._remux_cancelled)
        worker.finished.connect(self._remux_finished)
        worker.start()

    def _cancel_remux(self) -> None:
        if self._remux_worker is None or not self._remux_worker.isRunning():
            return
        self.status_label.setText("Remux를 중지하는 중…")
        self.stop_button.setEnabled(False)
        self._remux_worker.cancel()

    def _remux_done(self, output_path: str, _size_bytes: int) -> None:
        self._last_output_path = output_path
        self.progress_bar.setValue(100)
        self.status_label.setText(f"Remux 완료 · {Path(output_path).name}")
        self.open_output_button.setEnabled(True)
        play_completion_sound()

    def _remux_failed(self, message: str, detail: str) -> None:
        self.status_label.setText("Remux 실패")
        show_warm_message(
            self,
            "Remux 실패",
            message if not detail else f"{message}\n\n{detail[:1600]}",
        )

    def _remux_cancelled(self, message: str) -> None:
        self.status_label.setText(message or "Remux 중지됨")

    def _remux_finished(self) -> None:
        self._remux_worker = None
        self.select_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        for button in self.target_buttons.values():
            button.setEnabled(True)
        self._refresh_target_state()

    def _open_output_folder(self) -> None:
        if not self._last_output_path:
            return
        folder = Path(self._last_output_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    @staticmethod
    def _summary_text(media_info: MediaFileInfo) -> str:
        parts = [media_info.container_text]
        video = media_info.primary_video
        if video is not None:
            video_parts = [video.codec_name.upper() or "VIDEO", video.resolution_text]
            if video.frame_rate_text != "확인 불가":
                video_parts.append(video.frame_rate_text)
            if video.dynamic_range:
                video_parts.append(video.dynamic_range)
            parts.append(" · ".join(video_parts))

        if media_info.audio_tracks:
            audio = media_info.audio_tracks[0]
            channel_text = audio.channel_layout or (
                f"{audio.channels}ch" if audio.channels else ""
            )
            audio_text = audio.codec_name.upper() or "AUDIO"
            if channel_text:
                audio_text += f" {channel_text}"
            if len(media_info.audio_tracks) > 1:
                audio_text += f" 외 {len(media_info.audio_tracks) - 1}개"
            parts.append(audio_text)

        parts.append(f"자막 {len(media_info.subtitle_tracks)}개")
        parts.append(f"챕터 {len(media_info.chapters)}개")
        return " · ".join(parts)
