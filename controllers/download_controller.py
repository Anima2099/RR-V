from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from core.download_task import DownloadTask
from workers.analysis_worker import AnalysisWorker
from workers.download_worker import DownloadWorker


class DownloadController(QObject):
    analysis_started = Signal()
    analysis_status_changed = Signal(str)
    analysis_succeeded = Signal(object, bytes)
    analysis_failed = Signal(str, str, str)
    analysis_cancelled = Signal(str)
    analysis_finished = Signal()

    download_started = Signal(str)
    download_process_started = Signal(str, int)
    download_phase_changed = Signal(str, str, str)
    download_progress_changed = Signal(str, int, str, str, object, object, bool)
    download_succeeded = Signal(str, str, str)
    download_failed = Signal(str, str, str)
    download_cancelled = Signal(str, str)
    download_finished = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._analysis_worker: AnalysisWorker | None = None
        self._download_worker: DownloadWorker | None = None
        self._active_download_task_id = ""

    @property
    def is_analyzing(self) -> bool:
        return (
            self._analysis_worker is not None
            and self._analysis_worker.isRunning()
        )

    @property
    def is_downloading(self) -> bool:
        return (
            self._download_worker is not None
            and self._download_worker.isRunning()
        )

    @property
    def active_download_task_id(self) -> str:
        return self._active_download_task_id

    def analyze(self, url: str, log_id: str = "") -> None:
        if self.is_analyzing:
            return

        worker = AnalysisWorker(url, log_id)
        self._analysis_worker = worker

        worker.status_changed.connect(self.analysis_status_changed)
        worker.analysis_succeeded.connect(self.analysis_succeeded)
        worker.analysis_failed.connect(self.analysis_failed)
        worker.analysis_cancelled.connect(self.analysis_cancelled)
        worker.finished.connect(self._analysis_worker_finished)

        self.analysis_started.emit()
        worker.start()

    def cancel_analysis(self) -> None:
        if self._analysis_worker is not None:
            self._analysis_worker.cancel()

    def start_download(self, task: DownloadTask) -> bool:
        if self.is_downloading:
            return False

        worker = DownloadWorker(task)
        task_id = task.task_id
        self._download_worker = worker
        self._active_download_task_id = task_id

        worker.process_started.connect(
            lambda pid, current=task_id: self.download_process_started.emit(
                current, pid
            )
        )
        worker.phase_changed.connect(
            lambda phase, message, current=task_id:
                self.download_phase_changed.emit(current, phase, message)
        )
        worker.progress_changed.connect(
            lambda percent, speed, eta, downloaded, total, estimated, current=task_id:
                self.download_progress_changed.emit(
                    current,
                    percent,
                    speed,
                    eta,
                    downloaded,
                    total,
                    estimated,
                )
        )
        worker.download_succeeded.connect(
            lambda output, raw_log, current=task_id:
                self.download_succeeded.emit(current, output, raw_log)
        )
        worker.download_failed.connect(
            lambda message, detail, current=task_id:
                self.download_failed.emit(current, message, detail)
        )
        worker.download_cancelled.connect(
            lambda message, current=task_id:
                self.download_cancelled.emit(current, message)
        )
        worker.finished.connect(
            lambda current=task_id: self._download_worker_finished(current)
        )

        self.download_started.emit(task_id)
        worker.start()
        return True

    def cancel_download(self, task_id: str | None = None) -> bool:
        worker = self._download_worker
        if worker is None or not worker.isRunning():
            return False
        if task_id and task_id != self._active_download_task_id:
            return False
        worker.cancel()
        return True

    def shutdown(self) -> None:
        analysis_worker = self._analysis_worker
        if analysis_worker is not None:
            analysis_worker.cancel()
            analysis_worker.wait(2500)

        download_worker = self._download_worker
        if download_worker is not None:
            download_worker.cancel()
            download_worker.wait(5000)

    def _analysis_worker_finished(self) -> None:
        worker = self._analysis_worker
        self._analysis_worker = None
        if worker is not None:
            worker.deleteLater()
        self.analysis_finished.emit()

    def _download_worker_finished(self, task_id: str) -> None:
        worker = self._download_worker
        self._download_worker = None
        self._active_download_task_id = ""
        if worker is not None:
            worker.deleteLater()
        self.download_finished.emit(task_id)
