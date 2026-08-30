from __future__ import annotations

import sys
from collections import defaultdict
from time import perf_counter
from typing import Any, Callable

from app.application import create_application


def _milliseconds(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def main() -> int:
    app = create_application(sys.argv)

    # QApplication과 RR-V 테마가 준비된 뒤 실제 DownloadPage 모듈을 불러온다.
    # 이 스크립트는 제품 코드를 바꾸지 않고, 이 프로세스 안에서만 생성자와
    # 초기화 함수를 잠깐 감싸서 어느 구간이 시작 시간을 쓰는지 측정한다.
    import ui.pages.download_page as download_page_module

    timings: dict[str, float] = defaultdict(float)
    counts: dict[str, int] = defaultdict(int)

    def wrap_function(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                timings[name] += _milliseconds(started)
                counts[name] += 1

        return wrapped

    original_load_general_preferences = download_page_module.load_general_preferences
    original_load_queue = download_page_module.load_queue
    original_resolved_download_directory = download_page_module.resolved_download_directory
    original_controller = download_page_module.DownloadController
    original_task_list = download_page_module.DownloadTaskList
    original_preview_panel = download_page_module.PreviewPanel
    original_create_list_page = download_page_module.DownloadPage._create_list_page
    original_create_editor_page = download_page_module.DownloadPage._create_editor_page
    original_install_txt_drop_support = download_page_module.DownloadPage._install_txt_drop_support
    original_refresh_list_state = download_page_module.DownloadPage._refresh_list_state

    download_page_module.load_general_preferences = wrap_function(
        "preferences.load_general", original_load_general_preferences
    )
    download_page_module.load_queue = wrap_function("queue.load", original_load_queue)
    download_page_module.resolved_download_directory = wrap_function(
        "preferences.resolve_download_directory", original_resolved_download_directory
    )

    class TimedDownloadController(original_controller):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            started = perf_counter()
            try:
                super().__init__(*args, **kwargs)
            finally:
                timings["controller.create"] += _milliseconds(started)
                counts["controller.create"] += 1

    class TimedDownloadTaskList(original_task_list):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            started = perf_counter()
            try:
                super().__init__(*args, **kwargs)
            finally:
                timings["list.task_list"] += _milliseconds(started)
                counts["list.task_list"] += 1

    class TimedPreviewPanel(original_preview_panel):
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            started = perf_counter()
            try:
                super().__init__(*args, **kwargs)
            finally:
                timings["editor.preview_panel"] += _milliseconds(started)
                counts["editor.preview_panel"] += 1

    download_page_module.DownloadController = TimedDownloadController
    download_page_module.DownloadTaskList = TimedDownloadTaskList
    download_page_module.PreviewPanel = TimedPreviewPanel
    download_page_module.DownloadPage._create_list_page = wrap_function(
        "list.page_total", original_create_list_page
    )
    download_page_module.DownloadPage._create_editor_page = wrap_function(
        "editor.page_total", original_create_editor_page
    )
    download_page_module.DownloadPage._install_txt_drop_support = wrap_function(
        "startup.txt_drop_support", original_install_txt_drop_support
    )
    download_page_module.DownloadPage._refresh_list_state = wrap_function(
        "startup.final_refresh", original_refresh_list_state
    )

    page = None
    total_started = perf_counter()
    try:
        page = download_page_module.DownloadPage()
    finally:
        total_ms = _milliseconds(total_started)

        # 중첩되지 않는 큰 구간만 빼서 상단 URL UI와 상태 변수 준비 등
        # 아직 따로 이름 붙이지 않은 초기화 비용도 대략 확인한다.
        exclusive_names = (
            "preferences.load_general",
            "queue.load",
            "preferences.resolve_download_directory",
            "controller.create",
            "list.page_total",
            "editor.page_total",
            "startup.txt_drop_support",
            "startup.final_refresh",
        )
        categorized_ms = sum(timings[name] for name in exclusive_names)
        other_ms = max(0.0, total_ms - categorized_ms)

        print("\nRR-V DownloadPage startup profile")
        print("=" * 66)
        print(f"DownloadPage total                     {total_ms:10.3f} ms")
        print(f"  preferences.load_general             {timings['preferences.load_general']:10.3f} ms")
        print(f"  queue.load                            {timings['queue.load']:10.3f} ms")
        print(f"  preferences.resolve_download_directory {timings['preferences.resolve_download_directory']:8.3f} ms")
        print(f"  controller.create                    {timings['controller.create']:10.3f} ms")
        print(f"  list.page_total                      {timings['list.page_total']:10.3f} ms")
        print(f"    list.task_list                     {timings['list.task_list']:10.3f} ms")
        print(f"  editor.page_total                    {timings['editor.page_total']:10.3f} ms")
        print(f"    editor.preview_panel               {timings['editor.preview_panel']:10.3f} ms")
        print(f"  startup.txt_drop_support             {timings['startup.txt_drop_support']:10.3f} ms")
        print(f"  startup.final_refresh                {timings['startup.final_refresh']:10.3f} ms")
        print(f"  other init / upper URL UI            {other_ms:10.3f} ms")
        print("=" * 66)
        print(f"Restored task count: {len(getattr(page, 'tasks', ()) or ()) if page is not None else 0}")
        print("Profiler only: no download or Installer was started.")

    if page is not None:
        page.deleteLater()
        app.processEvents()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
