from __future__ import annotations

import importlib
import json
import os
import statistics
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_FULL_STARTUP_RESULT="
RUN_COUNT = 3


def _run_child() -> int:
    sys.dont_write_bytecode = True
    script_started = perf_counter()
    phases: list[dict[str, float | str]] = []

    def measure(name: str, func):
        started = perf_counter()
        result = func()
        elapsed = (perf_counter() - started) * 1000.0
        phases.append({"name": name, "ms": elapsed})
        return result

    # main.py의 실제 import 순서를 최대한 그대로 따라간다.
    native_host = measure(
        "import.services.native_messaging_host",
        lambda: importlib.import_module("services.native_messaging_host"),
    )
    if native_host.is_native_messaging_invocation(sys.argv[1:]):
        raise RuntimeError("Profiler must not run in Native Messaging mode")

    qtcore = measure(
        "import.PySide6.QtCore",
        lambda: importlib.import_module("PySide6.QtCore"),
    )
    application = measure(
        "import.app.application",
        lambda: importlib.import_module("app.application"),
    )
    general_preferences = measure(
        "import.app.general_preferences",
        lambda: importlib.import_module("app.general_preferences"),
    )
    cookie_work_file = measure(
        "import.services.cookie_work_file",
        lambda: importlib.import_module("services.cookie_work_file"),
    )
    external_url_module = measure(
        "import.services.external_url_service",
        lambda: importlib.import_module("services.external_url_service"),
    )
    windows_startup = measure(
        "import.services.windows_startup_service",
        lambda: importlib.import_module("services.windows_startup_service"),
    )
    browser_integration = measure(
        "import.services.browser_integration_service",
        lambda: importlib.import_module("services.browser_integration_service"),
    )
    measure(
        "import.ui.dialogs.warm_dialogs",
        lambda: importlib.import_module("ui.dialogs.warm_dialogs"),
    )

    # create_application()을 같은 순서로 풀어서 내부 단계를 따로 잰다.
    application_started = perf_counter()
    measure("app.performance_log", application.initialize_performance_log)
    app = measure(
        "app.QApplication",
        lambda: application.QApplication([sys.argv[0]]),
    )

    def configure_metadata_style() -> None:
        app.setApplicationName(application.APP_NAME)
        app.setApplicationVersion(application.APP_VERSION)
        app.setOrganizationName(application.ORGANIZATION_NAME)
        if application.APP_ICON_PATH.is_file():
            app.setWindowIcon(application.QIcon(str(application.APP_ICON_PATH)))
        app.setStyle("Fusion")

    measure("app.metadata_icon_fusion", configure_metadata_style)

    def init_settings() -> None:
        try:
            application.initialize_settings_store()
        except OSError:
            pass

    measure("app.settings_store", init_settings)
    measure("app.theme_initialize", application.initialize_active_theme)

    def daily_backup() -> None:
        try:
            application.ensure_daily_auto_backup()
        except OSError:
            pass

    measure("app.daily_backup", daily_backup)
    app_font = measure("app.choose_font", application.choose_application_font)
    measure("app.set_font", lambda: app.setFont(app_font))
    measure("app.palette", lambda: application.apply_active_palette(app))
    stylesheet = measure("app.load_theme", application.load_theme)
    measure("app.set_stylesheet", lambda: app.setStyleSheet(stylesheet))
    measure("app.preload_icons", application.preload_task_icons)
    create_application_ms = (perf_counter() - application_started) * 1000.0

    # main()의 primary 프로세스 준비 경로.
    external_service = measure(
        "startup.external_service_ctor",
        lambda: external_url_module.ExternalUrlService(app),
    )
    became_primary = measure(
        "startup.primary_lock",
        external_service.try_become_primary,
    )
    if not became_primary:
        external_service.close()
        app.quit()
        raise RuntimeError(
            "Another RR-V instance appears to be running. Close RR-V and run the profiler again."
        )

    measure(
        "startup.cookie_cleanup",
        cookie_work_file.cleanup_stale_cookie_work_directories,
    )
    prefs = measure(
        "startup.load_general_preferences",
        general_preferences.load_general_preferences,
    )

    def sync_browser() -> None:
        try:
            browser_integration.sync_browser_integration_registration()
        except Exception:
            pass

    measure("startup.browser_registration", sync_browser)

    if getattr(prefs, "start_with_windows", False):
        def sync_windows() -> None:
            try:
                windows_startup.sync_windows_startup_registration(
                    True,
                    start_hidden=getattr(prefs, "minimize_to_tray_on_close", False),
                )
            except windows_startup.WindowsStartupError:
                pass

        measure("startup.windows_registration", sync_windows)

    main_window_module = measure(
        "import.ui.main_window",
        lambda: importlib.import_module("ui.main_window"),
    )
    window = measure("startup.MainWindow_ctor", main_window_module.MainWindow)
    external_service.request_received.connect(window.handle_external_request)

    measure("startup.window_show", window.show)
    measure("startup.first_process_events", app.processEvents)
    measure("startup.second_process_events", app.processEvents)

    first_paint_ms = (perf_counter() - script_started) * 1000.0

    payload = {
        "script_to_first_paint_ms": first_paint_ms,
        "create_application_ms": create_application_ms,
        "phase_count": len(phases),
        "phases": phases,
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False), flush=True)

    external_service.close()
    window.deleteLater()
    app.processEvents()
    app.quit()
    return 0


