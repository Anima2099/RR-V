from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from core.local_media_info import MediaFileInfo
from services.remux_service import (
    RemuxCancelledError,
    RemuxError,
    RemuxService,
)


class RemuxWorker(QThread):
    progress_changed = Signal(int)
    phase_changed = Signal(str)
    succeeded = Signal(str, int)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, media_info: MediaFileInfo, target_container: str) -> None:
        super().__init__()
        self.media_info = media_info
        self.target_container = target_container
        self._service = RemuxService()

    def cancel(self) -> None:
        self.requestInterruption()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.remux(
                self.media_info,
                self.target_container,
                on_progress=self.progress_changed.emit,
                on_phase=self.phase_changed.emit,
                is_cancelled=self.isInterruptionRequested,
            )
        except RemuxCancelledError as error:
            self.cancelled.emit(str(error))
        except RemuxError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit(
                "Remux 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            self.succeeded.emit(result.output_path, result.size_bytes)
