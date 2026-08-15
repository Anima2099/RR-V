from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from core.thumbnail_models import ThumbnailOptions, ThumbnailTask
from services.thumbnail_service import (
    ThumbnailCancelledError,
    ThumbnailExecutionError,
    ThumbnailService,
    scan_folder_for_tasks,
)


class ThumbnailProbeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, video_path: str) -> None:
        super().__init__()
        self.video_path = video_path

    def run(self) -> None:
        try:
            result = ThumbnailService().probe_existing_thumbnail(self.video_path)
        except ThumbnailExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit(
                "현재 썸네일을 확인하는 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            self.succeeded.emit(result)


class ThumbnailBatchWorker(QThread):
    task_started = Signal(int, int, str)
    task_succeeded = Signal(int, str)
    task_failed = Signal(int, str, str)
    progress_changed = Signal(int)
    cancelled = Signal()
    completed = Signal(int, int)

    def __init__(
        self,
        tasks: list[ThumbnailTask],
        options: ThumbnailOptions,
    ) -> None:
        super().__init__()
        self.tasks = list(tasks)
        self.options = options
        self._cancel_event = threading.Event()
        self._service: ThumbnailService | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._service is not None:
            self._service.cancel()

    def run(self) -> None:
        success_count = 0
        fail_count = 0
        total = len(self.tasks)
        if total <= 0:
            self.completed.emit(0, 0)
            return

        for index, task in enumerate(self.tasks):
            if self._cancel_event.is_set():
                self.cancelled.emit()
                return

            self.task_started.emit(index, total, task.video_path)
            service = ThumbnailService()
            self._service = service
            try:
                result = service.replace_thumbnail(
                    task.video_path,
                    task.image_path,
                    self.options,
                    self._cancel_event,
                )
            except ThumbnailCancelledError:
                self.cancelled.emit()
                return
            except ThumbnailExecutionError as error:
                fail_count += 1
                self.task_failed.emit(
                    index,
                    error.user_message,
                    error.technical_detail,
                )
            except Exception as error:
                fail_count += 1
                self.task_failed.emit(
                    index,
                    "썸네일 교체 중 예상하지 못한 문제가 발생했습니다.",
                    repr(error),
                )
            else:
                success_count += 1
                self.task_succeeded.emit(index, result.output_path)
            finally:
                self._service = None

            self.progress_changed.emit(
                int(round((index + 1) / total * 100))
            )

        self.completed.emit(success_count, fail_count)


class ThumbnailFolderScanWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str)

    def __init__(self, folder_path: str) -> None:
        super().__init__()
        self.folder_path = folder_path

    def run(self) -> None:
        try:
            pairs = scan_folder_for_tasks(self.folder_path)
        except Exception as error:
            self.failed.emit(repr(error))
        else:
            self.succeeded.emit(pairs)
