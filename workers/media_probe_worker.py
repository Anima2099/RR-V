from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from services.media_probe_service import (
    MediaProbeCancelledError,
    MediaProbeError,
    MediaProbeService,
)


class MediaProbeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, input_path: str) -> None:
        super().__init__()
        self.input_path = input_path
        self._service = MediaProbeService()

    def cancel(self) -> None:
        self.requestInterruption()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.probe(
                self.input_path,
                is_cancelled=self.isInterruptionRequested,
            )
        except MediaProbeCancelledError as error:
            self.cancelled.emit(str(error))
        except MediaProbeError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit(
                "미디어 정보를 확인하는 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            self.succeeded.emit(result)
