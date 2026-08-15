from __future__ import annotations

from pathlib import Path
from time import perf_counter

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QDrag, QIcon, QMouseEvent, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app.paths import (
    CLOSE_ICON_PATH,
    COPY_ICON_PATH,
    DRAG_ICON_PATH,
    MORE_ICON_PATH,
    RETRY_ICON_PATH,
    STOP_ICON_PATH,
)
from app.performance_log import PerformanceSpan, write_performance
from core.download_task import DownloadStatus, DownloadTask


TASK_MIME_TYPE = "application/x-rrv-download-task"


class ElidedLabel(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        self.setToolTip(text)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

    def set_full_text(self, text: str) -> None:
        self._full_text = text
        self.setToolTip(text)
        self._update_elided_text()

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self) -> None:
        available_width = max(10, self.width() - 4)
        elided = self.fontMetrics().elidedText(
            self._full_text,
            Qt.TextElideMode.ElideRight,
            available_width,
        )
        super().setText(elided)


class ClickableFrame(QFrame):
    clicked = Signal()
    double_clicked = Signal()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_clicked.emit()
        super().mouseDoubleClickEvent(event)


class DragHandle(QToolButton):
    drag_started = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._press_position = QPoint()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._press_position = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not event.buttons() & Qt.MouseButton.LeftButton:
            return

        distance = (
            event.position().toPoint() - self._press_position
        ).manhattanLength()
        if distance >= QApplication.startDragDistance():
            self.drag_started.emit()
            return

        super().mouseMoveEvent(event)


