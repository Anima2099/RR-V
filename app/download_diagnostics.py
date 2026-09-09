from __future__ import annotations

from functools import wraps

from app.download_log import write_download_event
from core.download_task import DownloadStatus


_INSTALLED = False


def _status_snapshot(page: object) -> str:
    tasks = getattr(page, "tasks", ()) or ()
    parts: list[str] = []
    for task in tasks:
        task_id = str(getattr(task, "task_id", ""))[:8]
        status = getattr(getattr(task, "status", None), "value", "unknown")
        parts.append(f"{task_id}:{status}")
    return ",".join(parts) or "none"


def _button_snapshot(page: object) -> tuple[bool, str]:
    button = getattr(page, "start_all_button", None)
    if button is None:
        return False, "missing"
    return bool(button.isEnabled()), str(button.text())


def install_download_diagnostics() -> None:
    """빠른 추가의 분석->대기열 전환을 추적하고 타이밍 구멍을 막는다.

    기존 DownloadPage에는 분석 중 작업을 기다리는 `_queue_waiting_for_analysis`
    상태와 후속 대기열 진행 코드가 이미 있지만, 첫 다운로드 시작 버튼은 QUEUED
    작업이 생긴 뒤에만 활성화되어 사용자의 시작 요청을 미리 예약할 수 없었다.
    이 임시 진단 계층은 그 연결을 보완하면서 실제 버튼/상태 전환을 기록한다.

    원인이 스모크 테스트로 확정되면 같은 동작을 본 코드에 정리하고 이 모듈은
    제거한다.
    """
    global _INSTALLED
    if _INSTALLED:
        return

    from ui.pages.download_page import DownloadPage

    original_refresh = DownloadPage._refresh_list_state

    @wraps(original_refresh)
    def traced_refresh(page, *args, **kwargs):  # type: ignore[no-untyped-def]
        result = original_refresh(page, *args, **kwargs)

        controller = getattr(page, "controller", None)
        recovery_running = bool(page._recovery_running())
        downloading = bool(getattr(controller, "is_downloading", False))
        waiting = bool(getattr(page, "_queue_waiting_for_analysis", False))
        queued_exists = any(
            getattr(task, "status", None) is DownloadStatus.QUEUED
            for task in (getattr(page, "tasks", ()) or ())
        )
        pending_analysis = bool(page._has_pending_analysis())

        # 빠른 추가 직후에는 아직 QUEUED 작업이 없어도 사용자가 다운로드 시작을
        # 예약할 수 있게 한다. 기존 대기열 상태 머신이 분석 완료 후 이어서 시작한다.
        if (
            not recovery_running
            and not downloading
            and not waiting
            and pending_analysis
            and not queued_exists
        ):
            page.start_all_button.setText("다운로드 시작")
            page.start_all_button.setEnabled(True)
            page.start_all_button.setToolTip(
                "분석 중인 영상은 정보 확인이 끝나면 순서대로 다운로드합니다."
            )

        enabled, text = _button_snapshot(page)
        if pending_analysis or queued_exists or waiting:
            write_download_event(
                "diag.queue.refresh_state",
                button_enabled=enabled,
                button_text=text,
                queued=queued_exists,
                pending_analysis=pending_analysis,
                waiting=waiting,
                queue_running=bool(getattr(page, "_queue_running", False)),
                controller_downloading=downloading,
                statuses=_status_snapshot(page),
            )
        return result

    DownloadPage._refresh_list_state = traced_refresh

    original_start_first = DownloadPage._start_first_queued

    @wraps(original_start_first)
    def traced_start_first(page, *args, **kwargs):  # type: ignore[no-untyped-def]
        controller = getattr(page, "controller", None)
        tasks = getattr(page, "tasks", ()) or ()
        queued_count = sum(
            getattr(task, "status", None) is DownloadStatus.QUEUED
            for task in tasks
        )
        pending_analysis = bool(page._has_pending_analysis())
        enabled, text = _button_snapshot(page)
        write_download_event(
            "diag.queue.start_first_enter",
            queued=queued_count,
            task_count=len(tasks),
            pending_analysis=pending_analysis,
            button_enabled=enabled,
            button_text=text,
            queue_running=bool(getattr(page, "_queue_running", False)),
            controller_downloading=bool(
                getattr(controller, "is_downloading", False)
            ),
            recovery_running=bool(page._recovery_running()),
            statuses=_status_snapshot(page),
        )

        # 기존 코드는 QUEUED 작업이 아직 없으면 즉시 종료한다. 빠른 추가처럼
        # 분석 중인 작업이 존재할 때는 사용자의 시작 의사를 대기열에 예약한다.
        if (
            not bool(getattr(controller, "is_downloading", False))
            and not page._recovery_running()
            and page._next_queued_task() is None
            and pending_analysis
        ):
            page._queue_running = True
            page._queue_waiting_for_analysis = True
            page._queue_had_success = False
            page._queue_had_failure = False
            write_download_event(
                "queue.started_waiting_analysis",
                pending=sum(
                    getattr(task, "status", None) is DownloadStatus.ANALYZING
                    for task in tasks
                ),
                statuses=_status_snapshot(page),
            )
            page._refresh_list_state()
            page.toast.show_message(
                "영상 정보 확인이 끝나면 다운로드를 시작합니다."
            )
            return None

        try:
            return original_start_first(page, *args, **kwargs)
        except Exception as error:
            write_download_event(
                "diag.queue.start_first_exception",
                error=repr(error),
            )
            raise

    DownloadPage._start_first_queued = traced_start_first

    original_complete_quick = DownloadPage._complete_quick_task

    @wraps(original_complete_quick)
    def traced_complete_quick(page, media_info, thumbnail_data):  # type: ignore[no-untyped-def]
        task_id = str(getattr(page, "_active_quick_task_id", ""))
        before_enabled, before_text = _button_snapshot(page)
        write_download_event(
            "diag.quick.complete_enter",
            task_id=task_id,
            button_enabled=before_enabled,
            button_text=before_text,
            queue_running=bool(getattr(page, "_queue_running", False)),
            waiting=bool(getattr(page, "_queue_waiting_for_analysis", False)),
            statuses=_status_snapshot(page),
        )
        result = original_complete_quick(page, media_info, thumbnail_data)
        task = page._task_by_id(task_id) if task_id else None
        after_enabled, after_text = _button_snapshot(page)
        write_download_event(
            "diag.quick.complete_exit",
            task_id=task_id,
            task_status=(
                getattr(getattr(task, "status", None), "value", "missing")
                if task is not None
                else "missing"
            ),
            button_enabled=after_enabled,
            button_text=after_text,
            queue_running=bool(getattr(page, "_queue_running", False)),
            waiting=bool(getattr(page, "_queue_waiting_for_analysis", False)),
            statuses=_status_snapshot(page),
        )
        return result

    DownloadPage._complete_quick_task = traced_complete_quick

    original_analysis_finished = DownloadPage._analysis_finished

    @wraps(original_analysis_finished)
    def traced_analysis_finished(page, *args, **kwargs):  # type: ignore[no-untyped-def]
        before_enabled, before_text = _button_snapshot(page)
        write_download_event(
            "diag.quick.analysis_finished_enter",
            mode=str(getattr(page, "_analysis_mode", "")),
            button_enabled=before_enabled,
            button_text=before_text,
            queue_running=bool(getattr(page, "_queue_running", False)),
            waiting=bool(getattr(page, "_queue_waiting_for_analysis", False)),
            statuses=_status_snapshot(page),
        )
        result = original_analysis_finished(page, *args, **kwargs)

        # QThread finished 처리까지 끝난 최종 상태에서 한 번 더 확정한다. 빠른 추가
        # 카드와 상단 시작 버튼이 서로 다른 상태로 남는 것을 방지한다.
        page._refresh_list_state()
        after_enabled, after_text = _button_snapshot(page)
        write_download_event(
            "diag.quick.analysis_finished_exit",
            button_enabled=after_enabled,
            button_text=after_text,
            queue_running=bool(getattr(page, "_queue_running", False)),
            waiting=bool(getattr(page, "_queue_waiting_for_analysis", False)),
            statuses=_status_snapshot(page),
        )
        return result

    DownloadPage._analysis_finished = traced_analysis_finished

    original_init = DownloadPage.__init__

    @wraps(original_init)
    def traced_init(page, *args, **kwargs):  # type: ignore[no-untyped-def]
        original_init(page, *args, **kwargs)

        page.start_all_button.pressed.connect(
            lambda: write_download_event(
                "diag.queue.button_pressed",
                button_enabled=page.start_all_button.isEnabled(),
                button_text=page.start_all_button.text(),
                statuses=_status_snapshot(page),
            )
        )
        page.start_all_button.released.connect(
            lambda: write_download_event(
                "diag.queue.button_released",
                button_enabled=page.start_all_button.isEnabled(),
                button_text=page.start_all_button.text(),
                statuses=_status_snapshot(page),
            )
        )
        page.start_all_button.clicked.connect(
            lambda: write_download_event(
                "diag.queue.button_clicked",
                button_enabled=page.start_all_button.isEnabled(),
                button_text=page.start_all_button.text(),
                statuses=_status_snapshot(page),
            )
        )

    DownloadPage.__init__ = traced_init

    _INSTALLED = True
    write_download_event("diag.quick_add_queue_guard_installed")
