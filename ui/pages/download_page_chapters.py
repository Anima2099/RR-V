from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from app.chapter_preferences import load_delete_original_after_split
from app.download_preferences import load_download_preferences
from app.download_log import write_download_event
from core.download_task import DownloadStatus, DownloadTask
from services.partial_download_cleanup import (
    PartialCleanupResult,
    cleanup_partial_download_files,
    find_partial_download_files,
    should_offer_partial_cleanup,
)
from ui.dialogs.warm_dialogs import ask_warm_question
from ui.pages.download_page import DownloadPage as _BaseDownloadPage
from ui.widgets.chapter_preview_panel import PreviewPanel


_PARTIAL_CLEANUP_RETRY_DELAYS_MS = (0, 250, 500, 750)


class DownloadPage(_BaseDownloadPage):
    """기존 DownloadPage에 1.4 챕터 저장 UX와 안전한 정리 동작을 얹는다."""

    def __init__(self) -> None:
        self._pending_partial_cleanup: dict[str, DownloadTask] = {}
        super().__init__()

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
            task.delete_original_after_split = bool(
                task.split_chapters
                and load_delete_original_after_split(preferences.preset_id)
            )
            self.task_list.refresh_task(task.task_id)
        except Exception:
            # 빠른 추가 자체를 부가 표시 옵션 때문에 실패시키지 않는다.
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
            task.delete_original_after_split = bool(
                task.split_chapters
                and load_delete_original_after_split(preferences.preset_id)
            )
            self.task_list.refresh_task(task.task_id)
            self._schedule_queue_save()
        except Exception:
            # 분석 성공 뒤 표시 보강이 실패해도 기존 빠른 추가 흐름은 유지한다.
            pass

    def _create_task_from_preview(self, start_immediately: bool) -> None:
        before_ids = {task.task_id for task in self.tasks}
        try:
            options = self.preview_panel.selected_options()
            desired_split = bool(options.get("split_chapters", False))
            desired_delete = bool(
                desired_split and options.get("delete_original_after_split", False)
            )
        except Exception:
            desired_split = False
            desired_delete = False

        super()._create_task_from_preview(start_immediately)

        created = next(
            (task for task in self.tasks if task.task_id not in before_ids),
            None,
        )
        if created is None:
            return

        created.split_chapters = bool(desired_split and not created.audio_only)
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
        # 원본 삭제 성공 때만 대표 완료 파일이 첫 챕터다. 이 경우 카드의 파일
        # 크기는 첫 조각 하나가 아니라 챕터 폴더 전체 결과 용량으로 보여준다.
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
                    "완성된 영상, 자막, 썸네일 파일은 삭제하지 않습니다."
                )
            else:
                cleanup_message = (
                    "이 작업은 다운로드를 시작한 기록이 있습니다. "
                    "남아 있는 미완성 파일도 함께 정리할까요?\n\n"
                    "완성된 영상, 자막, 썸네일 파일은 삭제하지 않습니다."
                )
            if should_offer and ask_warm_question(
                self,
                "미완성 다운로드 파일 정리",
                cleanup_message,
                yes_text="부분 파일도 삭제",
                no_text="목록만 삭제",
            ):
                if active:
                    # 프로세스가 파일 핸들을 놓은 뒤 정리하도록 작업 객체를 보관한다.
                    self._pending_partial_cleanup[task_id] = task
                else:
                    cleanup_now = task

        super()._task_removed(task_id)

        if cleanup_now is not None:
            # 다이얼로그가 닫힌 뒤 이벤트 루프로 돌아가서 정리를 시작한다.
            QTimer.singleShot(
                0,
                lambda task=cleanup_now: self._start_partial_cleanup(task),
            )

    def _download_finished(self, task_id: str) -> None:
        super()._download_finished(task_id)
        task = self._pending_partial_cleanup.pop(task_id, None)
        if task is not None:
            # Windows에서 프로세스 종료 직후 파일 핸들이 풀리는 짧은 틈을 피한다.
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

        no_match_yet = not deleted_now and not unresolved_now
        retry_needed = bool(unresolved_now or no_match_yet)
        next_attempt = attempt + 1
        can_retry = next_attempt < len(_PARTIAL_CLEANUP_RETRY_DELAYS_MS)

        if retry_needed and can_retry:
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
