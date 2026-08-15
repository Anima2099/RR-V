from __future__ import annotations

from pathlib import Path
import re
from typing import Iterable

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QTextCursor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from app.download_log import write_download_event
from app.settings_store import get_settings
from app.url_list_io import (
    extract_urls as extract_url_list,
    format_source_url_list,
    merge_urls,
    probable_collection_urls,
    read_text_file,
    write_text_file,
)
from core.batch_entry import BatchAnalysisResult, BatchEntry
from workers.batch_analysis_worker import BatchAnalysisWorker


def _natural_sort_key(text: str) -> tuple[tuple[int, object], ...]:
    parts = re.split(r"(\d+)", str(text or "").casefold())
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part)
        for part in parts
        if part
    )


class BatchUrlInput(QPlainTextEdit):
    urls_paste_requested = Signal(object)
    text_files_dropped = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)

    def keyPressEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if event.matches(QKeySequence.StandardKey.Paste):
            urls = extract_url_list(QApplication.clipboard().text())
            if urls:
                self.urls_paste_requested.emit(urls)
                event.accept()
                return
        super().keyPressEvent(event)

    def dragEnterEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._txt_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        if self._txt_paths(event.mimeData()):
            event.acceptProposedAction()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        paths = self._txt_paths(event.mimeData())
        if paths:
            self.text_files_dropped.emit(paths)
            event.acceptProposedAction()
            return
        super().dropEvent(event)

    @staticmethod
    def _txt_paths(mime_data) -> list[str]:  # type: ignore[no-untyped-def]
        if not mime_data.hasUrls():
            return []
        paths: list[str] = []
        for url in mime_data.urls():
            local_path = url.toLocalFile()
            if local_path and Path(local_path).suffix.lower() == ".txt":
                paths.append(local_path)
        return paths


