from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from app.download_log import write_download_event
from core.download_task import DownloadTask
from services.subtitle_recovery_service import (
    SubtitleRecoveryCancelledError,
    SubtitleRecoveryError,
    SubtitleRecoveryService,
)


class SubtitleRecoveryWorker(QThread):
    phase_changed = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, task: DownloadTask) -> None:
        super().__init__()
        self.task = task
        self._cancel_event = threading.Event()
        self._service = SubtitleRecoveryService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        write_download_event(
            "subtitle_recovery.started",
            task_id=self.task.task_id,
            url=self.task.url,
        )
        try:
            result = self._service.recover(
                self.task,
                self._cancel_event,
                self.phase_changed.emit,
            )
        except SubtitleRecoveryCancelledError as error:
            write_download_event(
                "subtitle_recovery.cancelled",
                task_id=self.task.task_id,
            )
            self.cancelled.emit(str(error))
        except SubtitleRecoveryError as error:
            write_download_event(
                "subtitle_recovery.failed",
                task_id=self.task.task_id,
                message=error.user_message,
            )
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            write_download_event(
                "subtitle_recovery.unexpected_error",
                task_id=self.task.task_id,
                error=repr(error),
            )
            self.failed.emit(
                "자막 복구 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            write_download_event(
                "subtitle_recovery.succeeded",
                task_id=self.task.task_id,
                output=result.output_file,
                embedded=len(result.embedded_languages),
                sidecars=len(result.sidecar_files),
                skipped=len(result.skipped_existing_languages),
            )
            self.succeeded.emit(result)
