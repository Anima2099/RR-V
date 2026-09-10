from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.chapter_preferences import load_delete_original_after_split
from app.download_preferences import load_download_preferences
from app.download_log import write_download_event
from core.download_task import DownloadStatus, DownloadTask, remove_failed_tasks
from services.partial_download_cleanup import (
    PartialCleanupResult,
    cleanup_partial_download_files,
    find_partial_download_files,
    partial_cleanup_scan_diagnostics,
    should_offer_partial_cleanup,
)
from services.ytdlp_service import YtDlpService
from ui.dialogs.warm_dialogs import ask_warm_question
from ui.pages.download_page import DownloadPage as _BaseDownloadPage
from ui.widgets.chapter_preview_panel import PreviewPanel


_PARTIAL_CLEANUP_RETRY_DELAYS_MS = (0, 250, 500, 750)


class DownloadPage(_BaseDownloadPage):
    """기존 DownloadPage에 1.4 챕터 UX와 안전한 목록 정리 동작을 얹는다."""

    def __init__(self) -> None:
        self._pending_partial_cleanup: dict[str, DownloadTask] = {}
        super().__init__()

    def _create_list_page(self) -> QWidget:
        page = super()._create_list_page()

        self.clear_failed_button = QPushButton("실패 삭제")
        self.clear_failed_button.setObjectName("queueRetryButton")
        self.clear_failed_button.setToolTip(
            "실패한 항목을 목록에서 모두 제거합니다. 다운로드 파일은 삭제하지 않습니다."
        )
        self.clear_failed_button.clicked.connect(self._remove_failed_tasks)

        filter_row = self.list_filter_bar.layout()
        if filter_row is not None:
            retry_index = filter_row.indexOf(self.retry_all_failed_button)
            if retry_index >= 0:
                filter_row.insertWidget(retry_index, self.clear_failed_button)
            else:
                filter_row.addWidget(self.clear_failed_button)
        return page

    def _create_editor_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        header = QHBoxLayout()
        title = QLabel("영상 정보와 다운로드 설정")
        title.setObjectName("sectionTitle")

        back_button = QPushButton("목록으로 돌아가기")
        back_button.setObjectName("secondaryButton")
        back_button.clicked.connect(self._back_to_list)

        header.addWidget(title)
        header.addStretch()
        header.addWidget(back_button)
        layout.addLayout(header)

        self.preview_panel = PreviewPanel()
        self.preview_panel.cancel_requested.connect(self._back_to_list)
        self.preview_panel.task_requested.connect(self._create_task_from_preview)

        self.preview_scroll = QScrollArea()
        self.preview_scroll.setWidgetResizable(True)
        self.preview_scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        self.preview_scroll.setWidget(self.preview_panel)
        layout.addWidget(self.preview_scroll, 1)
        return page

    def _create_quick_placeholder(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        task = super()._create_quick_placeholder(*args, **kwargs)
        try:
            preferences = load_download_preferences()
            task.split_chapters = bool(
                preferences.split_chapters and not task.audio_only
            )
            task.sponsorblock_chapters = bool(
                preferences.sponsorblock_chapters
                and not task.audio_only
                and YtDlpService.is_youtube_url(task.url)
            )
            task.delete_original_after_split = bool(
                task.split_chapters
                and load_delete_original_after_split(preferences.preset_id)
            )
            self.task_list.refresh_task(task.task_id)
        except Exception:
            pass
        return task

    def _complete_quick_task(self, *args, **kwargs) -> None:  # type: ignore[no-untyped-def]
        task_id = self._active_quick_task_id
        super()._complete_quick_task(*args, **kwargs)

        task = self._task_by_id(task_id)
        if task is None:
            return
        try:
            preferences = load_download_preferences()
            task.split_chapters = bool(
                preferences.split_chapters and not task.audio_only
            )
            task.sponsorblock_chapters = bool(
                preferences.sponsorblock_chapters
                and not task.audio_only
                and YtDlpService.is_youtube_url(task.url)
            )
            task.delete_original_after_split = bool(
                task.split_chapters
                and load_delete_original_after_split(preferences.preset_id)
            )
            self.task_list.refresh_task(task.task_id)
            self._schedule_queue_save()
        except Exception:
            pass

    def _create_task_from_preview(self, start_immediately: bool) -> None:
        before_ids = {task.task_id for task in self.tasks}
        try:
            options = self.preview_panel.selected_options()
            desired_split = bool(options.get("split_chapters", False))
            desired_sponsorblock = bool(
                options.get("sponsorblock_chapters", False)
            )
            desired_delete = bool(
                desired_split and options.get("delete_original_after_split", False)
            )
        except Exception:
            desired_split = False
            desired_sponsorblock = False
            desired_delete = False

        super()._create_task_from_preview(start_immediately)

        created = next(
            (task for task in self.tasks if task.task_id not in before_ids),
            None,
        )
        if created is None:
            return

        created.split_chapters = bool(desired_split and not created.audio_only)
        created.sponsorblock_chapters = bool(
            desired_sponsorblock
            and not created.audio_only
            and YtDlpService.is_youtube_url(created.url)
        )
        created.delete_original_after_split = bool(
            created.split_chapters and desired_delete
        )
        self.task_list.refresh_task(created.task_id)
        self._schedule_queue_save()

    def _download_succeeded(
        self,
        task_id: str,
        output_file: str,
        raw_log_path: str,
    ) -> None:
        task = self._task_by_id(task_id)
        chapter_completion = ""
        if task is not None and task.split_chapters:
            chapter_completion = task.phase_message

        super()._download_succeeded(task_id, output_file, raw_log_path)

        task = self._task_by_id(task_id)
        if task is None:
            return

        if chapter_completion.startswith("챕터"):
            task.phase_message = chapter_completion

        delete_succeeded = (
            task.split_chapters
            and task.delete_original_after_split
            and "원본 삭제" in chapter_completion
            and "원본 삭제 실패" not in chapter_completion
        )
        if delete_succeeded and output_file:
            representative = Path(output_file)
            try:
                siblings = tuple(
                    path for path in representative.parent.iterdir() if path.is_file()
                )
                total_size = sum(max(0, path.stat().st_size) for path in siblings)
            except OSError:
                total_size = 0
            if total_size > 0:
                task.file_size_bytes = total_size
                task.downloaded_bytes = total_size
                task.total_bytes = total_size
                task.total_bytes_estimated = False

        self.task_list.refresh_task_status(task_id)
        self._schedule_queue_save()

    def _remove_failed_tasks(self) -> None:
        if self._recovery_running():
            self.toast.show_message(
                "썸네일/자막 복구가 끝난 뒤 실패 작업을 정리해 주세요."
            )
            return

        failed_count = sum(
            task.status is DownloadStatus.FAILED
            for task in self.tasks
        )
        if not failed_count:
            self.toast.show_message("삭제할 실패 항목이 없습니다.")
            return

        confirmed = ask_warm_question(
            self,
            "실패 항목 삭제",
            f"실패한 항목 {failed_count}개를 목록에서 삭제할까요?\n"
            "다운로드된 파일은 삭제되지 않습니다.",
            yes_text="삭제",
            no_text="취소",
        )
        if not confirmed:
            return

        self.tasks, failed_ids = remove_failed_tasks(self.tasks)
        for task_id in failed_ids:
            self.task_list.remove_task(task_id, emit_signals=False)

        self._refresh_list_state()
        self._save_queue_now()
        self.toast.show_message(
            f"실패한 항목 {len(failed_ids)}개를 목록에서 삭제했습니다."
        )

    def _refresh_list_state(self) -> None:
        super()._refresh_list_state()
        if not hasattr(self, "clear_failed_button"):
            return

        failed_count = sum(
            task.status is DownloadStatus.FAILED
            for task in self.tasks
        )
        recovery_running = self._recovery_running()
        self.clear_failed_button.setText(
            f"실패 삭제 {failed_count}" if failed_count else "실패 삭제"
        )
        self.clear_failed_button.setEnabled(
            failed_count > 0 and not recovery_running
        )
        self.clear_failed_button.setToolTip(
            (
                f"실패한 항목 {failed_count}개를 목록에서 삭제합니다. 다운로드 파일은 삭제하지 않습니다."
                if failed_count
                else "현재 삭제할 실패 항목이 없습니다."
            )
        )

    def _task_removed(self, task_id: str) -> None:
        task = self._task_by_id(task_id)
        active = self.controller.active_download_task_id == task_id
        cleanup_now: DownloadTask | None = None

        if task is not None and task.status in {
            DownloadStatus.DOWNLOADING,
            DownloadStatus.POSTPROCESSING,
            DownloadStatus.STOPPED,
            DownloadStatus.FAILED,
        }:
            partials = find_partial_download_files(task)
            should_offer = should_offer_partial_cleanup(
                task,
                active=active,
                detected_count=len(partials),
            )
            if partials:
                cleanup_message = (
                    f"이 작업의 미완성 다운로드 파일 {len(partials)}개가 남아 있습니다. "
                    "목록과 함께 삭제할까요?\n\n"
                    "완성된 영상과 별도 저장을 선택한 결과 파일은 삭제하지 않습니다."
                )
            else:
                cleanup_message = (
                    "이 작업은 다운로드를 시작한 기록이 있습니다. "
                    "남아 있는 미완성 파일도 함께 정리할까요?\n\n"
                    "완성된 영상과 별도 저장을 선택한 결과 파일은 삭제하지 않습니다."
                )
            if should_offer and ask_warm_question(
                self,
                "미완성 다운로드 파일 정리",
                cleanup_message,
                yes_text="미완성 파일도 삭제",
                no_text="목록만 삭제",
            ):
                if active:
                    self._pending_partial_cleanup[task_id] = task
                else:
                    cleanup_now = task

        super()._task_removed(task_id)

        if cleanup_now is not None:
            QTimer.singleShot(
                0,
                lambda task=cleanup_now: self._start_partial_cleanup(task),
            )

    def _download_finished(self, task_id: str) -> None:
        super()._download_finished(task_id)
        task = self._pending_partial_cleanup.pop(task_id, None)
        if task is not None:
            QTimer.singleShot(
                120,
                lambda task=task: self._start_partial_cleanup(task),
            )

    def _start_partial_cleanup(self, task: DownloadTask) -> None:
        self._attempt_partial_cleanup(
            task,
            attempt=0,
            deleted=(),
            unresolved_failed=(),
        )

    def _attempt_partial_cleanup(
        self,
        task: DownloadTask,
        *,
        attempt: int,
        deleted: tuple[str, ...],
        unresolved_failed: tuple[str, ...],
    ) -> None:
        diagnostics = partial_cleanup_scan_diagnostics(task)
        write_download_event(
            "download.partial_cleanup_scan",
            task_id=task.task_id,
            attempt=attempt + 1,
            started_at=f"{task.download_started_at:.3f}",
            embed_thumbnail=task.embed_thumbnail,
            save_thumbnail=task.save_thumbnail,
            entries=" || ".join(diagnostics),
        )

        result = cleanup_partial_download_files(task)
        deleted_now = tuple(dict.fromkeys((*deleted, *result.deleted)))

        still_failed = [
            path
            for path in unresolved_failed
            if path not in deleted_now and Path(path).exists()
        ]
        for path in result.failed:
            if path not in deleted_now and path not in still_failed:
                still_failed.append(path)
        unresolved_now = tuple(still_failed)

        next_attempt = attempt + 1
        can_retry = next_attempt < len(_PARTIAL_CLEANUP_RETRY_DELAYS_MS)

        if can_retry:
            delay_ms = _PARTIAL_CLEANUP_RETRY_DELAYS_MS[next_attempt]
            write_download_event(
                "download.partial_cleanup_retry",
                task_id=task.task_id,
                attempt=next_attempt + 1,
                delay_ms=delay_ms,
                deleted=len(deleted_now),
                unresolved=len(unresolved_now),
            )
            QTimer.singleShot(
                delay_ms,
                lambda task=task, attempt=next_attempt, deleted=deleted_now,
                unresolved=unresolved_now: self._attempt_partial_cleanup(
                    task,
                    attempt=attempt,
                    deleted=deleted,
                    unresolved_failed=unresolved,
                ),
            )
            return

        final_failed = tuple(
            path for path in unresolved_now if Path(path).exists()
        )
        self._report_partial_cleanup(
            task.task_id,
            PartialCleanupResult(
                deleted=deleted_now,
                failed=final_failed,
            ),
        )

    def _report_partial_cleanup(
        self,
        task_id: str,
        result: PartialCleanupResult,
    ) -> None:
        write_download_event(
            "download.partial_cleanup",
            task_id=task_id,
            deleted=result.deleted_count,
            failed=result.failed_count,
        )
        if result.failed_count:
            self.toast.show_message(
                f"미완성 파일 {result.deleted_count}개 삭제 · "
                f"{result.failed_count}개는 삭제하지 못했습니다."
            )
        elif result.deleted_count:
            self.toast.show_message(
                f"미완성 다운로드 파일 {result.deleted_count}개도 함께 삭제했습니다."
            )
        else:
            self.toast.show_message("미완성 다운로드 파일이 이미 정리되어 있습니다.")


__all__ = ["DownloadPage"]