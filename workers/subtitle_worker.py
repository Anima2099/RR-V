from __future__ import annotations

import threading

from PySide6.QtCore import QThread, Signal

from core.subtitle_models import SubtitleOptions, SubtitleTask
from services.subtitle_service import SubtitleCancelledError, SubtitleExecutionError, SubtitleService


class SubtitleProbeWorker(QThread):
    succeeded = Signal(object)
    failed = Signal(str, str)

    def __init__(self, video_path: str) -> None:
        super().__init__()
        self.video_path = video_path

    def run(self) -> None:
        try:
            result = SubtitleService().probe_video(self.video_path)
        except SubtitleExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit("자막 정보를 확인하는 중 예상하지 못한 문제가 발생했습니다.", repr(error))
        else:
            self.succeeded.emit(result)


class SubtitleWorker(QThread):
    phase_changed = Signal(str)
    progress_changed = Signal(int, str)
    succeeded = Signal(object)
    failed = Signal(str, str)
    cancelled = Signal(str)

    def __init__(self, task: SubtitleTask, options: SubtitleOptions) -> None:
        super().__init__()
        self.task = task
        self.options = options
        self._cancel_event = threading.Event()
        self._service: SubtitleService | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._service is not None:
            self._service.cancel()

    def run(self) -> None:
        self._service = SubtitleService()
        try:
            phase = {
                "extract": "영상에서 자막 읽는 중",
                "insert": "영상·음성을 그대로 복사해 새 파일 구성 중",
                "remove": "자막을 제외하고 새 영상 구성 중",
                "sync": "자막 시간 정보를 조정하는 중",
            }.get(self.options.operation, "자막 작업 준비 중")
            self.phase_changed.emit(phase)
            result = self._service.execute(
                self.task,
                self.options,
                self._cancel_event,
                progress_callback=lambda percent, detail: self.progress_changed.emit(percent, detail),
            )
        except SubtitleCancelledError as error:
            self.cancelled.emit(str(error))
        except SubtitleExecutionError as error:
            self.failed.emit(error.user_message, error.technical_detail)
        except Exception as error:
            self.failed.emit("자막 작업 중 예상하지 못한 문제가 발생했습니다.", repr(error))
        else:
            self.succeeded.emit(result)
        finally:
            self._service = None


class SubtitleBatchWorker(QThread):
    current_changed = Signal(int, int, object)
    item_started = Signal(int, object)
    item_succeeded = Signal(int, object)
    item_failed = Signal(int, str, str)
    item_progress = Signal(int, int, str)
    cancelled = Signal(str)
    completed = Signal(int, int)

    def __init__(self, tasks: list[SubtitleTask], options: SubtitleOptions) -> None:
        super().__init__()
        self.tasks = list(tasks)
        self.options = options
        self._cancel_event = threading.Event()
        self._service: SubtitleService | None = None

    def cancel(self) -> None:
        self._cancel_event.set()
        if self._service is not None:
            self._service.cancel()

    def run(self) -> None:
        success = 0
        failed = 0
        total = len(self.tasks)
        for index, task in enumerate(self.tasks):
            if self._cancel_event.is_set():
                self.cancelled.emit("여러 자막 작업 중지됨")
                return
            self.current_changed.emit(index + 1, total, task)
            self.item_started.emit(index, task)
            service = SubtitleService()
            self._service = service
            try:
                result = service.execute(
                    task,
                    self.options,
                    self._cancel_event,
                    progress_callback=lambda percent, detail, item_index=index: self.item_progress.emit(item_index, percent, detail),
                )
            except SubtitleCancelledError as error:
                self.cancelled.emit(str(error))
                return
            except SubtitleExecutionError as error:
                failed += 1
                self.item_failed.emit(index, error.user_message, error.technical_detail)
            except Exception as error:
                failed += 1
                self.item_failed.emit(index, "자막 작업 중 예상하지 못한 문제가 발생했습니다.", repr(error))
            else:
                success += 1
                self.item_succeeded.emit(index, result)
            finally:
                self._service = None
        self.completed.emit(success, failed)
