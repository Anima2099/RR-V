from __future__ import annotations

from time import time

from PySide6.QtCore import QObject, QTimer, Signal

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
    download_runtime_ended = Signal(str, bool)
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
        worker = self._download_worker
        if worker is None:
            return False
        if worker.isRunning():
            return True
        return worker.has_running_process

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

        # cleanup 판별에 쓰는 기준 시각은 raw log의 mtime처럼 움직이면 안 된다.
        # 다운로드 세션이 실제로 시작되는 순간을 한 번만 고정해 둔다.
        task.download_started_at = time()
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
        if worker is None:
            return False
        if task_id and task_id != self._active_download_task_id:
            return False
        if not worker.isRunning() and not worker.has_running_process:
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
        process_running = False
        if worker is not None:
            process_running = worker.has_running_process
            if process_running:
                # Worker가 끝났는데 자식 yt-dlp만 남는 비정상 상태라면 한 번
                # 종료를 요청한다. 그래도 살아 있으면 Controller가 소유권을
                # 유지해 새 다운로드가 겹치지 않게 한다.
                worker.cancel()
                process_running = worker.has_running_process

        if not process_running:
            self._release_download_worker(task_id, worker)

        self.download_runtime_ended.emit(task_id, process_running)
        self.download_finished.emit(task_id)

        if process_running and worker is not None:
            QTimer.singleShot(
                350,
                lambda current=task_id, retained=worker:
                    self._recheck_finished_download_runtime(
                        current,
                        retained,
                    ),
            )

    def _recheck_finished_download_runtime(
        self,
        task_id: str,
        worker: DownloadWorker,
    ) -> None:
        if (
            self._download_worker is not worker
            or self._active_download_task_id != task_id
        ):
            return

        if worker.has_running_process:
            # 시간만으로 실패를 판정하지 않는다. 실제 프로세스가 살아 있는
            # 동안은 소유권을 유지하고 다음 상태 확인만 예약한다.
            QTimer.singleShot(
                350,
                lambda current=task_id, retained=worker:
                    self._recheck_finished_download_runtime(
                        current,
                        retained,
                    ),
            )
            return

        self._release_download_worker(task_id, worker)
        # UI가 아직 downloading/postprocessing 상태라면 이 신호를 받은 뒤
        # 고립 작업으로 정리되어 실패/재시도 가능한 상태가 된다.
        self.download_runtime_ended.emit(task_id, False)

    def _release_download_worker(
        self,
        task_id: str,
        worker: DownloadWorker | None,
    ) -> None:
        if (
            task_id != self._active_download_task_id
            and self._active_download_task_id
        ):
            return
        if worker is not None and self._download_worker is not worker:
            return

        self._download_worker = None
        self._active_download_task_id = ""
        if worker is not None:
            worker.deleteLater()
