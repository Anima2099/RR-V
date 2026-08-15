from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from app.download_log import write_download_event
from core.download_task import DownloadTask
from services.download_service import (
    DownloadCancelledError,
    DownloadExecutionError,
    YtDlpDownloadService,
)


class DownloadWorker(QThread):
    process_started = Signal(int)
    phase_changed = Signal(str, str)
    progress_changed = Signal(int, str, str, object, object, bool)
    download_succeeded = Signal(str, str)
    download_failed = Signal(str, str)
    download_cancelled = Signal(str)

    def __init__(self, task: DownloadTask) -> None:
        super().__init__()
        self.task = task
        self._cancel_event = threading.Event()
        self._service = YtDlpDownloadService()
        self._last_progress_bucket = -1
        self._last_phase = ""

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.download(
                self.task,
                self._cancel_event,
                on_progress=self._emit_progress,
                on_phase=self._emit_phase,
                on_process=self.process_started.emit,
            )
        except DownloadCancelledError as error:
            self.download_cancelled.emit(str(error))
        except DownloadExecutionError as error:
            write_download_event(
                "download.worker_failed",
                task_id=self.task.task_id,
                message=error.user_message,
                raw_log=self.task.raw_log_path or "-",
            )
            self.download_failed.emit(error.user_message, error.technical_detail)
        except Exception as error:  # 마지막 안전망
            write_download_event(
                "download.worker_unexpected_error",
                task_id=self.task.task_id,
                error=repr(error),
            )
            self.download_failed.emit(
                "예상하지 못한 다운로드 오류가 발생했습니다.",
                repr(error),
            )
        else:
            self.download_succeeded.emit(
                result.output_file,
                result.raw_log_path,
            )

    def _emit_progress(
        self,
        percent: int,
        speed: str,
        eta: str,
        downloaded_bytes: int,
        total_bytes: int,
        total_estimated: bool,
    ) -> None:
        self.progress_changed.emit(
            percent,
            speed,
            eta,
            downloaded_bytes,
            total_bytes,
            total_estimated,
        )
        bucket = min(4, max(0, percent) // 25)
        if bucket > self._last_progress_bucket:
            self._last_progress_bucket = bucket
            write_download_event(
                "download.progress",
                task_id=self.task.task_id,
                percent=percent,
                speed=speed,
                eta=eta,
                downloaded_bytes=downloaded_bytes,
                total_bytes=total_bytes,
                total_estimated=total_estimated,
            )

    def _emit_phase(self, phase: str, message: str) -> None:
        self.phase_changed.emit(phase, message)
        phase_key = f"{phase}:{message}"
        if phase_key == self._last_phase:
            return
        self._last_phase = phase_key
        write_download_event(
            "download.phase",
            task_id=self.task.task_id,
            phase=phase,
            message=message,
        )
