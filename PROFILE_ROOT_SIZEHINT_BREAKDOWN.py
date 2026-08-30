from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_ROOT_SIZEHINT_RESULT="


def _time_call(name: str, func) -> tuple[float, str]:
    started = perf_counter()
    error = ""
    try:
        func()
    except Exception as exc:  # profiler only
        error = repr(exc)
    return (perf_counter() - started) * 1000.0, error


def _run_child(mode: str) -> int:
    from app.application import create_application
    from ui.main_window import MainWindow

    app = create_application(sys.argv)

    ctor_started = perf_counter()
    window = MainWindow()
    ctor_ms = (perf_counter() - ctor_started) * 1000.0
    window.show_page(0)

    root = window.centralWidget()
    if root is None:
        raise RuntimeError("MainWindow centralWidget is missing")

    targets = {
        "root": root,
        "root_layout": root.layout(),
        "sidebar": window.sidebar,
        "pages": window.pages,
        "download": window.download_page,
        "media_tools": window.media_tools_page,
        "settings": window.settings_page,
        "about": window.about_page,
    }

    target_ms = 0.0
    target_error = ""
    if mode != "baseline":
        target = targets[mode]
        if target is None:
            raise RuntimeError(f"target {mode!r} is missing")
        target_ms, target_error = _time_call(
            mode,
            target.sizeHint,
        )

    root_ms, root_error = _time_call("root", root.sizeHint)

    show_started = perf_counter()
    window.show()
    show_ms = (perf_counter() - show_started) * 1000.0

    events_started = perf_counter()
    app.processEvents()
    first_events_ms = (perf_counter() - events_started) * 1000.0

    payload = {
        "mode": mode,
        "main_window_ctor_ms": ctor_ms,
        "target_ms": target_ms,
        "target_error": target_error,
        "root_after_ms": root_ms,
        "root_error": root_error,
        "show_ms": show_ms,
        "events_ms": first_events_ms,
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False))

    window.deleteLater()
    app.processEvents()
    app.quit()
    return 0


def _run_fresh(mode: str) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", mode],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    print(f"\n[{mode}] fresh process")
    print("=" * 100)
    print(completed.stdout.rstrip())
    if completed.returncode != 0:
        raise RuntimeError(f"child {mode!r} exited with {completed.returncode}")

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    raise RuntimeError(f"child {mode!r} did not produce a result")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _run_child(sys.argv[2])

    print("RR-V rootWidget sizeHint breakdown probe")
    print("Each case runs in a fresh Python process.")
    print("The normal RR-V app should be closed before running this profiler.")
    print("Product code is not modified by this experiment.")

    modes = (
        "baseline",
        "root_layout",
        "sidebar",
        "pages",
        "download",
        "media_tools",
        "settings",
        "about",
    )
    results = {mode: _run_fresh(mode) for mode in modes}

    print("\nrootWidget sizeHint breakdown")
    print("=" * 112)
    print(
        f"{'case':<16}"
        f"{'MW ctor':>12}"
        f"{'target hint':>16}"
        f"{'root after':>16}"
        f"{'show':>14}"
        f"{'events':>14}"
    )
    print("-" * 112)
    for mode in modes:
        result = results[mode]
        print(
            f"{mode:<16}"
            f"{float(result['main_window_ctor_ms']):>11.3f} "
            f"{float(result['target_ms']):>15.3f} "
            f"{float(result['root_after_ms']):>15.3f} "
            f"{float(result['show_ms']):>13.3f} "
            f"{float(result['events_ms']):>13.3f}"
        )
    print("=" * 112)

    candidates: list[tuple[float, str, float]] = []
    for mode in modes:
        if mode == "baseline":
            continue
        result = results[mode]
        target_ms = float(result["target_ms"])
        root_after_ms = float(result["root_after_ms"])
        candidates.append((target_ms, mode, root_after_ms))

    candidates.sort(reverse=True)
    print("\nLargest first sizeHint targets")
    print("-" * 78)
    for rank, (target_ms, mode, root_after_ms) in enumerate(candidates, 1):
        print(
            f"{rank:2d}. {target_ms:9.3f} ms  {mode:<16}"
            f"root afterwards {root_after_ms:9.3f} ms"
        )

    if candidates:
        target_ms, mode, root_after_ms = candidates[0]
        if target_ms >= 500 and root_after_ms <= 100:
            print(
                f"\nVerdict: {mode} absorbs most of rootWidget's cold sizeHint cost."
            )
            if mode == "pages":
                print(
                    "The next experiment should test whether the main QStackedWidget is "
                    "measuring hidden pages unnecessarily."
                )
            else:
                print(
                    f"The next experiment should decompose {mode}'s own layout/children."
                )
        else:
            print(
                "\nVerdict: no single top-level child fully absorbs the rootWidget cost."
            )
            print(
                "The next target is root layout activation or a cumulative combination of children."
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
