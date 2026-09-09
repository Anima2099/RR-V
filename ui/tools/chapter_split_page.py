from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from app.notifications import play_completion_sound
from core.local_media_info import MediaFileInfo
from services.chapter_split_service import ChapterSplitService, valid_chapters
from ui.dialogs.warm_dialogs import show_warm_message
from ui.widgets.common import create_card
from workers.chapter_split_worker import ChapterSplitWorker
from workers.media_probe_worker import MediaProbeWorker


MEDIA_FILTER = (
    "미디어 파일 (*.mp4 *.mkv *.mov *.m4v *.webm *.avi *.ts *.mts *.m2ts "
    "*.mp3 *.m4a *.m4b *.aac *.flac *.wav *.ogg *.opus *.mka);;"
    "모든 파일 (*.*)"
)


class ChapterDropFrame(QFrame):
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


class ChapterSplitPage(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._input_path = ""
        self._media_info: MediaFileInfo | None = None
        self._probe_worker: MediaProbeWorker | None = None
        self._split_worker: ChapterSplitWorker | None = None
        self._last_output_directory = ""
        self._service = ChapterSplitService()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 14, 24, 14)
        outer.setSpacing(10)

        title = QLabel("챕터 분할")
        title.setObjectName("sectionTitle")
        description = QLabel(
            "파일에 들어 있는 챕터 정보를 읽어 각 챕터를 별도 파일로 나눕니다. "
            "영상과 음성은 다시 인코딩하지 않아 빠르고 원본 품질을 유지합니다."
        )
        description.setObjectName("bodyText")
        description.setWordWrap(True)
        outer.addWidget(title)
        outer.addWidget(description)

        outer.addWidget(self._create_input_card())
        outer.addWidget(self._create_chapter_card())
        outer.addStretch()
        outer.addWidget(self._create_status_card())

        self._refresh_state()

    @property
    def has_active_operation(self) -> bool:
        probing = self._probe_worker is not None and self._probe_worker.isRunning()
        splitting = self._split_worker is not None and self._split_worker.isRunning()
        return probing or splitting

    def shutdown(self) -> None:
        if self._probe_worker is not None and self._probe_worker.isRunning():
            self._probe_worker.cancel()
            self._probe_worker.wait(1800)
        if self._split_worker is not None and self._split_worker.isRunning():
            self._split_worker.cancel()
            self._split_worker.wait(5000)

    def _create_input_card(self) -> QFrame:
        card, layout = create_card()
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(9)

        heading = QLabel("입력 파일")
        heading.setObjectName("settingsGroupTitle")
        hint = QLabel(
            "파일을 끌어놓거나 직접 선택하면 RR-V가 내장 챕터를 먼저 확인합니다."
        )
        hint.setObjectName("mutedText")
        hint.setWordWrap(True)

        self.drop_area = ChapterDropFrame()
        drop_layout = QVBoxLayout(self.drop_area)
        drop_layout.setContentsMargins(14, 8, 14, 8)
        drop_layout.setSpacing(6)

        self.path_input = QLineEdit()
        self.path_input.setObjectName("converterPathInput")
        self.path_input.setReadOnly(True)
        self.path_input.setPlaceholderText("챕터가 들어 있는 미디어 파일을 선택")

        self.select_button = QPushButton("파일 선택")
        self.select_button.setObjectName("secondaryButton")
        self.select_button.clicked.connect(self._choose_file)

        row = QHBoxLayout()
        row.setSpacing(10)
        row.addWidget(self.path_input, 1)
        row.addWidget(self.select_button)

        self.input_summary = QLabel("아직 선택한 파일이 없습니다.")
        self.input_summary.setObjectName("mutedText")
        self.input_summary.setWordWrap(False)

        drop_layout.addLayout(row)
        drop_layout.addWidget(self.input_summary)
        self.drop_area.file_dropped.connect(self._set_input_file)

        layout.addWidget(heading)
        layout.addWidget(hint)
        layout.addWidget(self.drop_area)
        return card

    def _create_chapter_card(self) -> QFrame:
        card, layout = create_card()
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)

        heading = QLabel("감지된 챕터")
        heading.setObjectName("settingsGroupTitle")
        layout.addWidget(heading)

        self.chapter_status_label = QLabel(
            "파일을 선택하면 챕터 수와 제목을 표시합니다."
        )
        self.chapter_status_label.setObjectName("mutedText")
        self.chapter_status_label.setWordWrap(True)
        layout.addWidget(self.chapter_status_label)

        self.chapter_preview_label = QLabel("")
        self.chapter_preview_label.setObjectName("bodyText")
        self.chapter_preview_label.setWordWrap(True)
        self.chapter_preview_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self.chapter_preview_label.hide()
        layout.addWidget(self.chapter_preview_label)

        self.output_label = QLabel("출력 폴더: 확인 전")
        self.output_label.setObjectName("mutedText")
        self.output_label.setWordWrap(False)
        self.output_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        layout.addWidget(self.output_label)

        accuracy_hint = QLabel(
            "무손실 분할은 키프레임을 기준으로 처리하므로 일부 파일은 "
            "챕터 시작 지점이 아주 조금 앞당겨질 수 있습니다."
        )
        accuracy_hint.setObjectName("mutedText")
        accuracy_hint.setWordWrap(True)
        layout.addWidget(accuracy_hint)
        return card

    def _create_status_card(self) -> QFrame:
        card, layout = create_card()
        layout.setContentsMargins(20, 14, 20, 14)
        layout.setSpacing(8)

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
        self.stop_button.clicked.connect(self._cancel_split)

        self.start_button = QPushButton("챕터 분할 시작")
        self.start_button.setObjectName("primaryButton")
        self.start_button.setEnabled(False)
        self.start_button.clicked.connect(self._start_split)

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
            "챕터를 분할할 미디어 파일 선택",
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
                "챕터 분할 작업 중",
                "현재 분석 또는 챕터 분할이 끝난 뒤 다른 파일을 선택해 주세요.",
            )
            return

        self._input_path = str(candidate)
        self._media_info = None
        self._last_output_directory = ""
        self.path_input.setText(self._input_path)
        self.input_summary.setText("내장 챕터를 확인하는 중…")
        self.chapter_status_label.setText("챕터 정보를 읽는 중…")
        self.chapter_preview_label.clear()
        self.chapter_preview_label.hide()
        self.output_label.setText("출력 폴더: 확인 중…")
        self.output_label.setToolTip("")
        self.status_label.setText("파일 분석 중…")
        self.progress_bar.setValue(0)
        self.open_output_button.setEnabled(False)
        self._refresh_state()

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
        chapters = valid_chapters(media_info)
        container = Path(media_info.file_name).suffix.lstrip(".").upper() or "MEDIA"
        self.input_summary.setText(
            f"{container} · {media_info.duration_text} · 챕터 {len(chapters)}개"
        )

        if not chapters:
            self.chapter_status_label.setText(
                "분할 가능한 내장 챕터가 없습니다."
            )
            self.chapter_preview_label.clear()
            self.chapter_preview_label.hide()
            self.output_label.setText("출력 폴더: 생성하지 않음")
            self.output_label.setToolTip("")
            self.status_label.setText("챕터 없음 · 다른 파일을 선택해 주세요.")
            self._refresh_state()
            return

        self.chapter_status_label.setText(
            f"챕터 {len(chapters)}개를 찾았습니다. 전체 챕터를 순서대로 분할합니다."
        )
        preview_lines: list[str] = []
        preview_limit = 8
        for position, chapter in enumerate(chapters[:preview_limit], start=1):
            title = chapter.title.strip() or f"챕터 {position:02d}"
            preview_lines.append(
                f"{position:02d}. {self._clock_text(chapter.start_seconds)}  {title}"
            )
        if len(chapters) > preview_limit:
            preview_lines.append(f"… 외 {len(chapters) - preview_limit}개")
        self.chapter_preview_label.setText("\n".join(preview_lines))
        self.chapter_preview_label.show()

        output_directory = self._service.suggested_output_directory(media_info)
        self.output_label.setText(f"출력 폴더: {output_directory.name}")
        self.output_label.setToolTip(str(output_directory))
        self.status_label.setText("분석 완료 · 챕터 분할을 시작할 수 있습니다.")
        self._refresh_state()

    def _probe_failed(self, message: str, detail: str) -> None:
        self._media_info = None
        self.input_summary.setText(message)
        self.chapter_status_label.setText("챕터 정보를 확인하지 못했습니다.")
        self.chapter_preview_label.clear()
        self.chapter_preview_label.hide()
        self.output_label.setText("출력 폴더: 확인 실패")
        self.output_label.setToolTip("")
        self.status_label.setText("파일 분석 실패")
        self._refresh_state()
        show_warm_message(
            self,
            "미디어 분석 실패",
            message if not detail else f"{message}\n\n{detail[:1200]}",
        )

    def _probe_cancelled(self, message: str) -> None:
        self.status_label.setText(message or "파일 분석 중지됨")

    def _probe_finished(self) -> None:
        self._probe_worker = None
        self._refresh_state()

    def _refresh_state(self) -> None:
        chapters = (
            valid_chapters(self._media_info)
            if self._media_info is not None
            else ()
        )
        busy = self.has_active_operation
        self.select_button.setEnabled(not busy)
        self.start_button.setEnabled(bool(chapters) and not busy)

    def _start_split(self) -> None:
        media_info = self._media_info
        if media_info is None or self.has_active_operation:
            return
        chapters = valid_chapters(media_info)
        if not chapters:
            show_warm_message(
                self,
                "챕터 확인",
                "분할할 수 있는 내장 챕터가 없습니다.",
            )
            return

        self._last_output_directory = ""
        self.progress_bar.setValue(0)
        self.status_label.setText("챕터 분할 준비 중…")
        self.select_button.setEnabled(False)
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.open_output_button.setEnabled(False)

        worker = ChapterSplitWorker(media_info)
        self._split_worker = worker
        worker.progress_changed.connect(self.progress_bar.setValue)
        worker.phase_changed.connect(self.status_label.setText)
        worker.succeeded.connect(self._split_done)
        worker.failed.connect(self._split_failed)
        worker.cancelled.connect(self._split_cancelled)
        worker.finished.connect(self._split_finished)
        worker.start()

    def _cancel_split(self) -> None:
        if self._split_worker is None or not self._split_worker.isRunning():
            return
        self.status_label.setText("챕터 분할을 중지하는 중…")
        self.stop_button.setEnabled(False)
        self._split_worker.cancel()

    def _split_done(self, output_directory: str, count: int) -> None:
        self._last_output_directory = output_directory
        self.progress_bar.setValue(100)
        self.status_label.setText(
            f"챕터 분할 완료 · {count}개 · {Path(output_directory).name}"
        )
        self.open_output_button.setEnabled(True)
        play_completion_sound()
        self._reset_input_after_success()

    def _split_failed(self, message: str, detail: str) -> None:
        self.status_label.setText("챕터 분할 실패")
        show_warm_message(
            self,
            "챕터 분할 실패",
            message if not detail else f"{message}\n\n{detail[:1600]}",
        )

    def _split_cancelled(self, message: str) -> None:
        self.status_label.setText(message or "챕터 분할 중지됨")

    def _split_finished(self) -> None:
        self._split_worker = None
        self.stop_button.setEnabled(False)
        self._refresh_state()

    def _reset_input_after_success(self) -> None:
        self._input_path = ""
        self._media_info = None
        self.path_input.clear()
        self.input_summary.setText("아직 선택한 파일이 없습니다.")
        self.chapter_status_label.setText(
            "다음 파일을 선택하면 챕터를 다시 확인합니다."
        )
        self.chapter_preview_label.clear()
        self.chapter_preview_label.hide()
        self.output_label.setText("출력 폴더: 다음 파일을 선택해 주세요.")
        self.output_label.setToolTip("")
        self.start_button.setEnabled(False)

    def _open_output_folder(self) -> None:
        if not self._last_output_directory:
            return
        directory = Path(self._last_output_directory)
        if not directory.is_dir():
            show_warm_message(
                self,
                "결과 폴더",
                "완성된 챕터 폴더를 찾을 수 없습니다.",
            )
            self.open_output_button.setEnabled(False)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(directory)))

    @staticmethod
    def _clock_text(seconds: float) -> str:
        total = max(0, int(seconds))
        hours, remainder = divmod(total, 3600)
        minutes, secs = divmod(remainder, 60)
        if hours:
            return f"{hours:02d}:{minutes:02d}:{secs:02d}"
        return f"{minutes:02d}:{secs:02d}"
