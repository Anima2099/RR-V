from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter


def _elapsed_ms(started: float) -> float:
    return (perf_counter() - started) * 1000.0


def _run_child(case: str) -> int:
    from app.application import create_application

    app = create_application(sys.argv)

    # DownloadPage import time is intentionally outside the measured constructor
    # interval. The previous profiler also measured only DownloadPage creation.
    from PySide6.QtWidgets import QWidget
    from ui.pages.download_page import DownloadPage

    empty_widget = None
    page = None
    empty_ms: float | None = None

    try:
        if case == "download-first":
            started = perf_counter()
            page = DownloadPage()
            download_ms = _elapsed_ms(started)
        elif case == "widget-first":
            started = perf_counter()
            empty_widget = QWidget()
            empty_widget.setObjectName("rrvQtColdProbe")
            empty_ms = _elapsed_ms(started)

            # Let deferred Qt work caused by the first QWidget settle before the
            # real DownloadPage constructor is measured.
            app.processEvents()

            started = perf_counter()
            page = DownloadPage()
            download_ms = _elapsed_ms(started)
        else:
            raise ValueError(f"Unknown probe case: {case}")

        result = {
            "case": case,
            "empty_widget_ms": empty_ms,
            "download_page_ms": download_ms,
            "task_count": len(getattr(page, "tasks", ()) or ()),
        }
        print("RRV_QT_PROBE_RESULT=" + json.dumps(result, separators=(",", ":")))
    finally:
        if page is not None:
            page.deleteLater()
        if empty_widget is not None:
            empty_widget.deleteLater()
        app.processEvents()
        app.quit()

    return 0


def _launch_case(case: str) -> tuple[dict[str, object], str]:
    script = str(Path(__file__).resolve())
    environment = os.environ.copy()
    environment["PYTHONIOENCODING"] = "utf-8"

    completed = subprocess.run(
        [sys.executable, script, "--case", case],
        cwd=str(Path(script).parent),
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )

    output = completed.stdout or ""
    result: dict[str, object] | None = None
    for line in output.splitlines():
        if not line.startswith("RRV_QT_PROBE_RESULT="):
            continue
        try:
            parsed = json.loads(line.split("=", 1)[1])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            result = parsed
            break

    if completed.returncode != 0 or result is None:
        print(output, end="" if output.endswith("\n") else "\n")
        raise RuntimeError(
            f"Probe child failed for {case} (exit={completed.returncode})."
        )
    return result, output


def _number(result: dict[str, object], key: str) -> float:
    value = result.get(key)
    if value is None:
        return 0.0
    return float(value)


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--case":
        return _run_child(sys.argv[2])

    print("RR-V Qt first-widget cold-start probe")
    print("Each case runs in a fresh Python process.")
    print("No download or Installer is started.\n")

    direct, direct_output = _launch_case("download-first")
    warmed, warmed_output = _launch_case("widget-first")

    print("[A] Fresh process: DownloadPage is the first QWidget tree")
    print("=" * 72)
    print(direct_output, end="" if direct_output.endswith("\n") else "\n")

    print("\n[B] Fresh process: empty QWidget first, then DownloadPage")
    print("=" * 72)
    print(warmed_output, end="" if warmed_output.endswith("\n") else "\n")

    direct_download = _number(direct, "download_page_ms")
    empty_widget = _number(warmed, "empty_widget_ms")
    warmed_download = _number(warmed, "download_page_ms")
    ratio = warmed_download / direct_download if direct_download > 0.0 else 0.0
    shifted_ms = max(0.0, direct_download - warmed_download)

    print("\nCold-start comparison")
    print("=" * 72)
    print(f"A. DownloadPage first             {direct_download:10.3f} ms")
    print(f"B. Empty QWidget first            {empty_widget:10.3f} ms")
    print(f"B. DownloadPage after QWidget     {warmed_download:10.3f} ms")
    print(f"DownloadPage warm/cold ratio      {ratio:10.3f}")
    print(f"Cost shifted away from DownloadPage {shifted_ms:8.3f} ms")

    if direct_download >= 500.0 and ratio <= 0.35 and empty_widget >= 250.0:
        print(
            "Verdict: strong first-QWidget / Qt style initialization signature."
        )
    elif direct_download >= 500.0 and ratio <= 0.35:
        print(
            "Verdict: strong one-time Qt startup signature, but an empty QWidget "
            "does not absorb most of the cost by itself."
        )
    elif direct_download >= 500.0 and ratio >= 0.70:
        print(
            "Verdict: the heavy cost remains inside DownloadPage even after an "
            "empty QWidget exists."
        )
    else:
        print("Verdict: mixed result; inspect both fresh-process timings.")

    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
