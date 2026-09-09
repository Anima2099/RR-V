from __future__ import annotations

from functools import wraps
from time import perf_counter

from app.download_log import write_download_event


_INSTALLED = False


def _status_snapshot(page: object) -> str:
    tasks = getattr(page, "tasks", ()) or ()
    parts: list[str] = []
    for task in tasks:
        task_id = str(getattr(task, "task_id", ""))[:8]
        status = getattr(getattr(task, "status", None), "value", "unknown")
        parts.append(f"{task_id}:{status}")
    return ",".join(parts) or "none"


def install_download_diagnostics() -> None:
    """Temporarily trace the download-start path without changing behavior.

    These wrappers intentionally log only control-flow state. They do not alter queue
    decisions, task values, worker lifecycle, filename rendering, or yt-dlp commands.
    Remove this module and its main.py hook after the start-path regression is found.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from controllers.download_controller import DownloadController
    from services.download_service import YtDlpDownloadService as BaseDownloadService
    from services.templated_download_service import YtDlpDownloadService as TemplatedDownloadService
    from ui.pages.download_page import DownloadPage
    from workers.download_worker import DownloadWorker

    original_start_first = DownloadPage._start_first_queued

    @wraps(original_start_first)
    def traced_start_first(page, *args, **kwargs):  # type: ignore[no-untyped-def]
        controller = getattr(page, "controller", None)
        tasks = getattr(page, "tasks", ()) or ()
        queued_count = sum(
            getattr(getattr(task, "status", None), "value", "") == "queued"
            for task in tasks
        )
        write_download_event(
            "diag.queue.start_first_enter",
            queued=queued_count,
            task_count=len(tasks),
            queue_running=bool(getattr(page, "_queue_running", False)),
            controller_downloading=bool(
                getattr(controller, "is_downloading", False)
            ),
            recovery_running=bool(page._recovery_running()),
            statuses=_status_snapshot(page),
        )
        try:
            return original_start_first(page, *args, **kwargs)
        except Exception as error:
            write_download_event(
                "diag.queue.start_first_exception",
                error=repr(error),
            )
            raise
        finally:
            tasks_after = getattr(page, "tasks", ()) or ()
            write_download_event(
                "diag.queue.start_first_exit",
                queue_running=bool(getattr(page, "_queue_running", False)),
                controller_downloading=bool(
                    getattr(controller, "is_downloading", False)
                ),
                statuses=_status_snapshot(page),
                queued=sum(
                    getattr(getattr(task, "status", None), "value", "")
                    == "queued"
                    for task in tasks_after
                ),
            )

    DownloadPage._start_first_queued = traced_start_first

    original_start_task = DownloadPage._start_task

    @wraps(original_start_task)
    def traced_start_task(page, task_id: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        task = page._task_by_id(task_id)
        controller = getattr(page, "controller", None)
        write_download_event(
            "diag.queue.start_task_enter",
            task_id=task_id,
            from_queue=bool(kwargs.get("from_queue", False)),
            task_found=task is not None,
            task_status=(
                getattr(getattr(task, "status", None), "value", "missing")
                if task is not None
                else "missing"
            ),
            controller_downloading=bool(
                getattr(controller, "is_downloading", False)
            ),
            recovery_running=bool(page._recovery_running()),
        )
        try:
            return original_start_task(page, task_id, *args, **kwargs)
        except Exception as error:
            write_download_event(
                "diag.queue.start_task_exception",
                task_id=task_id,
                error=repr(error),
            )
            raise
        finally:
            current = page._task_by_id(task_id)
            write_download_event(
                "diag.queue.start_task_exit",
                task_id=task_id,
                task_status=(
                    getattr(getattr(current, "status", None), "value", "missing")
                    if current is not None
                    else "missing"
                ),
                phase=(getattr(current, "phase_message", "") if current else ""),
                process_id=(getattr(current, "process_id", 0) if current else 0),
                controller_downloading=bool(
                    getattr(controller, "is_downloading", False)
                ),
                active_task_id=str(
                    getattr(controller, "active_download_task_id", "")
                ),
            )

    DownloadPage._start_task = traced_start_task

    original_controller_start = DownloadController.start_download

    @wraps(original_controller_start)
    def traced_controller_start(controller, task):  # type: ignore[no-untyped-def]
        write_download_event(
            "diag.controller.start_download_enter",
            task_id=getattr(task, "task_id", ""),
            is_downloading=bool(controller.is_downloading),
            active_task_id=controller.active_download_task_id,
        )
        try:
            result = original_controller_start(controller, task)
        except Exception as error:
            write_download_event(
                "diag.controller.start_download_exception",
                task_id=getattr(task, "task_id", ""),
                error=repr(error),
            )
            raise
        worker = getattr(controller, "_download_worker", None)
        write_download_event(
            "diag.controller.start_download_exit",
            task_id=getattr(task, "task_id", ""),
            result=bool(result),
            active_task_id=controller.active_download_task_id,
            worker_exists=worker is not None,
            worker_running=bool(worker is not None and worker.isRunning()),
        )
        return result

    DownloadController.start_download = traced_controller_start

    original_worker_run = DownloadWorker.run

    @wraps(original_worker_run)
    def traced_worker_run(worker):  # type: ignore[no-untyped-def]
        task = getattr(worker, "task", None)
        task_id = getattr(task, "task_id", "")
        write_download_event(
            "diag.worker.run_enter",
            task_id=task_id,
            cancel_requested=bool(worker._cancel_event.is_set()),
        )
        started = perf_counter()
        try:
            return original_worker_run(worker)
        except Exception as error:
            write_download_event(
                "diag.worker.run_exception",
                task_id=task_id,
                error=repr(error),
            )
            raise
        finally:
            write_download_event(
                "diag.worker.run_exit",
                task_id=task_id,
                elapsed_ms=f"{(perf_counter() - started) * 1000.0:.1f}",
                cancel_requested=bool(worker._cancel_event.is_set()),
            )

    DownloadWorker.run = traced_worker_run

    original_download = BaseDownloadService.download

    @wraps(original_download)
    def traced_download(service, task, *args, **kwargs):  # type: ignore[no-untyped-def]
        write_download_event(
            "diag.service.download_enter",
            task_id=getattr(task, "task_id", ""),
            output_stem=bool(getattr(task, "output_stem", "")),
        )
        started = perf_counter()
        try:
            return original_download(service, task, *args, **kwargs)
        except Exception as error:
            write_download_event(
                "diag.service.download_exception",
                task_id=getattr(task, "task_id", ""),
                elapsed_ms=f"{(perf_counter() - started) * 1000.0:.1f}",
                error=repr(error),
            )
            raise
        finally:
            write_download_event(
                "diag.service.download_exit",
                task_id=getattr(task, "task_id", ""),
                elapsed_ms=f"{(perf_counter() - started) * 1000.0:.1f}",
            )

    BaseDownloadService.download = traced_download

    original_filename_title = TemplatedDownloadService._filename_title

    @wraps(original_filename_title)
    def traced_filename_title(service, task):  # type: ignore[no-untyped-def]
        task_id = getattr(task, "task_id", "")
        write_download_event(
            "diag.filename.resolve_enter",
            task_id=task_id,
        )
        started = perf_counter()
        try:
            result = original_filename_title(service, task)
        except Exception as error:
            write_download_event(
                "diag.filename.resolve_exception",
                task_id=task_id,
                elapsed_ms=f"{(perf_counter() - started) * 1000.0:.1f}",
                error=repr(error),
            )
            raise
        write_download_event(
            "diag.filename.resolve_exit",
            task_id=task_id,
            elapsed_ms=f"{(perf_counter() - started) * 1000.0:.1f}",
            stem_length=len(result),
        )
        return result

    TemplatedDownloadService._filename_title = traced_filename_title
    _INSTALLED = True
    write_download_event("diag.download_start_tracing_installed")
