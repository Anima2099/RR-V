from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from services.ytdlp_service import (
    AnalysisCancelledError,
    MediaAnalysisError,
    YtDlpService,
)


class AnalysisWorker(QThread):
    status_changed = Signal(str)
    analysis_succeeded = Signal(object, bytes)
    analysis_failed = Signal(str, str, str)
    analysis_cancelled = Signal(str)

    def __init__(self, url: str, log_id: str = "") -> None:
        super().__init__()
        self.url = url
        self.log_id = log_id
        self._cancel_event = threading.Event()
        self._service = YtDlpService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        try:
            self.status_changed.emit("yt-dlp 영상 정보 확인 중…")
            media_info = self._service.analyze(
                self.url,
                self._cancel_event,
                self.log_id,
            )

            if self._cancel_event.is_set():
                raise AnalysisCancelledError("영상 정보 확인 취소됨")

            thumbnail_data = b""
            if media_info.thumbnail_url:
                self.status_changed.emit("썸네일을 불러오는 중…")
                thumbnail_data = self._service.download_thumbnail(
                    media_info.thumbnail_url
                )

            if self._cancel_event.is_set():
                raise AnalysisCancelledError("영상 정보 확인 취소됨")

            self.analysis_succeeded.emit(media_info, thumbnail_data)
        except AnalysisCancelledError as error:
            self.analysis_cancelled.emit(str(error))
        except MediaAnalysisError as error:
            raw_log_path = error.raw_log_path
            if not raw_log_path:
                raw_log_path = self._service._write_analysis_failure_log(
                    self.log_id,
                    self.url,
                    command=(),
                    return_code=None,
                    stdout="",
                    stderr="",
                    failure_detail=error.technical_detail or error.user_message,
                )
            self.analysis_failed.emit(
                error.user_message,
                error.technical_detail,
                raw_log_path,
            )
        except Exception as error:  # 마지막 안전망
            detail = repr(error)
            raw_log_path = self._service._write_analysis_failure_log(
                self.log_id,
                self.url,
                command=(),
                return_code=None,
                stdout="",
                stderr="",
                failure_detail=detail,
            )
            self.analysis_failed.emit(
                "영상 정보를 확인하는 중 예상하지 못한 문제가 발생했습니다.",
                detail,
                raw_log_path,
            )
