from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from app.download_log import write_download_event
from core.download_task import DownloadTask
from services.thumbnail_recovery_service import (
    ThumbnailRecoveryCancelledError,
    ThumbnailRecoveryError,
    ThumbnailRecoveryService,
)


class ThumbnailRecoveryWorker(QThread):
    phase_changed = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, task: DownloadTask) -> None:
        super().__init__()
        self.task = task
        self._cancel_event = threading.Event()
        self._service = ThumbnailRecoveryService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        write_download_event(
            "thumbnail_recovery.started",
            task_id=self.task.task_id,
            url=self.task.url,
        )
        try:
            result = self._service.recover(
                self.task,
                self._cancel_event,
                self.phase_changed.emit,
            )
        except ThumbnailRecoveryCancelledError as error:
            write_download_event(
                "thumbnail_recovery.cancelled",
                task_id=self.task.task_id,
            )
            self.cancelled.emit(str(error))
        except ThumbnailRecoveryError as error:
            write_download_event(
                "thumbnail_recovery.failed",
                task_id=self.task.task_id,
                message=error.user_message,
            )
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            write_download_event(
                "thumbnail_recovery.unexpected_error",
                task_id=self.task.task_id,
                error=repr(error),
            )
            self.failed.emit(
                "썸네일 복구 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            write_download_event(
                "thumbnail_recovery.succeeded",
                task_id=self.task.task_id,
                output=result.output_file,
            )
            self.succeeded.emit(result)