class BatchAddDialog(QDialog):
    def __init__(
        self,
        initial_text: str = "",
        *,
        initial_status: str = "",
        existing_identity_keys: Iterable[str] = (),
        existing_urls: Iterable[str] = (),
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("warmDialog")
        self.setWindowTitle("재생목록 · 여러 주소 추가")
        self.setModal(True)
        self.resize(820, 620)
        self.setMinimumSize(700, 500)

        self.selected_entries: tuple[BatchEntry, ...] = ()
        self.direct_urls: tuple[str, ...] = ()
        self._settings = get_settings()
        self._saving_column_widths = False
        self._worker: BatchAnalysisWorker | None = None
        self._updating_items = False
        self._busy = False
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder
        self._existing_identity_keys = {
            value.strip().lower() for value in existing_identity_keys if value.strip()
        }
        self._existing_urls = {
            value.strip().lower() for value in existing_urls if value.strip()
        }

        layout = QVBoxLayout(self)
        layout.setContentsMargins(22, 20, 22, 20)
        layout.setSpacing(12)

        title = QLabel("재생목록이나 여러 영상 주소를 한꺼번에 추가합니다.")
        title.setObjectName("dialogTitle")
        description = QLabel(
            "개별 영상 주소는 바로 추가할 수 있고, 재생목록은 목록 확인 후 원하는 영상만 선택할 수 있습니다."
        )
        description.setObjectName("emptyDescription")
        description.setWordWrap(True)

        self.url_input = BatchUrlInput()
        self.url_input.setObjectName("batchUrlInput")
        self.url_input.setPlaceholderText(
            "https://www.youtube.com/playlist?list=...\n"
            "https://www.youtube.com/watch?v=...\n"
            "https://www.youtube.com/watch?v=..."
        )
        self.url_input.setPlainText(initial_text.strip())
        self.url_input.setMaximumHeight(130)
        self.url_input.setToolTip(
            "영상 주소를 붙여넣거나 RR-V에서 내보낸 TXT 파일을 이 입력란에 드래그 앤 드롭할 수 있습니다."
        )

        input_buttons = QHBoxLayout()
        input_buttons.setSpacing(8)

        self.import_txt_button = QPushButton("TXT 불러오기")
        self.import_txt_button.setObjectName("secondaryButton")
        self.import_txt_button.setToolTip("TXT 파일에서 영상·재생목록 주소를 찾아 입력란에 추가")
        self.import_txt_button.clicked.connect(self._import_txt_urls)

        self.export_txt_button = QPushButton("주소 TXT 저장")
        self.export_txt_button.setObjectName("secondaryButton")
        self.export_txt_button.setToolTip("현재 입력란에서 찾은 주소를 TXT 파일로 저장")
        self.export_txt_button.clicked.connect(self._export_txt_urls)

        self.paste_button = QPushButton("클립보드에서 추가")
        self.paste_button.setObjectName("secondaryButton")
        self.paste_button.setToolTip("클립보드의 주소를 기존 입력 내용 뒤에 추가하고 중복은 제외")
        self.paste_button.clicked.connect(self._paste_clipboard_urls)

        self.url_count_label = QLabel("주소 0개")
        self.url_count_label.setObjectName("mutedText")

        self.direct_add_button = QPushButton("빠른 추가")
        self.direct_add_button.setObjectName("quickAddTextButton")
        self.direct_add_button.setFixedWidth(96)
        self.direct_add_button.setFixedHeight(46)
        self.direct_add_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.direct_add_button.setToolTip(
            "입력한 개별 영상 주소를 목록 확인 없이 기본 프리셋으로 다운로드 목록에 바로 추가"
        )
        self.direct_add_button.clicked.connect(self._accept_direct_urls)

        self.inspect_button = QPushButton("목록 확인")
        self.inspect_button.setObjectName("primaryButton")
        self.inspect_button.clicked.connect(self._inspect_sources)

        input_buttons.addWidget(self.import_txt_button)
        input_buttons.addWidget(self.export_txt_button)
        input_buttons.addWidget(self.paste_button)
        input_buttons.addWidget(self.url_count_label)
        input_buttons.addStretch()
        input_buttons.addWidget(self.direct_add_button)
        input_buttons.addWidget(self.inspect_button)

        self.status_label = QLabel(
            initial_status.strip()
            or "주소를 입력한 뒤 빠른 추가 또는 목록 확인을 사용해 주세요."
        )
        self.status_label.setObjectName("dialogStatusText")
        self.status_label.setWordWrap(True)

        self.tree = QTreeWidget()
        self.tree.setObjectName("batchEntryTree")
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(("영상", "채널", "길이", "출처"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setUniformRowHeights(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.itemChanged.connect(self._item_changed)

        self.tree.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )

        header = self.tree.header()
        header.setMinimumSectionSize(60)
        header.setStretchLastSection(False)
        for index in range(self.tree.columnCount()):
            header.setSectionResizeMode(
                index,
                QHeaderView.ResizeMode.Interactive,
            )
        header.setSectionsClickable(True)
        header.setSortIndicatorShown(False)
        header.sectionClicked.connect(self._sort_by_header)
        header.sectionDoubleClicked.connect(self.tree.resizeColumnToContents)
        header.sectionResized.connect(self._save_column_widths)
        header_item = self.tree.headerItem()
        header_item.setToolTip(0, "클릭하여 영상 제목을 오름차순/내림차순으로 정렬")
        header_item.setToolTip(1, "클릭하여 채널 이름을 오름차순/내림차순으로 정렬")
        header_item.setToolTip(2, "클릭하여 영상 길이를 짧은 순/긴 순으로 정렬")
        self._restore_column_widths()

        selection_row = QHBoxLayout()
        select_all_button = QPushButton("전체 선택")
        select_all_button.setObjectName("smallSecondaryButton")
        select_all_button.clicked.connect(lambda: self._set_all_checked(True))
        clear_all_button = QPushButton("전체 해제")
        clear_all_button.setObjectName("smallSecondaryButton")
        clear_all_button.clicked.connect(lambda: self._set_all_checked(False))

        self.selection_label = QLabel("선택 0개")
        self.selection_label.setObjectName("mutedText")
        selection_row.addWidget(select_all_button)
        selection_row.addWidget(clear_all_button)
        selection_row.addStretch()
        selection_row.addWidget(self.selection_label)

        action_row = QHBoxLayout()
        action_row.addStretch()
        cancel_button = QPushButton("취소")
        cancel_button.setObjectName("secondaryButton")
        cancel_button.clicked.connect(self.reject)

        self.add_button = QPushButton("선택 항목 추가")
        self.add_button.setObjectName("primaryButton")
        self.add_button.setEnabled(False)
        self.add_button.clicked.connect(self._accept_selected)
        action_row.addWidget(cancel_button)
        action_row.addWidget(self.add_button)

        layout.addWidget(title)
        layout.addWidget(description)
        layout.addWidget(self.url_input)
        layout.addLayout(input_buttons)
        layout.addWidget(self.status_label)
        layout.addWidget(self.tree, 1)
        layout.addLayout(selection_row)
        layout.addLayout(action_row)

        self.url_input.urls_paste_requested.connect(self._append_pasted_urls)
        self.url_input.text_files_dropped.connect(self._import_dropped_txt_files)
        self.url_input.textChanged.connect(self._refresh_url_count)
        self._refresh_url_count()

        if initial_text.strip():
            QTimer.singleShot(0, self.url_input.selectAll)

    def _restore_column_widths(self) -> None:
        defaults = [390, 160, 75, 125]
        raw = self._settings.value("batch_add/column_widths", defaults)
        if not isinstance(raw, (list, tuple)):
            raw = defaults

        widths: list[int] = []
        for index, default in enumerate(defaults):
            try:
                widths.append(max(60, int(raw[index])))
            except (IndexError, TypeError, ValueError):
                widths.append(default)

        self._saving_column_widths = True
        try:
            header = self.tree.header()
            for index, width in enumerate(widths):
                header.resizeSection(index, width)
        finally:
            self._saving_column_widths = False

    def _save_column_widths(self, *_args) -> None:  # type: ignore[no-untyped-def]
        if self._saving_column_widths:
            return
        header = self.tree.header()
        self._settings.setValue(
            "batch_add/column_widths",
            [
                header.sectionSize(index)
                for index in range(self.tree.columnCount())
            ],
        )
        self._settings.sync()

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop_worker()
        super().closeEvent(event)

    def reject(self) -> None:
        self._stop_worker()
        super().reject()

    def _paste_clipboard_urls(self) -> None:
        urls = self.extract_urls(QApplication.clipboard().text())
        if not urls:
            self.status_label.setText("클립보드에서 주소를 찾지 못했습니다.")
            return
        self._append_urls(urls, source_label="클립보드")

    def _append_pasted_urls(self, urls: object) -> None:
        if not isinstance(urls, (list, tuple)):
            return
        normalized = [str(url) for url in urls]
        self._append_urls(normalized, source_label="클립보드")

    def _append_urls(self, incoming_urls: Iterable[str], *, source_label: str) -> None:
        existing_urls = self.extract_urls(self.url_input.toPlainText())
        merged_urls, duplicate_count = merge_urls(existing_urls, incoming_urls)
        added_count = len(merged_urls) - len(existing_urls)

        if added_count:
            self._set_input_urls(merged_urls)

        if added_count:
            message = f"{source_label}에서 주소 {added_count}개를 추가했습니다."
        else:
            message = f"{source_label}의 주소가 모두 이미 입력되어 있습니다."
        if duplicate_count:
            message += f" 중복 {duplicate_count}개는 제외했습니다."
        self.status_label.setText(message)

    def _set_input_urls(self, urls: Iterable[str]) -> None:
        self.url_input.setPlainText("\n".join(urls))
        cursor = self.url_input.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.url_input.setTextCursor(cursor)

    def _import_txt_urls(self) -> None:
        file_path, _selected_filter = QFileDialog.getOpenFileName(
            self,
            "일괄 추가 TXT 불러오기",
            str(self._default_text_directory()),
            "텍스트 파일 (*.txt);;모든 파일 (*)",
        )
        if not file_path:
            return
        self._import_txt_files([file_path])

    def _import_dropped_txt_files(self, paths: object) -> None:
        if not isinstance(paths, (list, tuple)):
            return
        normalized = [str(path) for path in paths if str(path).strip()]
        if normalized:
            self._import_txt_files(normalized, dropped=True)

    def _import_txt_files(self, paths: Iterable[str], *, dropped: bool = False) -> None:
        imported_urls: list[str] = []
        read_errors: list[str] = []
        file_count = 0

        for raw_path in paths:
            path = str(raw_path).strip()
            if not path:
                continue
            file_count += 1
            try:
                text = read_text_file(path)
            except OSError as error:
                read_errors.append(f"{path}: {error}")
                continue
            file_urls = self.extract_urls(text)
            imported_urls, _duplicates = merge_urls(imported_urls, file_urls)

        if not imported_urls:
            if read_errors:
                self.status_label.setText("TXT 파일을 읽지 못했습니다.")
                self.status_label.setToolTip("\n".join(read_errors))
            else:
                self.status_label.setText("TXT 파일에서 영상 주소를 찾지 못했습니다.")
            return

        existing_urls = self.extract_urls(self.url_input.toPlainText())
        merged_urls, duplicate_count = merge_urls(existing_urls, imported_urls)
        added_count = len(merged_urls) - len(existing_urls)
        if added_count:
            self._set_input_urls(merged_urls)

        source = "드롭한 TXT" if dropped else "TXT"
        message = f"{source} {file_count}개에서 주소 {added_count}개를 추가했습니다."
        if duplicate_count:
            message += f" 중복 {duplicate_count}개는 제외했습니다."
        if read_errors:
            message += f" 읽지 못한 파일 {len(read_errors)}개가 있습니다."
            self.status_label.setToolTip("\n".join(read_errors))
        else:
            self.status_label.setToolTip("")
        self.status_label.setText(message)

    def _export_txt_urls(self) -> None:
        urls = self.extract_urls(self.url_input.toPlainText())
        if not urls:
            self.status_label.setText("저장할 영상 또는 재생목록 주소가 없습니다.")
            return

        default_path = self._default_text_directory() / "RR-V_일괄_추가_주소.txt"
        file_path, _selected_filter = QFileDialog.getSaveFileName(
            self,
            "일괄 추가 주소 TXT 저장",
            str(default_path),
            "텍스트 파일 (*.txt);;모든 파일 (*)",
        )
        if not file_path:
            return
        destination = Path(file_path)
        if destination.suffix.lower() != ".txt":
            destination = destination.with_suffix(".txt")
        try:
            write_text_file(destination, format_source_url_list(urls))
        except OSError as error:
            self.status_label.setText(f"TXT 파일을 저장하지 못했습니다: {error}")
            return
        self.status_label.setText(f"주소 {len(urls)}개를 TXT로 저장했습니다.")

    @staticmethod
    def _default_text_directory() -> Path:
        downloads = Path.home() / "Downloads"
        return downloads if downloads.is_dir() else Path.home()

    def _refresh_url_count(self) -> None:
        count = len(self.extract_urls(self.url_input.toPlainText()))
        self.url_count_label.setText(f"주소 {count}개")
        if not self._busy:
            self.export_txt_button.setEnabled(count > 0)
            self.direct_add_button.setEnabled(count > 0)
            self.inspect_button.setEnabled(count > 0)

    def _accept_direct_urls(self) -> None:
        urls = self.extract_urls(self.url_input.toPlainText())
        if not urls:
            self.status_label.setText("바로 추가할 개별 영상 주소를 입력해 주세요.")
            self.url_input.setFocus()
            return
        if self._worker is not None and self._worker.isRunning():
            return

        collection_urls = probable_collection_urls(urls)
        if collection_urls:
            self.status_label.setText(
                f"재생목록 정보가 포함되었거나 여러 영상을 가리킬 수 있는 주소 {len(collection_urls)}개가 있습니다. "
                "'목록 확인'을 사용해 원하는 영상만 선택해 주세요."
            )
            self.status_label.setToolTip("\n".join(collection_urls))
            return

        self.status_label.setToolTip("")
        self.selected_entries = ()
        self.direct_urls = tuple(urls)
        write_download_event("batch.direct_add_accepted", sources=len(urls))
        self.accept()

    def _sort_by_header(self, column: int) -> None:
        if column not in (0, 1, 2):
            return

        if self._sort_column == column:
            self._sort_order = (
                Qt.SortOrder.DescendingOrder
                if self._sort_order == Qt.SortOrder.AscendingOrder
                else Qt.SortOrder.AscendingOrder
            )
        else:
            self._sort_column = column
            self._sort_order = Qt.SortOrder.AscendingOrder

        header = self.tree.header()
        header.setSortIndicatorShown(True)
        header.setSortIndicator(column, self._sort_order)
        self._apply_current_sort()

    def _apply_current_sort(self) -> None:
        if self._sort_column not in (0, 1, 2):
            return

        items = [
            self.tree.takeTopLevelItem(0)
            for _index in range(self.tree.topLevelItemCount())
        ]
        reverse = self._sort_order == Qt.SortOrder.DescendingOrder

        if self._sort_column == 2:
            known: list[QTreeWidgetItem] = []
            unknown: list[QTreeWidgetItem] = []
            for item in items:
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(entry, BatchEntry) and entry.duration_seconds is not None:
                    known.append(item)
                else:
                    unknown.append(item)
            known.sort(
                key=lambda item: int(
                    item.data(0, Qt.ItemDataRole.UserRole).duration_seconds or 0
                ),
                reverse=reverse,
            )
            items = [*known, *unknown]
        else:
            def text_key(item: QTreeWidgetItem) -> tuple[tuple[int, object], ...]:
                entry = item.data(0, Qt.ItemDataRole.UserRole)
                if not isinstance(entry, BatchEntry):
                    return ()
                value = entry.title if self._sort_column == 0 else entry.uploader
                return _natural_sort_key(value)

            items.sort(key=text_key, reverse=reverse)

        self._updating_items = True
        try:
            self.tree.addTopLevelItems(items)
        finally:
            self._updating_items = False

    def _inspect_sources(self) -> None:
        urls = self.extract_urls(self.url_input.toPlainText())
        if not urls:
            self.status_label.setText("확인할 영상 또는 재생목록 주소를 입력해 주세요.")
            self.url_input.setFocus()
            return
        if self._worker is not None and self._worker.isRunning():
            return

        self._clear_results()
        self._set_busy(True)
        self.status_label.setText(f"주소 {len(urls)}개의 목록을 준비 중…")
        write_download_event("batch.inspect_started", sources=len(urls))

        worker = BatchAnalysisWorker(urls)
        self._worker = worker
        worker.status_changed.connect(self.status_label.setText)
        worker.analysis_succeeded.connect(self._analysis_succeeded)
        worker.analysis_failed.connect(self._analysis_failed)
        worker.analysis_cancelled.connect(self._analysis_cancelled)
        worker.finished.connect(self._worker_finished)
        worker.start()

    def _analysis_succeeded(self, result: BatchAnalysisResult) -> None:
        write_download_event(
            "batch.inspect_completed",
            sources=result.source_count,
            entries=len(result.entries),
            errors=len(result.errors),
        )
        self._updating_items = True
        duplicate_count = 0
        try:
            for entry in result.entries:
                is_duplicate = (
                    entry.identity_key.lower() in self._existing_identity_keys
                    or entry.webpage_url.strip().lower() in self._existing_urls
                )
                if is_duplicate:
                    duplicate_count += 1

                item = QTreeWidgetItem(
                    (
                        entry.title,
                        entry.uploader,
                        entry.duration_text,
                        entry.source_title or "개별 영상",
                    )
                )
                item.setFlags(
                    item.flags()
                    | Qt.ItemFlag.ItemIsUserCheckable
                    | Qt.ItemFlag.ItemIsSelectable
                    | Qt.ItemFlag.ItemIsEnabled
                )
                item.setCheckState(
                    0,
                    Qt.CheckState.Unchecked if is_duplicate else Qt.CheckState.Checked,
                )
                item.setData(0, Qt.ItemDataRole.UserRole, entry)
                tooltip_lines = [entry.title, entry.webpage_url]
                if is_duplicate:
                    tooltip_lines.append("기존 다운로드 목록에 이미 있는 항목")
                item.setToolTip(0, "\n".join(tooltip_lines))
                self.tree.addTopLevelItem(item)
        finally:
            self._updating_items = False

        parts = [f"영상 {len(result.entries)}개를 찾았습니다."]
        if duplicate_count:
            parts.append(f"기존 목록과 겹치는 후보 {duplicate_count}개는 선택 해제 상태로 유지했습니다.")
        if result.errors:
            parts.append(f"읽지 못한 주소 {len(result.errors)}개가 있습니다.")
            error_detail = "\n\n".join(
                f"{error.source_url}\n{error.message}\n{error.detail}".strip()
                for error in result.errors
            )
            self.status_label.setToolTip(error_detail)
        else:
            self.status_label.setToolTip("")

        if not result.entries:
            parts.append("추가할 수 있는 영상을 찾지 못했습니다.")
        self.status_label.setText(" ".join(parts))
        self._apply_current_sort()
        self._refresh_selection_count()

    def _analysis_failed(self, message: str, detail: str) -> None:
        write_download_event(
            "batch.inspect_failed",
            message=message,
            detail=detail[:800],
        )
        self.status_label.setText(message)
        self.status_label.setToolTip(detail)

    def _analysis_cancelled(self, message: str) -> None:
        write_download_event("batch.inspect_cancelled", message=message)
        self.status_label.setText(message)

    def _worker_finished(self) -> None:
        worker = self._worker
        self._worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_busy(False)
        self._refresh_selection_count()

    def _stop_worker(self) -> None:
        worker = self._worker
        if worker is None:
            return
        if worker.isRunning():
            worker.cancel()
            worker.wait(3000)
        self._worker = None
        worker.deleteLater()

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        count = len(self.extract_urls(self.url_input.toPlainText()))
        self.url_input.setEnabled(not busy)
        self.import_txt_button.setEnabled(not busy)
        self.export_txt_button.setEnabled(not busy and count > 0)
        self.paste_button.setEnabled(not busy)
        self.direct_add_button.setEnabled(not busy and count > 0)
        self.inspect_button.setEnabled(not busy and count > 0)
        self.add_button.setEnabled(not busy and self._checked_count() > 0)

    def _clear_results(self) -> None:
        self._updating_items = True
        try:
            self.tree.clear()
        finally:
            self._updating_items = False
        self.selection_label.setText("선택 0개")
        self.add_button.setEnabled(False)
        self.status_label.setToolTip("")

    def _item_changed(self, _item: QTreeWidgetItem, _column: int) -> None:
        if not self._updating_items:
            self._refresh_selection_count()

    def _set_all_checked(self, checked: bool) -> None:
        self._updating_items = True
        try:
            state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
            for index in range(self.tree.topLevelItemCount()):
                self.tree.topLevelItem(index).setCheckState(0, state)
        finally:
            self._updating_items = False
        self._refresh_selection_count()

    def _checked_count(self) -> int:
        return sum(
            self.tree.topLevelItem(index).checkState(0) == Qt.CheckState.Checked
            for index in range(self.tree.topLevelItemCount())
        )

    def _refresh_selection_count(self) -> None:
        selected_count = self._checked_count()
        total_count = self.tree.topLevelItemCount()
        self.selection_label.setText(f"선택 {selected_count}개 / 전체 {total_count}개")
        busy = self._worker is not None and self._worker.isRunning()
        self.add_button.setEnabled(not busy and selected_count > 0)

    def _accept_selected(self) -> None:
        entries: list[BatchEntry] = []
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.checkState(0) != Qt.CheckState.Checked:
                continue
            entry = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(entry, BatchEntry):
                entries.append(entry)
        if not entries:
            self.status_label.setText("추가할 영상을 하나 이상 선택해 주세요.")
            return
        self.selected_entries = tuple(entries)
        write_download_event("batch.selection_accepted", selected=len(entries))
        self.accept()

    @staticmethod
    def extract_urls(text: str) -> list[str]:
        return extract_url_list(text)
