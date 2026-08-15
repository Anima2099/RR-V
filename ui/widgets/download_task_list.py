from __future__ import annotations

from time import perf_counter

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent, QDragMoveEvent, QDropEvent
from PySide6.QtWidgets import (
    QLayout,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from app.performance_log import PerformanceSpan, write_performance
from core.download_task import DownloadStatus, DownloadTask
from ui.dialogs.warm_dialogs import ask_warm_question
from ui.widgets.download_task_card import TASK_MIME_TYPE, DownloadTaskCard


class DownloadTaskList(QWidget):
    task_removed = Signal(str)
    order_changed = Signal(list)
    message_requested = Signal(str)
    card_expanded = Signal(str)
    retry_requested = Signal(str)
    stop_requested = Signal(str)
    path_changed = Signal(str)
    thumbnail_recovery_requested = Signal(str)
    subtitle_recovery_requested = Signal(str)

    def __init__(self, tasks: list[DownloadTask]) -> None:
        super().__init__()
        self.setObjectName("downloadTaskList")
        self.setAcceptDrops(True)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding,
            QSizePolicy.Policy.Preferred,
        )

        self._cards: list[DownloadTaskCard] = []
        self._drop_target: DownloadTaskCard | None = None
        self._geometry_refresh_pending = False
        self._failed_only = False

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 4, 12)
        self._layout.setSpacing(10)
        self._layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)

        for index, task in enumerate(tasks, start=1):
            self.add_task(task, index)

    @property
    def count(self) -> int:
        return len(self._cards)

    def add_task(
        self,
        task: DownloadTask,
        index_number: int | None = None,
        position: int | None = None,
    ) -> DownloadTaskCard:
        total_started = perf_counter()
        first_card = not self._cards
        if index_number is None:
            index_number = len(self._cards) + 1

        with PerformanceSpan(
            "task_list.card_construct",
            first_card=first_card,
            has_thumbnail=bool(task.thumbnail_data),
        ):
            card = DownloadTaskCard(task, index_number)

        connect_started = perf_counter()
        card.remove_requested.connect(self._remove_requested)
        card.message_requested.connect(self.message_requested)
        card.size_changed.connect(self._schedule_card_size_changed)
        card.details_toggle_requested.connect(self._toggle_card_details)
        card.retry_requested.connect(self.retry_requested)
        card.stop_requested.connect(self.stop_requested)
        card.path_changed.connect(self.path_changed)
        card.thumbnail_recovery_requested.connect(
            self.thumbnail_recovery_requested
        )
        card.subtitle_recovery_requested.connect(
            self.subtitle_recovery_requested
        )
        connect_ms = (perf_counter() - connect_started) * 1000.0

        insert_started = perf_counter()
        if position is None:
            self._cards.append(card)
            self._layout.addWidget(card)
        else:
            position = max(0, min(position, len(self._cards)))
            self._cards.insert(position, card)
            self._layout.insertWidget(position, card)
        self._apply_filter_to_card(card)
        card.set_reordering_enabled(not self._failed_only)
        insert_ms = (perf_counter() - insert_started) * 1000.0

        renumber_started = perf_counter()
        self._renumber_cards()
        renumber_ms = (perf_counter() - renumber_started) * 1000.0
        self._schedule_card_size_changed()

        write_performance(
            "task_list.add_task.total",
            (perf_counter() - total_started) * 1000.0,
            first_card=first_card,
            connect_ms=f"{connect_ms:.3f}",
            insert_ms=f"{insert_ms:.3f}",
            renumber_ms=f"{renumber_ms:.3f}",
            count=len(self._cards),
        )
        return card


    def refresh_task(self, task_id: str) -> None:
        card = self.card_for_task(task_id)
        if card is None:
            return
        with PerformanceSpan("task_list.refresh_task", task_id=task_id):
            card.refresh_from_task()
        self._apply_filter_to_card(card)
        self._schedule_card_size_changed()

    def refresh_task_status(self, task_id: str) -> None:
        card = self.card_for_task(task_id)
        if card is None:
            return
        card.refresh_status_from_task()
        self._apply_filter_to_card(card)
        self._schedule_card_size_changed()

    def set_failed_only(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if self._failed_only == enabled:
            return
        self._failed_only = enabled
        self.setAcceptDrops(not enabled)
        for card in self._cards:
            self._apply_filter_to_card(card)
            card.set_reordering_enabled(not enabled)
        self._clear_drop_target()
        self._schedule_card_size_changed()

    def _apply_filter_to_card(self, card: DownloadTaskCard) -> None:
        card.setVisible(
            not self._failed_only
            or card.task.status is DownloadStatus.FAILED
        )

    def remove_task(self, task_id: str, emit_signals: bool = True) -> None:
        card = self.card_for_task(task_id)
        if card is None:
            return
        self._cards.remove(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        self._renumber_cards()
        if emit_signals:
            self.task_removed.emit(task_id)
            self.order_changed.emit(self.task_ids())
        self._schedule_card_size_changed()

    def task_ids(self) -> list[str]:
        return [card.task.task_id for card in self._cards]

    def move_task_to_top(self, task_id: str) -> None:
        card = self.card_for_task(task_id)
        if card is None or (self._cards and self._cards[0] is card):
            return
        self._cards.remove(card)
        self._cards.insert(0, card)
        self._rebuild_layout()
        self._renumber_cards()
        self.order_changed.emit(self.task_ids())

    def card_for_task(self, task_id: str) -> DownloadTaskCard | None:
        return next(
            (card for card in self._cards if card.task.task_id == task_id),
            None,
        )

    def task_for_identity(self, identity_key: str) -> DownloadTask | None:
        card = next(
            (
                card
                for card in self._cards
                if card.task.identity_key == identity_key
            ),
            None,
        )
        return card.task if card is not None else None

    def focus_task(self, task_id: str) -> None:
        """현재 작업을 강조하고 보이는 위치로 옮기되 상세 정보는 열지 않는다."""
        card = self.card_for_task(task_id)
        if card is None:
            return

        for candidate in self._cards:
            candidate.set_highlighted(candidate is card)

        self.card_expanded.emit(task_id)
        QTimer.singleShot(1300, lambda: card.set_highlighted(False))

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if self._failed_only:
            event.ignore()
            return
        if event.mimeData().hasFormat(TASK_MIME_TYPE):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event: QDragMoveEvent) -> None:
        if self._failed_only:
            event.ignore()
            return
        source_id = self._source_id(event)
        if not source_id:
            event.ignore()
            return

        target_index = self._target_index(
            event.position().toPoint().y(),
            source_id,
        )
        self._show_drop_target(source_id, target_index)
        event.acceptProposedAction()

    def dragLeaveEvent(self, event: QDragLeaveEvent) -> None:
        self._clear_drop_target()
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        if self._failed_only:
            event.ignore()
            return
        source_id = self._source_id(event)
        if not source_id:
            event.ignore()
            return

        source_card = self.card_for_task(source_id)
        if source_card is None:
            event.ignore()
            return

        target_index = self._target_index(
            event.position().toPoint().y(),
            source_id,
        )
        self._cards.remove(source_card)
        target_index = max(0, min(target_index, len(self._cards)))
        target_index = max(self._pinned_count(), target_index)
        self._cards.insert(target_index, source_card)

        self._rebuild_layout()
        self._renumber_cards()
        self._clear_drop_target()
        self.order_changed.emit(self.task_ids())
        self.message_requested.emit("다운로드 순서 변경 완료")
        event.acceptProposedAction()

    def _toggle_card_details(self, task_id: str) -> None:
        selected_card = self.card_for_task(task_id)
        if selected_card is None:
            return

        should_open = not selected_card.details_visible

        # 상세 정보는 한 번에 하나만 펼친다.
        for card in self._cards:
            card.set_details_visible(card is selected_card and should_open)

        self._schedule_card_size_changed()

        if should_open:
            # 레이아웃이 새 높이를 계산한 뒤 스크롤 위치를 조정한다.
            QTimer.singleShot(0, lambda: self.card_expanded.emit(task_id))

    def _source_id(self, event) -> str:  # type: ignore[no-untyped-def]
        raw_data = event.mimeData().data(TASK_MIME_TYPE)
        try:
            return bytes(raw_data).decode("utf-8")
        except UnicodeDecodeError:
            return ""

    def _target_index(self, y_position: int, source_id: str) -> int:
        remaining_cards = [
            card for card in self._cards if card.task.task_id != source_id
        ]
        for index, card in enumerate(remaining_cards):
            if y_position < card.geometry().center().y():
                return index
        return len(remaining_cards)

    def _pinned_count(self) -> int:
        if (
            self._cards
            and self._cards[0].task.status in {
                DownloadStatus.DOWNLOADING,
                DownloadStatus.POSTPROCESSING,
            }
        ):
            return 1
        return 0

    def _show_drop_target(self, source_id: str, target_index: int) -> None:
        remaining_cards = [
            card for card in self._cards if card.task.task_id != source_id
        ]
        target_index = max(self._pinned_count(), target_index)
        target_card = (
            remaining_cards[target_index]
            if target_index < len(remaining_cards)
            else None
        )

        if target_card is self._drop_target:
            return

        self._clear_drop_target()
        self._drop_target = target_card

        if self._drop_target is not None:
            self._drop_target.setProperty("dropTarget", True)
            self._refresh_style(self._drop_target)
        else:
            self.setProperty("dropAtEnd", True)
            self._refresh_style(self)

    def _clear_drop_target(self) -> None:
        if self._drop_target is not None:
            self._drop_target.setProperty("dropTarget", False)
            self._refresh_style(self._drop_target)
            self._drop_target = None

        self.setProperty("dropAtEnd", False)
        self._refresh_style(self)

    @staticmethod
    def _refresh_style(widget: QWidget) -> None:
        style = widget.style()
        style.unpolish(widget)
        style.polish(widget)
        widget.update()

    def _renumber_cards(self) -> None:
        for index, card in enumerate(self._cards, start=1):
            card.set_index_number(index)

    def _rebuild_layout(self) -> None:
        for card in self._cards:
            self._layout.removeWidget(card)
        for card in self._cards:
            self._layout.addWidget(card)
        self._schedule_card_size_changed()

    def _schedule_card_size_changed(self) -> None:
        if self._geometry_refresh_pending:
            return
        self._geometry_refresh_pending = True
        QTimer.singleShot(0, self._card_size_changed)

    def _card_size_changed(self) -> None:
        self._geometry_refresh_pending = False
        started = perf_counter()
        self._layout.invalidate()
        self._layout.activate()
        self.adjustSize()
        self.updateGeometry()
        write_performance(
            "task_list.geometry_refresh",
            (perf_counter() - started) * 1000.0,
            count=len(self._cards),
        )

    def _remove_requested(self, task_id: str) -> None:
        card = self.card_for_task(task_id)
        if card is None:
            return

        if card.task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
        }:
            if not ask_warm_question(
                self,
                "다운로드 중인 작업 삭제",
                "현재 다운로드를 중지하고 목록에서 삭제하시겠습니까?",
                yes_text="중지하고 삭제",
                no_text="취소",
            ):
                return

        self._cards.remove(card)
        self._layout.removeWidget(card)
        card.deleteLater()
        self._renumber_cards()
        self.task_removed.emit(task_id)
        self.order_changed.emit(self.task_ids())
        self.message_requested.emit("목록에서 작업 삭제됨")
        self._schedule_card_size_changed()
