from __future__ import annotations

import sys
from collections import defaultdict
from time import perf_counter
from typing import Any, Callable

from app.application import create_application


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def main() -> int:
    app = create_application(sys.argv)

    # 제품 코드는 바꾸지 않는다. 이 프로세스 안에서만 DownloadPage가 참조하는
    # 생성자와 초기화 함수를 잠시 감싸서 시작 비용을 세분화한다.
    import ui.pages.download_page as module

    timings: dict[int, dict[str, float]] = {
        1: defaultdict(float),
        2: defaultdict(float),
    }
    counts: dict[int, dict[str, int]] = {
        1: defaultdict(int),
        2: defaultdict(int),
    }
    active_run = {"id": 1}
    phase = {"name": "upper"}

    def record(name: str, duration_ms: float) -> None:
        run_id = active_run["id"]
        timings[run_id][name] += duration_ms
        counts[run_id][name] += 1

    def wrap_function(name: str, function: Callable[..., Any]) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                record(name, _elapsed_ms(started))

        return wrapped

    def wrap_current_phase_function(
        label: str,
        function: Callable[..., Any],
    ) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                record(f"{phase['name']}.{label}", _elapsed_ms(started))

        return wrapped

    def wrap_phase_function(
        name: str,
        phase_name: str,
        function: Callable[..., Any],
    ) -> Callable[..., Any]:
        def wrapped(*args: Any, **kwargs: Any) -> Any:
            previous = phase["name"]
            phase["name"] = phase_name
            started = perf_counter()
            try:
                return function(*args, **kwargs)
            finally:
                record(name, _elapsed_ms(started))
                phase["name"] = previous

        return wrapped

    def timed_class(label: str, base: type) -> type:
        class Timed(base):  # type: ignore[misc, valid-type]
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                started = perf_counter()
                try:
                    super().__init__(*args, **kwargs)
                finally:
                    record(f"{phase['name']}.{label}", _elapsed_ms(started))

        Timed.__name__ = f"Timed{getattr(base, '__name__', label)}"
        return Timed

    originals = {
        "load_general_preferences": module.load_general_preferences,
        "load_queue": module.load_queue,
        "resolved_download_directory": module.resolved_download_directory,
        "DownloadController": module.DownloadController,
        "DownloadTaskList": module.DownloadTaskList,
        "PreviewPanel": module.PreviewPanel,
        "ToastMessage": module.ToastMessage,
        "QTimer": module.QTimer,
        "QWidget": module.QWidget,
        "QVBoxLayout": module.QVBoxLayout,
        "QHBoxLayout": module.QHBoxLayout,
        "QLabel": module.QLabel,
        "QLineEdit": module.QLineEdit,
        "QPushButton": module.QPushButton,
        "QStackedWidget": module.QStackedWidget,
        "QToolButton": module.QToolButton,
        "QScrollArea": module.QScrollArea,
        "QButtonGroup": module.QButtonGroup,
        "create_card": module.create_card,
        "_create_list_page": module.DownloadPage._create_list_page,
        "_create_editor_page": module.DownloadPage._create_editor_page,
        "_install_txt_drop_support": module.DownloadPage._install_txt_drop_support,
        "_refresh_list_state": module.DownloadPage._refresh_list_state,
    }

    module.load_general_preferences = wrap_function(
        "preferences.load_general", originals["load_general_preferences"]
    )
    module.load_queue = wrap_function("queue.load", originals["load_queue"])
    module.resolved_download_directory = wrap_function(
        "preferences.resolve_download_directory",
        originals["resolved_download_directory"],
    )

    module.DownloadController = timed_class(
        "controller", originals["DownloadController"]
    )
    module.DownloadTaskList = timed_class(
        "download_task_list", originals["DownloadTaskList"]
    )
    module.PreviewPanel = timed_class(
        "preview_panel", originals["PreviewPanel"]
    )
    module.ToastMessage = timed_class(
        "toast_message", originals["ToastMessage"]
    )
    module.QTimer = timed_class("qtimer", originals["QTimer"])
    module.QWidget = timed_class("qwidget", originals["QWidget"])
    module.QVBoxLayout = timed_class("qvboxlayout", originals["QVBoxLayout"])
    module.QHBoxLayout = timed_class("qhboxlayout", originals["QHBoxLayout"])
    module.QLabel = timed_class("qlabel", originals["QLabel"])
    module.QLineEdit = timed_class("qlineedit", originals["QLineEdit"])
    module.QPushButton = timed_class("qpushbutton", originals["QPushButton"])
    module.QStackedWidget = timed_class(
        "qstackedwidget", originals["QStackedWidget"]
    )
    module.QToolButton = timed_class("qtoolbutton", originals["QToolButton"])
    module.QScrollArea = timed_class("qscrollarea", originals["QScrollArea"])
    module.QButtonGroup = timed_class("qbuttongroup", originals["QButtonGroup"])
    module.create_card = wrap_current_phase_function(
        "create_card", originals["create_card"]
    )

    module.DownloadPage._create_list_page = wrap_phase_function(
        "list.page_total", "list", originals["_create_list_page"]
    )
    module.DownloadPage._create_editor_page = wrap_phase_function(
        "editor.page_total", "editor", originals["_create_editor_page"]
    )
    module.DownloadPage._install_txt_drop_support = wrap_function(
        "startup.txt_drop_support", originals["_install_txt_drop_support"]
    )
    module.DownloadPage._refresh_list_state = wrap_function(
        "startup.final_refresh", originals["_refresh_list_state"]
    )

    def create_page(run_id: int) -> tuple[Any, float]:
        active_run["id"] = run_id
        phase["name"] = "upper"
        started = perf_counter()
        page = module.DownloadPage()
        return page, _elapsed_ms(started)

    page1 = None
    page2 = None
    try:
        page1, total1 = create_page(1)
        page1.deleteLater()
        page1 = None
        app.processEvents()

        # 같은 QApplication 안에서 한 번 더 만든다. 두 번째가 급격히 빨라지면
        # Qt/Windows의 첫 위젯, 폰트, 스타일 준비 같은 1회성 비용일 가능성이 높다.
        page2, total2 = create_page(2)

        widget_labels = (
            "toast_message",
            "qtimer",
            "qwidget",
            "qvboxlayout",
            "qhboxlayout",
            "qlabel",
            "qlineedit",
            "qpushbutton",
            "qstackedwidget",
            "qtoolbutton",
            "qscrollarea",
            "qbuttongroup",
            "create_card",
        )

        def print_run(run_id: int, total_ms: float, title: str) -> None:
            data = timings[run_id]
            run_counts = counts[run_id]
            exclusive_names = (
                "preferences.load_general",
                "queue.load",
                "preferences.resolve_download_directory",
                "list.page_total",
                "editor.page_total",
                "startup.txt_drop_support",
                "startup.final_refresh",
            )
            # controller는 upper.controller라는 생성자 계측에 기록된다.
            categorized_ms = sum(data[name] for name in exclusive_names)
            categorized_ms += data["upper.controller"]
            upper_other_ms = max(0.0, total_ms - categorized_ms)

            print(f"\n{title}")
            print("=" * 76)
            print(f"DownloadPage total                       {total_ms:10.3f} ms")
            print(f"  preferences.load_general               {data['preferences.load_general']:10.3f} ms")
            print(f"  queue.load                              {data['queue.load']:10.3f} ms")
            print(f"  preferences.resolve_download_directory {data['preferences.resolve_download_directory']:10.3f} ms")
            print(f"  controller.create                      {data['upper.controller']:10.3f} ms")
            print(f"  list.page_total                        {data['list.page_total']:10.3f} ms")
            print(f"    list.download_task_list              {data['list.download_task_list']:10.3f} ms")
            print(f"  editor.page_total                      {data['editor.page_total']:10.3f} ms")
            print(f"    editor.preview_panel                 {data['editor.preview_panel']:10.3f} ms")
            print(f"  startup.txt_drop_support               {data['startup.txt_drop_support']:10.3f} ms")
            print(f"  startup.final_refresh                  {data['startup.final_refresh']:10.3f} ms")
            print(f"  upper/residual                         {upper_other_ms:10.3f} ms")
            print("  -- upper constructor detail --")
            for label in widget_labels:
                name = f"upper.{label}"
                duration = data[name]
                count = run_counts[name]
                if duration > 0.0 or count:
                    print(f"    {name:<34} {duration:9.3f} ms  calls={count}")
            print("=" * 76)

        print("\nRR-V DownloadPage startup deep profile")
        print_run(1, total1, "[1] Cold creation")
        print_run(2, total2, "[2] Warm creation in same process")

        ratio = (total2 / total1) if total1 > 0 else 0.0
        print(f"\nWarm / cold ratio: {ratio:.3f}")
        if total1 >= 500.0 and ratio <= 0.35:
            print("Interpretation: strong one-time Qt/Windows startup cost signature.")
        elif total1 >= 500.0 and ratio >= 0.70:
            print("Interpretation: most cost repeats on every DownloadPage creation.")
        else:
            print("Interpretation: mixed startup cost; inspect the upper constructor detail.")
        print(f"Restored task count: {len(getattr(page2, 'tasks', ()) or ()) if page2 is not None else 0}")
        print("Profiler only: no download or Installer was started.")
    finally:
        if page1 is not None:
            page1.deleteLater()
        if page2 is not None:
            page2.deleteLater()
        app.processEvents()
        app.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