def _run_fresh(index: int) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    started = perf_counter()
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child"],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    process_wall_ms = (perf_counter() - started) * 1000.0

    print(f"\n[PASS {index}] fresh Python process")
    print("=" * 100)
    print(completed.stdout.rstrip())
    if completed.returncode != 0:
        raise RuntimeError(f"pass {index} exited with {completed.returncode}")

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            result = json.loads(line[len(RESULT_PREFIX):])
            result["process_wall_ms"] = process_wall_ms
            return result
    raise RuntimeError(f"pass {index} did not produce a result")


def _phase_map(result: dict[str, object]) -> dict[str, float]:
    return {
        str(item["name"]): float(item["ms"])
        for item in result.get("phases", [])
    }


def main() -> int:
    if len(sys.argv) >= 2 and sys.argv[1] == "--child":
        return _run_child()

    print("RR-V full startup timeline probe")
    print("Close the normal RR-V app before running this profiler.")
    print("Three fresh Python processes are measured to show cold/warm OS cache effects.")
    print("The profiler shows the RR-V window briefly, then closes it automatically.")
    print("No download, conversion, installer, or update is started.")

    results = [_run_fresh(index) for index in range(1, RUN_COUNT + 1)]
    maps = [_phase_map(result) for result in results]
    all_names: list[str] = []
    for phase_map in maps:
        for name in phase_map:
            if name not in all_names:
                all_names.append(name)

    print("\nFull startup timeline")
    print("=" * 124)
    print(
        f"{'phase':<42}"
        f"{'pass1':>14}"
        f"{'pass2':>14}"
        f"{'pass3':>14}"
        f"{'median':>14}"
    )
    print("-" * 124)
    for name in all_names:
        values = [phase_map.get(name, 0.0) for phase_map in maps]
        print(
            f"{name:<42}"
            f"{values[0]:>13.3f} "
            f"{values[1]:>13.3f} "
            f"{values[2]:>13.3f} "
            f"{statistics.median(values):>13.3f}"
        )

    print("-" * 124)
    for key, label in (
        ("create_application_ms", "create_application expanded total"),
        ("script_to_first_paint_ms", "script start -> first paint"),
        ("process_wall_ms", "parent-observed process wall"),
    ):
        values = [float(result[key]) for result in results]
        print(
            f"{label:<42}"
            f"{values[0]:>13.3f} "
            f"{values[1]:>13.3f} "
            f"{values[2]:>13.3f} "
            f"{statistics.median(values):>13.3f}"
        )
    print("=" * 124)

    median_phases = []
    for name in all_names:
        values = [phase_map.get(name, 0.0) for phase_map in maps]
        median_phases.append((statistics.median(values), name))
    median_phases.sort(reverse=True)

    print("\nLargest median phases")
    print("-" * 78)
    for rank, (value, name) in enumerate(median_phases[:12], 1):
        print(f"{rank:>2}. {value:9.3f} ms  {name}")

    known_median = statistics.median(
        float(result["script_to_first_paint_ms"]) for result in results
    )
    main_window_median = statistics.median(
        phase_map.get("startup.MainWindow_ctor", 0.0) for phase_map in maps
    )
    import_main_window_median = statistics.median(
        phase_map.get("import.ui.main_window", 0.0) for phase_map in maps
    )
    create_app_median = statistics.median(
        float(result["create_application_ms"]) for result in results
    )

    print("\nCheckpoint summary")
    print("-" * 78)
    print(f"create_application median : {create_app_median:9.3f} ms")
    print(f"MainWindow import median  : {import_main_window_median:9.3f} ms")
    print(f"MainWindow ctor median    : {main_window_median:9.3f} ms")
    print(f"script -> first paint     : {known_median:9.3f} ms")
    print("Use the 'Largest median phases' list as the next optimization target.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
