from __future__ import annotations

from PySide6.QtCore import QTimer

from ui.pages.download_page import DownloadPage as _BaseDownloadPage


class DownloadPage(_BaseDownloadPage):
    """1.4 refinement that restores manual Quick Add as a one-click download.

    The base page already has a proven auto-download queue path used by browser
    requests. Manual Quick Add now marks its task for that same path before the
    analysis worker starts, avoiding a race even when analysis completes quickly.
    Batch Add remains unchanged and therefore only queues items.
    """

    def __init__(self) -> None:
        super().__init__()
        self.quick_add_button.setToolTip(
            "기본 프리셋으로 정보를 확인한 뒤 바로 다운로드"
        )

    def _quick_add_url(self) -> None:
        url = self._resolve_input_url()
        if not url:
            return

        task = self._create_quick_placeholder(url)

        # The base page's legacy name says 'external', but this set is the actual
        # analysis-complete auto-start marker consumed by _complete_quick_task().
        # Mark the task before starting analysis so a very fast result cannot race
        # ahead of the auto-download intent.
        self._external_auto_download_task_ids.add(task.task_id)
        self._quick_queue.append((task.task_id, url))

        self.url_input.clear()
        self._show_list_page()
        self.toast.show_message(
            "기본 프리셋으로 목록에 추가하고 자동 다운로드를 준비합니다."
        )
        QTimer.singleShot(0, self.url_input.setFocus)
        self._start_next_quick_request()
