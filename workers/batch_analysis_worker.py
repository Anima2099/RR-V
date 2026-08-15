from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from services.batch_service import (
    BatchAnalysisCancelledError,
    BatchAnalysisService,
)


class BatchAnalysisWorker(QThread):
    status_changed = Signal(str)
    analysis_succeeded = Signal(object)
    analysis_failed = Signal(str, str)
    analysis_cancelled = Signal(str)

    def __init__(self, urls: list[str]) -> None:
        super().__init__()
        self.urls = list(urls)
        self._cancel_event = threading.Event()
        self._service = BatchAnalysisService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.analyze_sources(
                self.urls,
                self._cancel_event,
                self.status_changed.emit,
            )
            if self._cancel_event.is_set():
                raise BatchAnalysisCancelledError("일괄 목록 확인 취소됨")
            self.analysis_succeeded.emit(result)
        except BatchAnalysisCancelledError as error:
            self.analysis_cancelled.emit(str(error))
        except Exception as error:
            self.analysis_failed.emit(
                "여러 주소의 영상 목록을 확인하지 못했습니다.",
                repr(error),
            )