class DownloadTaskCard(QFrame):
    remove_requested = Signal(str)
    message_requested = Signal(str)
    size_changed = Signal()
    details_toggle_requested = Signal(str)
    retry_requested = Signal(str)
    stop_requested = Signal(str)
    path_changed = Signal(str)
    thumbnail_recovery_requested = Signal(str)
    subtitle_recovery_requested = Signal(str)

    def __init__(self, task: DownloadTask, index_number: int) -> None:
        total_started = perf_counter()
        super().__init__()
        self.task = task
        self.index_number = index_number
        self._details_visible = False
        self._primary_action_is_stop = False
        self._reordering_enabled = True

        self.setObjectName("taskCard")
        self.setProperty("taskStatus", task.status.value)
        self.setAcceptDrops(False)

        with PerformanceSpan(
            "card.build_ui",
            first_index=index_number,
            has_thumbnail=bool(task.thumbnail_data),
        ):
            self._build_ui()
        with PerformanceSpan("card.initial_status_ui"):
            # 아직 화면에 붙기 전이므로 강제 unpolish/polish는 하지 않는다.
            self._update_status_ui(refresh_style=False)

        write_performance(
            "card.init.total",
            (perf_counter() - total_started) * 1000.0,
            first_index=index_number,
            has_thumbnail=bool(task.thumbnail_data),
        )

    def _build_ui(self) -> None:
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(14, 12, 14, 12)
        root_layout.setSpacing(10)

        summary_frame = ClickableFrame()
        summary_frame.setObjectName("taskSummary")
        summary_frame.setCursor(Qt.CursorShape.PointingHandCursor)
        summary_frame.clicked.connect(
            lambda: self.details_toggle_requested.emit(self.task.task_id)
        )
        summary_frame.double_clicked.connect(self._handle_double_click)

        summary_layout = QHBoxLayout(summary_frame)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(12)

        self.drag_handle = DragHandle()
        self.drag_handle.setObjectName("dragHandle")
        self.drag_handle.setIcon(QIcon(str(DRAG_ICON_PATH)))
        self.drag_handle.setIconSize(QSize(20, 20))
        self.drag_handle.setToolTip("끌어서 다운로드 순서 변경")
        self.drag_handle.setCursor(Qt.CursorShape.OpenHandCursor)
        self.drag_handle.drag_started.connect(self._start_drag)

        thumbnail = QFrame()
        thumbnail.setObjectName("taskThumbnail")
        thumbnail.setFixedSize(128, 72)

        thumbnail_layout = QVBoxLayout(thumbnail)
        thumbnail_layout.setContentsMargins(6, 6, 6, 6)
        thumbnail_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.thumbnail_label = QLabel()
        self.thumbnail_label.setObjectName("thumbnailText")
        self.thumbnail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )
        thumbnail_layout.addWidget(self.thumbnail_label)
        self._update_thumbnail()

        info_frame = QFrame()
        info_frame.setObjectName("taskInfo")
        info_frame.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents,
            True,
        )

        info_layout = QVBoxLayout(info_frame)
        info_layout.setContentsMargins(0, 0, 0, 0)
        info_layout.setSpacing(5)

        self.title_label = ElidedLabel(self.task.title)
        self.title_label.setObjectName("taskTitle")

        self.meta_label = ElidedLabel(self.task.meta_text)
        self.meta_label.setObjectName("taskMeta")

        status_row = QHBoxLayout()
        status_row.setContentsMargins(0, 0, 0, 0)
        status_row.setSpacing(9)

        self.status_pill = QLabel()
        self.status_pill.setObjectName("statusPill")
        self.status_pill.setProperty("taskStatus", self.task.status.value)
        self.status_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setObjectName("taskProgress")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setProperty("taskStatus", self.task.status.value)

        status_row.addWidget(self.status_pill)
        status_row.addWidget(self.progress_bar, 1)

        info_layout.addWidget(self.title_label)
        info_layout.addWidget(self.meta_label)
        info_layout.addLayout(status_row)

        actions = QFrame()
        actions.setObjectName("taskActions")

        actions_layout = QHBoxLayout(actions)
        actions_layout.setContentsMargins(0, 0, 0, 0)
        actions_layout.setSpacing(4)

        self.retry_button = self._create_action_button(
            RETRY_ICON_PATH, "이 영상을 다시 다운로드", self._primary_action
        )
        self.copy_button = self._create_action_button(
            COPY_ICON_PATH, "영상 주소 복사", self._copy_url
        )
        self.more_button = self._create_action_button(
            MORE_ICON_PATH, "추가 작업", self._show_more_menu
        )
        self.remove_button = self._create_action_button(
            CLOSE_ICON_PATH,
            "목록에서 삭제",
            lambda: self.remove_requested.emit(self.task.task_id),
        )
        self.remove_button.setObjectName("dangerActionButton")

        actions_layout.addWidget(self.retry_button)
        actions_layout.addWidget(self.copy_button)
        actions_layout.addWidget(self.more_button)
        actions_layout.addWidget(self.remove_button)

        summary_layout.addWidget(self.drag_handle)
        summary_layout.addWidget(thumbnail)
        summary_layout.addWidget(info_frame, 1)
        summary_layout.addWidget(actions)

        self.details_frame = self._create_details_frame()
        self.details_frame.hide()

        root_layout.addWidget(summary_frame)
        root_layout.addWidget(self.details_frame)

    def _create_action_button(self, icon_path, tooltip: str, callback) -> QToolButton:
        button = QToolButton()
        button.setObjectName("taskActionButton")
        button.setIcon(QIcon(str(icon_path)))
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(callback)
        return button

    def _create_details_frame(self) -> QFrame:
        frame = QFrame()
        frame.setObjectName("taskDetails")

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(12)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(1, 1)

        self.detail_status = QLabel()
        self.detail_progress = QLabel()
        self.detail_size = QLabel()
        self.detail_speed = QLabel()
        self.detail_eta = QLabel()
        self.detail_phase = QLabel()
        self.detail_path = ElidedLabel(self.task.save_path)
        self.detail_output = ElidedLabel(self.task.output_file or "-")
        self.detail_url = ElidedLabel(self.task.url)

        rows = [
            ("상태", self.detail_status),
            ("진행률", self.detail_progress),
            ("받은 용량 / 전체 용량", self.detail_size),
            ("속도", self.detail_speed),
            ("남은 시간", self.detail_eta),
            ("현재 단계", self.detail_phase),
            ("저장 경로", self.detail_path),
            ("완료 파일", self.detail_output),
            ("원본 주소", self.detail_url),
        ]

        for row_index, (name, value_widget) in enumerate(rows):
            label = QLabel(name)
            label.setObjectName("detailName")
            if value_widget is self.detail_size:
                self.detail_size_name = label
            value_widget.setObjectName("detailValue")
            grid.addWidget(label, row_index, 0)
            grid.addWidget(value_widget, row_index, 1)

        self.error_label = QLabel()
        self.error_label.setObjectName("taskErrorMessage")
        self.error_label.setWordWrap(True)
        self.error_label.hide()

        button_row = QHBoxLayout()
        button_row.addStretch()

        log_button = QPushButton("원본 로그 보기")
        log_button.setObjectName("smallSecondaryButton")
        log_button.clicked.connect(self._open_raw_log)

        copy_log_button = QPushButton("로그 복사")
        copy_log_button.setObjectName("smallSecondaryButton")
        copy_log_button.clicked.connect(self._copy_raw_log)

        button_row.addWidget(log_button)
        button_row.addWidget(copy_log_button)

        layout.addLayout(grid)
        layout.addWidget(self.error_label)
        layout.addLayout(button_row)
        return frame

    def _update_status_ui(self, refresh_style: bool = True) -> None:
        status_value = self.task.status.value
        previous_status = self.property("taskStatus")
        status_changed = previous_status != status_value
        self.setProperty("taskStatus", status_value)
        self.status_pill.setProperty("taskStatus", status_value)
        self.progress_bar.setProperty("taskStatus", status_value)

        self.status_pill.setText(self.task.status_label)
        if self.task.status is DownloadStatus.ANALYZING:
            self.progress_bar.setRange(0, 0)
            self.progress_bar.setFormat("")
        else:
            self.progress_bar.setRange(0, 100)
            progress_format = "%p%"
            compact_size = self._compact_size_text()
            if compact_size:
                progress_format = f"%p% · {compact_size}"
            self.progress_bar.setFormat(progress_format)
            self.progress_bar.setValue(self.task.progress)
        self.detail_status.setText(self.task.status_label)
        self.detail_progress.setText(f"{self.task.progress}%")
        if (
            self.task.status is DownloadStatus.COMPLETED
            and self.task.file_size_bytes > 0
        ):
            self.detail_size_name.setText("파일 크기")
            self.detail_size.setText(self._format_bytes(self.task.file_size_bytes))
        else:
            self.detail_size_name.setText("받은 용량 / 전체 용량")
            self.detail_size.setText(self._detail_size_text())
        self.detail_speed.setText(self.task.speed)
        self.detail_eta.setText(self.task.eta)
        self.detail_phase.setText(self.task.phase_message or "-")
        self.detail_path.set_full_text(self.task.save_path)
        self.detail_output.set_full_text(self.task.output_file or "-")
        self.detail_url.set_full_text(self.task.url)

        self.error_label.setText(self.task.error_message)
        self.error_label.setVisible(bool(self.task.error_message))

        active_statuses = {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }
        is_stop_action = self.task.status in active_statuses
        if is_stop_action:
            self.retry_button.setObjectName("stopTaskButton")
            self.retry_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )
            self.retry_button.setText("중지")
            self.retry_button.setIcon(QIcon(str(STOP_ICON_PATH)))
            self.retry_button.setToolTip("현재 다운로드를 중지하고 대기열도 멈춤")
            self.retry_button.setEnabled(True)
        else:
            self.retry_button.setObjectName("taskActionButton")
            self.retry_button.setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly
            )
            self.retry_button.setText("")
            self.retry_button.setIcon(QIcon(str(RETRY_ICON_PATH)))
            self.retry_button.setToolTip("이 영상을 다시 다운로드")
            self.retry_button.setEnabled(
                self.task.status in {
                    DownloadStatus.COMPLETED,
                    DownloadStatus.FAILED,
                    DownloadStatus.STOPPED,
                }
            )

        if self._primary_action_is_stop != is_stop_action:
            self._primary_action_is_stop = is_stop_action
            self._refresh_style(self.retry_button)

        self._update_drag_handle_state()

        if refresh_style and status_changed:
            self._refresh_style(self)
            self._refresh_style(self.status_pill)
            self._refresh_style(self.progress_bar)

    def refresh_from_task(self) -> None:
        self.title_label.set_full_text(self.task.title)
        self.meta_label.set_full_text(self.task.meta_text)
        self._update_thumbnail()
        self._update_status_ui()

    def refresh_status_from_task(self) -> None:
        self.meta_label.set_full_text(self.task.meta_text)
        self._update_status_ui()

    def _compact_size_text(self) -> str:
        if (
            self.task.status is DownloadStatus.COMPLETED
            and self.task.file_size_bytes > 0
        ):
            return self._format_bytes(self.task.file_size_bytes)

        if self.task.downloaded_bytes <= 0 and self.task.total_bytes <= 0:
            return ""

        received = self._format_bytes(self.task.downloaded_bytes)
        if self.task.total_bytes > 0:
            total = self._format_bytes(self.task.total_bytes)
            return f"{received} / 약 {total}"
        return f"{received} / 계산 중"

    def _detail_size_text(self) -> str:
        if self.task.downloaded_bytes <= 0 and self.task.total_bytes <= 0:
            if self.task.status in {
                DownloadStatus.DOWNLOADING,
                DownloadStatus.POSTPROCESSING,
            }:
                return "계산 중"
            return "-"

        received = self._format_bytes(self.task.downloaded_bytes)
        if self.task.total_bytes > 0:
            total = self._format_bytes(self.task.total_bytes)
            return f"{received} / 약 {total}"
        return f"{received} / 계산 중"

    @staticmethod
    def _format_bytes(value: int) -> str:
        size = max(0, int(value))
        if size < 1024:
            return f"{size} B"

        amount = float(size)
        units = ("KB", "MB", "GB", "TB")
        for unit in units:
            amount /= 1024.0
            if amount < 1024.0 or unit == units[-1]:
                if amount >= 100:
                    return f"{amount:.0f} {unit}"
                if amount >= 10:
                    return f"{amount:.1f} {unit}"
                return f"{amount:.2f} {unit}"
        return f"{size} B"

    def set_index_number(self, index_number: int) -> None:
        self.index_number = index_number
        if not self.task.thumbnail_data:
            if self.task.status is DownloadStatus.ANALYZING:
                self.thumbnail_label.setText("확인 중")
            else:
                self.thumbnail_label.setText(f"VIDEO {index_number:02d}")

    def set_reordering_enabled(self, enabled: bool) -> None:
        self._reordering_enabled = bool(enabled)
        self._update_drag_handle_state()

    def _update_drag_handle_state(self) -> None:
        status_allows_drag = self.task.status not in {
            DownloadStatus.ANALYZING,
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }
        self.drag_handle.setEnabled(
            self._reordering_enabled and status_allows_drag
        )
        self.drag_handle.setCursor(
            Qt.CursorShape.OpenHandCursor
            if self.drag_handle.isEnabled()
            else Qt.CursorShape.ArrowCursor
        )
        self.drag_handle.setToolTip(
            "끌어서 다운로드 순서 변경"
            if self._reordering_enabled
            else "필터 보기에서는 다운로드 순서를 변경할 수 없습니다."
        )

    def set_highlighted(self, highlighted: bool) -> None:
        self.setProperty("highlighted", highlighted)
        self._refresh_style(self)

    def _update_thumbnail(self) -> None:
        started = perf_counter()
        load_ms = 0.0
        scale_ms = 0.0
        loaded = False

        pixmap = QPixmap()
        if self.task.thumbnail_data:
            load_started = perf_counter()
            loaded = pixmap.loadFromData(self.task.thumbnail_data)
            load_ms = (perf_counter() - load_started) * 1000.0

        if loaded:
            scale_started = perf_counter()
            scaled = pixmap.scaled(
                116,
                66,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            scale_ms = (perf_counter() - scale_started) * 1000.0
            self.thumbnail_label.setPixmap(scaled)
            self.thumbnail_label.setText("")
        else:
            self.thumbnail_label.setPixmap(QPixmap())
            if self.task.status is DownloadStatus.ANALYZING:
                self.thumbnail_label.setText("확인 중")
            else:
                self.thumbnail_label.setText(f"VIDEO {self.index_number:02d}")

        write_performance(
            "card.thumbnail",
            (perf_counter() - started) * 1000.0,
            bytes=len(self.task.thumbnail_data),
            loaded=loaded,
            load_ms=f"{load_ms:.3f}",
            scale_ms=f"{scale_ms:.3f}",
        )

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    @property
    def details_visible(self) -> bool:
        return self._details_visible

    def set_details_visible(self, visible: bool) -> None:
        if self._details_visible == visible:
            return

        self._details_visible = visible
        self.details_frame.setVisible(visible)
        self.adjustSize()
        self.updateGeometry()
        self.size_changed.emit()

    def toggle_details(self) -> None:
        self.set_details_visible(not self._details_visible)

    def _start_drag(self) -> None:
        if not self._reordering_enabled:
            return
        if self.task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }:
            return

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setData(
            TASK_MIME_TYPE,
            self.task.task_id.encode("utf-8"),
        )
        drag.setMimeData(mime_data)
        drag.setPixmap(self.grab())
        drag.setHotSpot(QPoint(28, 28))
        drag.exec(Qt.DropAction.MoveAction)

    def _copy_url(self) -> None:
        QApplication.clipboard().setText(self.task.url)
        self.message_requested.emit("영상 주소 복사 완료")

    def _primary_action(self) -> None:
        if self.task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }:
            self.stop_requested.emit(self.task.task_id)
        else:
            self.retry_requested.emit(self.task.task_id)

    def _open_raw_log(self) -> None:
        if not self.task.raw_log_path:
            self.message_requested.emit("아직 이 작업의 원본 로그가 없습니다.")
            return
        path = Path(self.task.raw_log_path)
        if not path.is_file():
            self.message_requested.emit("원본 로그 파일을 찾을 수 없습니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def _copy_raw_log(self) -> None:
        if not self.task.raw_log_path:
            self.message_requested.emit("아직 이 작업의 원본 로그가 없습니다.")
            return
        path = Path(self.task.raw_log_path)
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            self.message_requested.emit("원본 로그 읽기 실패")
            return
        QApplication.clipboard().setText(text)
        self.message_requested.emit("원본 로그 복사 완료")

    def _show_more_menu(self) -> None:
        menu = QMenu(self)
        open_action = menu.addAction("원본 페이지를 브라우저에서 열기")
        output_action = None
        if self.task.output_file:
            output_action = menu.addAction("완료 파일이 있는 폴더 열기")
        thumbnail_recovery_action = None
        subtitle_recovery_action = None
        recovery_available = (
            not self.task.audio_only
            and self.task.status in {
                DownloadStatus.COMPLETED,
                DownloadStatus.FAILED,
            }
        )
        if recovery_available:
            menu.addSeparator()
            thumbnail_recovery_action = menu.addAction("썸네일만 복구")
            thumbnail_recovery_action.setToolTip(
                "영상을 다시 다운로드하지 않고 원본 썸네일만 다시 확보해 영상에 넣습니다."
            )
            if self.task.subtitle_tracks:
                subtitle_recovery_action = menu.addAction("자막만 복구")
                subtitle_recovery_action.setToolTip(
                    "영상을 다시 다운로드하지 않고 이 작업에서 선택했던 자막만 다시 받아 복구합니다."
                )

        menu.addSeparator()
        path_action = menu.addAction("저장 위치 변경")
        path_action.setEnabled(
            self.task.status in {
                DownloadStatus.ANALYZING,
                DownloadStatus.QUEUED,
            }
        )
        path_action.setToolTip(
            "아직 다운로드를 시작하지 않은 작업에서만 저장 위치를 변경할 수 있습니다."
        )

        selected_action = menu.exec(
            self.more_button.mapToGlobal(self.more_button.rect().bottomLeft())
        )

        if selected_action is open_action:
            QDesktopServices.openUrl(QUrl(self.task.url))
            self.message_requested.emit("원본 페이지를 브라우저에서 열었습니다.")
        elif output_action is not None and selected_action is output_action:
            output_path = Path(self.task.output_file)
            folder = output_path.parent if output_path.parent.exists() else Path(self.task.save_path)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        elif (
            thumbnail_recovery_action is not None
            and selected_action is thumbnail_recovery_action
        ):
            self.thumbnail_recovery_requested.emit(self.task.task_id)
        elif (
            subtitle_recovery_action is not None
            and selected_action is subtitle_recovery_action
        ):
            self.subtitle_recovery_requested.emit(self.task.task_id)
        elif selected_action is path_action:
            selected_path = QFileDialog.getExistingDirectory(
                self,
                "저장 위치 선택",
                self.task.save_path,
            )
            if selected_path:
                self.task.save_path = selected_path
                self.detail_path.set_full_text(selected_path)
                self.path_changed.emit(self.task.task_id)

    def _handle_double_click(self) -> None:
        if self.task.status is not DownloadStatus.COMPLETED:
            return
        if not self.task.output_file:
            self.message_requested.emit("완료 파일 위치를 확인할 수 없습니다.")
            return
        output = Path(self.task.output_file)
        if not output.is_file():
            self.message_requested.emit("완료 파일이 이동되었거나 삭제된 것으로 보입니다.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output)))
