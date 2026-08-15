from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from core.converter_models import ConversionOptions, VideoProbeResult
from services.converter_service import (
    AnimatedImageConverterService,
    ConversionCancelledError,
    ConversionExecutionError,
)


class ProbeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, input_path: str) -> None:
        super().__init__()
        self.input_path = input_path

    def run(self) -> None:
        try:
            result = AnimatedImageConverterService().probe(self.input_path)
        except ConversionExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit(
                "영상 정보를 확인하는 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            self.succeeded.emit(result)


class ConversionWorker(QThread):
    process_started = Signal(int)
    progress_changed = Signal(int)
    phase_changed = Signal(str)
    attempt_changed = Signal(int, int, str)
    succeeded = Signal(str, int, int)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(
        self,
        input_path: str,
        probe: VideoProbeResult,
        options: ConversionOptions,
    ) -> None:
        super().__init__()
        self.input_path = input_path
        self.probe = probe
        self.options = options
        self._cancel_event = threading.Event()
        self._service = AnimatedImageConverterService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.convert(
                input_path=self.input_path,
                probe=self.probe,
                options=self.options,
                cancel_event=self._cancel_event,
                on_progress=self.progress_changed.emit,
                on_phase=self.phase_changed.emit,
                on_attempt=self.attempt_changed.emit,
                on_process=self.process_started.emit,
            )
        except ConversionCancelledError as error:
            self.cancelled.emit(str(error))
        except ConversionExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit(
                "변환 중 예상하지 못한 문제가 발생했습니다.",
                repr(error),
            )
        else:
            self.succeeded.emit(
                result.output_path,
                result.size_bytes,
                result.attempts,
            )


class BatchConversionWorker(QThread):
    current_changed = Signal(int, int, str)
    item_started = Signal(int, str)
    item_progress = Signal(int, int)
    item_phase = Signal(int, str)
    item_attempt = Signal(int, int, int, str)
    item_succeeded = Signal(int, str, int, int)
    item_failed = Signal(int, str, str)
    cancelled = Signal(str)

    def __init__(
        self,
        input_paths: list[str],
        options: ConversionOptions,
    ) -> None:
        super().__init__()
        self.input_paths = list(input_paths)
        self.options = options
        self._cancel_event = threading.Event()
        self._service = AnimatedImageConverterService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        total = len(self.input_paths)
        for index, input_path in enumerate(self.input_paths):
            if self._cancel_event.is_set():
                self.cancelled.emit("여러 영상 변환 중지됨")
                return

            self.current_changed.emit(index + 1, total, input_path)
            self.item_started.emit(index, input_path)
            try:
                probe = self._service.probe(input_path)
                result = self._service.convert(
                    input_path=input_path,
                    probe=probe,
                    options=self.options,
                    cancel_event=self._cancel_event,
                    on_progress=lambda value, i=index: self.item_progress.emit(i, value),
                    on_phase=lambda text, i=index: self.item_phase.emit(i, text),
                    on_attempt=lambda attempt, maximum, detail, i=index: self.item_attempt.emit(
                        i, attempt, maximum, detail
                    ),
                    on_process=lambda _pid: None,
                )
            except ConversionCancelledError:
                self.cancelled.emit("여러 영상 변환 중지됨")
                return
            except ConversionExecutionError as error:
                self.item_failed.emit(index, error.user_message, error.technical_detail)
            except Exception as error:
                self.item_failed.emit(
                    index,
                    "변환 중 예상하지 못한 문제가 발생했습니다.",
                    repr(error),
                )
            else:
                self.item_succeeded.emit(
                    index,
                    result.output_path,
                    result.size_bytes,
                    result.attempts,
                )
