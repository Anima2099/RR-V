from __future__ import annotations

import gc
import threading

from PySide6.QtCore import QThread, Signal

from core.snapshot_models import SnapshotOptions, SnapshotProbeResult
from services.snapshot_service import SnapshotCancelledError, SnapshotExecutionError, SnapshotService


class SnapshotProbeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, input_path: str) -> None:
        super().__init__()
        self.input_path = input_path

    def run(self) -> None:
        try:
            result = SnapshotService().probe(self.input_path)
        except SnapshotExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit("영상 정보를 확인하는 중 예상하지 못한 문제가 발생했습니다.", repr(error))
        else:
            self.succeeded.emit(result)


class SnapshotWorker(QThread):
    progress_changed = Signal(int)
    phase_changed = Signal(str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, input_path: str, probe: SnapshotProbeResult, options: SnapshotOptions) -> None:
        super().__init__()
        self.input_path = input_path
        self.probe = probe
        self.options = options
        self._cancel_event = threading.Event()
        self._service = SnapshotService()

    def cancel(self) -> None:
        self._cancel_event.set()
        self._service.cancel()

    def run(self) -> None:
        try:
            result = self._service.create_snapshot(
                self.input_path,
                self.probe,
                self.options,
                self._cancel_event,
                on_progress=self.progress_changed.emit,
                on_phase=self.phase_changed.emit,
            )
        except SnapshotCancelledError as error:
            self.cancelled.emit(str(error))
        except SnapshotExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit("스냅샷 생성 중 예상하지 못한 문제가 발생했습니다.", repr(error))
        else:
            self.succeeded.emit(result)


class SnapshotBatchWorker(QThread):
    current_changed = Signal(int, int, str)
    item_started = Signal(int, str)
    item_progress = Signal(int, int)
    item_phase = Signal(int, str)
    item_succeeded = Signal(int, object)
    item_failed = Signal(int, str, str)
    cancelled = Signal(str)
    completed = Signal(int, int)

    def __init__(self, input_paths: list[str], options: SnapshotOptions) -> None:
        super().__init__()
        self.input_paths = list(input_paths)
        self.options = options
        self._cancel_event = threading.Event()
        self._service: SnapshotService | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._service is not None:
            self._service.cancel()

    def run(self) -> None:
        success_count = 0
        fail_count = 0
        total = len(self.input_paths)
        for index, input_path in enumerate(self.input_paths):
            if self._cancel_event.is_set():
                self.cancelled.emit("여러 영상 스냅샷 생성 중지됨")
                return
            self.current_changed.emit(index + 1, total, input_path)
            self.item_started.emit(index, input_path)
            service = SnapshotService()
            self._service = service
            try:
                probe = service.probe(input_path)
                result = service.create_snapshot(
                    input_path,
                    probe,
                    self.options,
                    self._cancel_event,
                    on_progress=lambda value, i=index: self.item_progress.emit(i, value),
                    on_phase=lambda text, i=index: self.item_phase.emit(i, text),
                )
            except SnapshotCancelledError:
                self.cancelled.emit("여러 영상 스냅샷 생성 중지됨")
                return
            except SnapshotExecutionError as error:
                fail_count += 1
                self.item_failed.emit(index, error.user_message, error.technical_detail)
            except Exception as error:
                fail_count += 1
                self.item_failed.emit(index, "스냅샷 생성 중 예상하지 못한 문제가 발생했습니다.", repr(error))
            else:
                success_count += 1
                self.item_succeeded.emit(index, result)
            finally:
                self._service = None
                gc.collect()
                if index + 1 < total and not self._cancel_event.is_set():
                    self.msleep(200)
        self.completed.emit(success_count, fail_count)
