from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from core.local_media_info import (
    AudioTrackInfo,
    MediaChapter,
    MediaFileInfo,
    OtherTrackInfo,
    SubtitleTrackInfo,
    VideoTrackInfo,
)
from ui.widgets.common import create_card
from workers.media_probe_worker import MediaProbeWorker


MEDIA_FILTER = (
    "미디어 파일 (*.mp4 *.mkv *.webm *.mov *.avi *.m4v *.ts *.m2ts *.mts *.flv *.wmv "
    "*.mp3 *.m4a *.aac *.flac *.wav *.ogg *.opus);;모든 파일 (*.*)"
)

_CODEC_LABELS = {
    "h264": "H.264",
    "hevc": "H.265 / HEVC",
    "av1": "AV1",
    "vp9": "VP9",
    "vp8": "VP8",
    "mpeg4": "MPEG-4",
    "aac": "AAC",
    "ac3": "AC-3",
    "eac3": "E-AC-3",
    "dts": "DTS",
    "flac": "FLAC",
    "opus": "Opus",
    "vorbis": "Vorbis",
    "mp3": "MP3",
    "subrip": "SRT",
    "ass": "ASS",
    "ssa": "SSA",
    "webvtt": "WebVTT",
    "mov_text": "MOV text",
}


class MediaFileDropFrame(QFrame):
    file_dropped = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.setObjectName("converterDropArea")
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if any(url.isLocalFile() for url in event.mimeData().urls()):
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


class MediaInfoPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._worker: MediaProbeWorker | None = None
        self._current_info: MediaFileInfo | None = None

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 18, 24, 18)
        outer.setSpacing(12)

        title = QLabel("상세 미디어 정보")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "미디어 파일을 FFprobe로 한 번 분석해 컨테이너, 코덱, 트랙, HDR, 챕터 정보를 정리합니다. "
            "이 분석 결과는 이후 Remux와 챕터 기능에서도 같은 구조로 재사용합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        self.drop_area = MediaFileDropFrame()
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(14, 12, 14, 12)
        drop_layout.setSpacing(8)

        path_row = QHBoxLayout()
        path_row.setSpacing(10)
        self.path_input = QLineEdit()
        self.path_input.setObjectName("converterPathInput")
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("미디어 파일을 끌어놓거나 파일 선택 버튼 사용")
        self.select_button = QPushButton("파일 선택")
        self.select_button.setObjectName("secondaryButton")
        self.select_button.clicked.connect(self._choose_file)
        path_row.addWidget(self.path_input, 1)
        path_row.addWidget(self.select_button)

        self.status_label = QLabel("아직 분석한 파일이 없습니다.")
        self.status_label.setObjectName("mutedText")
        self.status_label.setWordWrap(True)
        drop_layout.addLayout(path_row)
        drop_layout.addWidget(self.status_label)
        self.drop_area.file_dropped.connect(self._set_input_file)
        outer.addWidget(self.drop_area)

        self.result_scroll = QScrollArea()
        self.result_scroll.setObjectName("settingsTabScroll")
        self.result_scroll.setWidgetResizable(True)
        self.result_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.result_scroll.setFrameShape(QFrame.Shape.NoFrame)

        self.result_content = QWidget()
        self.result_layout = QVBoxLayout(self.result_content)
        self.result_layout.setContentsMargins(0, 2, 4, 10)
        self.result_layout.setSpacing(12)
        self.result_scroll.setWidget(self.result_content)
        outer.addWidget(self.result_scroll, 1)

        self._render_empty_state()

    @property
    def has_active_operation(self) -> bool:
        return self._worker is not None and self._worker.isRunning()

    def shutdown(self) -> None:
        worker = self._worker
        if worker is None or not worker.isRunning():
            return
        worker.cancel()
        worker.wait(2500)

    def _choose_file(self) -> None:
        if self.has_active_operation:
            return
        selected, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "미디어 파일 선택",
            "",
            MEDIA_FILTER,
        )
        if selected:
            self._set_input_file(selected)

    def _set_input_file(self, input_path: str) -> None:
        if self.has_active_operation:
            self.status_label.setText("현재 파일 정보를 확인하는 중입니다.")
            return

        path = Path(input_path).expanduser()
        if not path.is_file():
            self.status_label.setText("선택한 파일을 찾을 수 없습니다.")
            return

        self.path_input.setText(str(path))
        self.path_input.setToolTip(str(path))
        self.status_label.setToolTip("")
        self.status_label.setText("FFprobe로 미디어 정보를 확인하는 중…")
        self.select_button.setEnabled(False)
        self._current_info = None
        self._render_loading_state()

        worker = MediaProbeWorker(str(path))
        self._worker = worker
        worker.succeeded.connect(self._probe_succeeded)
        worker.failed.connect(self._probe_failed)
        worker.cancelled.connect(self._probe_cancelled)
        worker.finished.connect(self._probe_finished)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _probe_succeeded(self, result: object) -> None:
        if not isinstance(result, MediaFileInfo):
            self._probe_failed(
                "미디어 정보를 해석하지 못했습니다.",
                "분석 결과가 MediaFileInfo 형식이 아닙니다.",
            )
            return
        self._current_info = result
        self.status_label.setToolTip("")
        self.status_label.setText(
            f"분석 완료 · 스트림 {result.stream_count}개 · 챕터 {len(result.chapters)}개"
        )
        self._render_info(result)

    def _probe_failed(self, message: str, detail: str) -> None:
        self._current_info = None
        self.status_label.setText(message)
        self.status_label.setToolTip(detail)
        self._clear_result_widgets()
        card, layout = create_card()
        title = QLabel("미디어 정보를 읽지 못했습니다")
        title.setObjectName("sectionTitle")
        body = QLabel(message)
        body.setObjectName("bodyText")
        body.setWordWrap(True)
        layout.addWidget(title)
        layout.addWidget(body)
        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("mutedText")
            detail_label.setWordWrap(True)
            detail_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            layout.addWidget(detail_label)
        self.result_layout.addWidget(card)
        self.result_layout.addStretch()

    def _probe_cancelled(self, message: str) -> None:
        self._current_info = None
        self.status_label.setText(message or "미디어 정보 확인이 취소되었습니다.")
        self._render_empty_state()

    def _probe_finished(self) -> None:
        self.select_button.setEnabled(True)
        self._worker = None

    def _render_loading_state(self) -> None:
        self._clear_result_widgets()
        label = QLabel("파일의 스트림과 챕터 구조를 읽고 있습니다…")
        label.setObjectName("mutedText")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.result_layout.addWidget(label)
        self.result_layout.addStretch()

    def _render_empty_state(self) -> None:
        self._clear_result_widgets()
        label = QLabel(
            "파일을 선택하면 상세 정보가 여기에 표시됩니다.\n"
            "영상뿐 아니라 오디오 전용 파일과 다중 트랙 파일도 분석할 수 있습니다."
        )
        label.setObjectName("mutedText")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setWordWrap(True)
        self.result_layout.addWidget(label)
        self.result_layout.addStretch()

    def _render_info(self, info: MediaFileInfo) -> None:
        self._clear_result_widgets()
        self.result_layout.addWidget(self._create_summary_card(info))
        if info.video_tracks:
            self.result_layout.addWidget(self._create_video_card(info.video_tracks))
        if info.audio_tracks:
            self.result_layout.addWidget(self._create_audio_card(info.audio_tracks))
        if info.subtitle_tracks:
            self.result_layout.addWidget(
                self._create_subtitle_card(info.subtitle_tracks)
            )
        if info.other_tracks:
            self.result_layout.addWidget(self._create_other_card(info.other_tracks))
        if info.chapters:
            self.result_layout.addWidget(self._create_chapter_card(info.chapters))
        if info.metadata:
            self.result_layout.addWidget(self._create_metadata_card(info.metadata))
        self.result_layout.addStretch()

    def _create_summary_card(self, info: MediaFileInfo) -> QFrame:
        card, layout = create_card()
        title = QLabel("파일 요약")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)

        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(8)
        rows = (
            ("파일", info.file_name),
            ("컨테이너", info.container_text),
            ("파일 크기", info.size_text),
            ("재생 시간", info.duration_text),
            ("전체 비트레이트", info.bit_rate_text),
            (
                "스트림",
                f"비디오 {len(info.video_tracks)} · 오디오 {len(info.audio_tracks)} · "
                f"자막 {len(info.subtitle_tracks)} · 기타 {len(info.other_tracks)}",
            ),
            ("챕터", f"{len(info.chapters)}개"),
        )
        for row, (name, value) in enumerate(rows):
            self._add_grid_row(grid, row, name, value)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    def _create_video_card(self, tracks: tuple[VideoTrackInfo, ...]) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"비디오 트랙 · {len(tracks)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for track in tracks:
            flags: list[str] = []
            if track.is_default:
                flags.append("기본")
            if track.is_attached_picture:
                flags.append("첨부 이미지")
            details = [
                track.resolution_text,
                track.frame_rate_text,
                track.profile,
                track.pixel_format,
                track.dynamic_range,
                track.bit_rate_text,
                self._language_text(track.language),
                track.title,
                *flags,
            ]
            if track.rotation_degrees not in {None, 0}:
                details.append(f"회전 {track.rotation_degrees}°")
            layout.addWidget(
                self._create_track_item(
                    f"스트림 #{track.index} · {self._codec_label(track.codec_name)}",
                    details,
                )
            )
        return card

    def _create_audio_card(self, tracks: tuple[AudioTrackInfo, ...]) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"오디오 트랙 · {len(tracks)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for track in tracks:
            channels = track.channel_layout
            if not channels and track.channels:
                channels = f"{track.channels}채널"
            sample_rate = (
                f"{track.sample_rate / 1000:g} kHz" if track.sample_rate else ""
            )
            details = [
                track.profile,
                channels,
                sample_rate,
                track.sample_format,
                track.bit_rate_text,
                self._language_text(track.language),
                track.title,
                "기본" if track.is_default else "",
            ]
            layout.addWidget(
                self._create_track_item(
                    f"스트림 #{track.index} · {self._codec_label(track.codec_name)}",
                    details,
                )
            )
        return card

    def _create_subtitle_card(
        self,
        tracks: tuple[SubtitleTrackInfo, ...],
    ) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"자막 트랙 · {len(tracks)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for track in tracks:
            details = [
                self._language_text(track.language),
                track.title,
                "기본" if track.is_default else "",
                "강제 자막" if track.is_forced else "",
            ]
            layout.addWidget(
                self._create_track_item(
                    f"스트림 #{track.index} · {self._codec_label(track.codec_name)}",
                    details,
                )
            )
        return card

    def _create_other_card(self, tracks: tuple[OtherTrackInfo, ...]) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"기타 스트림 · {len(tracks)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for track in tracks:
            details = [
                track.codec_type,
                self._language_text(track.language),
                track.title,
                "기본" if track.is_default else "",
            ]
            layout.addWidget(
                self._create_track_item(
                    f"스트림 #{track.index} · {self._codec_label(track.codec_name)}",
                    details,
                )
            )
        return card

    def _create_chapter_card(self, chapters: tuple[MediaChapter, ...]) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"챕터 · {len(chapters)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        for chapter in chapters:
            name = chapter.title or f"챕터 {chapter.index + 1}"
            time_text = (
                f"{self._clock_text(chapter.start_seconds)} → "
                f"{self._clock_text(chapter.end_seconds)}"
            )
            layout.addWidget(
                self._create_track_item(
                    f"{chapter.index + 1:02d}. {name}",
                    [time_text],
                )
            )
        return card

    def _create_metadata_card(
        self,
        metadata: tuple[tuple[str, str], ...],
    ) -> QFrame:
        card, layout = create_card()
        title = QLabel(f"파일 메타데이터 · {len(metadata)}개")
        title.setObjectName("sectionTitle")
        layout.addWidget(title)
        grid = QGridLayout()
        grid.setHorizontalSpacing(20)
        grid.setVerticalSpacing(7)
        for row, (key, value) in enumerate(metadata):
            self._add_grid_row(grid, row, key, value)
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        return card

    @staticmethod
    def _create_track_item(title_text: str, details: list[str]) -> QFrame:
        item = QFrame()
        item.setObjectName("settingsOptionGroup")
        layout = QVBoxLayout(item)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(4)

        title = QLabel(title_text)
        title.setObjectName("settingsGroupTitle")
        detail_text = " · ".join(value for value in details if value)
        detail = QLabel(detail_text or "추가 정보 없음")
        detail.setObjectName("mutedText")
        detail.setWordWrap(True)
        detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(title)
        layout.addWidget(detail)
        return item

    @staticmethod
    def _add_grid_row(
        grid: QGridLayout,
        row: int,
        name: str,
        value: str,
    ) -> None:
        name_label = QLabel(name)
        name_label.setObjectName("settingsGroupTitle")
        value_label = QLabel(value or "확인 불가")
        value_label.setObjectName("bodyText")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        grid.addWidget(name_label, row, 0, alignment=Qt.AlignmentFlag.AlignTop)
        grid.addWidget(value_label, row, 1)

    @staticmethod
    def _codec_label(codec_name: str) -> str:
        normalized = codec_name.strip().casefold()
        if not normalized:
            return "알 수 없는 코덱"
        return _CODEC_LABELS.get(normalized, codec_name.upper())

    @staticmethod
    def _language_text(language: str) -> str:
        return f"언어 {language}" if language else ""

    @staticmethod
    def _clock_text(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"

    def _clear_result_widgets(self) -> None:
        while self.result_layout.count():
            item = self.result_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
