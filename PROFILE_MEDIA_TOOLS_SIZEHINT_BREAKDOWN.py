from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_MEDIA_SIZEHINT_RESULT="


def _timed_size_hint(widget) -> tuple[float, str]:
    started = perf_counter()
    try:
        widget.sizeHint()
        error = ""
    except Exception as exc:
        error = repr(exc)
    return (perf_counter() - started) * 1000.0, error


def _run_child(mode: str) -> int:
    from app.application import create_application
    from ui.pages.media_tools_page import MediaToolsPage

    app = create_application(sys.argv)

    started = perf_counter()
    page = MediaToolsPage()
    ctor_ms = (perf_counter() - started) * 1000.0

    targets = {
        "tool_stack": page.tool_stack,
        "converter": page.converter_page,
        "thumbnail": page.thumbnail_page,
        "snapshot": page.snapshot_page,
        "subtitle": page.subtitle_page,
    }

    target_ms = 0.0
    target_error = ""
    if mode != "baseline":
        target = targets[mode]
        target_ms, target_error = _timed_size_hint(target)

    page_after_ms, page_error = _timed_size_hint(page)
    stack_after_ms, stack_error = _timed_size_hint(page.tool_stack)

    payload = {
        "mode": mode,
        "ctor_ms": ctor_ms,
        "target_ms": target_ms,
        "target_error": target_error,
        "page_after_ms": page_after_ms,
        "page_error": page_error,
        "stack_after_ms": stack_after_ms,
        "stack_error": stack_error,
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False))

    page.deleteLater()
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

    print("RR-V MediaToolsPage sizeHint breakdown probe")
    print("Each case runs in a fresh Python process.")
    print("The normal RR-V app should be closed before running this profiler.")
    print("Product code is not modified by this experiment.")

    modes = (
        "baseline",
        "tool_stack",
        "converter",
        "thumbnail",
        "snapshot",
        "subtitle",
    )
    results = {mode: _run_fresh(mode) for mode in modes}

    print("\nMediaToolsPage sizeHint breakdown")
    print("=" * 112)
    print(
        f"{'case':<16}{'ctor':>14}{'target hint':>18}"
        f"{'page afterwards':>20}{'stack afterwards':>20}"
    )
    print("-" * 112)
    for mode in modes:
        item = results[mode]
        print(
            f"{mode:<16}"
            f"{float(item['ctor_ms']):>13.3f} "
            f"{float(item['target_ms']):>17.3f} "
            f"{float(item['page_after_ms']):>19.3f} "
            f"{float(item['stack_after_ms']):>19.3f}"
        )
    print("=" * 112)

    ranked = sorted(
        (
            (mode, float(results[mode]["target_ms"]), float(results[mode]["page_after_ms"]))
            for mode in modes
            if mode != "baseline"
        ),
        key=lambda item: item[1],
        reverse=True,
    )

    print("\nLargest first sizeHint targets")
    print("-" * 78)
    for index, (mode, target_ms, page_after_ms) in enumerate(ranked, 1):
        print(
            f"{index:2d}. {target_ms:9.3f} ms  {mode:<14} "
            f"MediaTools afterwards {page_after_ms:9.3f} ms"
        )

    baseline_ms = float(results["baseline"]["page_after_ms"])
    if ranked:
        mode, target_ms, page_after_ms = ranked[0]
        if baseline_ms >= 500 and target_ms >= 500 and page_after_ms <= baseline_ms * 0.35:
            print(f"\nVerdict: {mode} absorbs most of MediaToolsPage's cold sizeHint cost.")
            if mode == "tool_stack":
                print("The next target is the stacked widget policy or one of its child pages.")
            else:
                print(f"The next target is the {mode} page's own sizeHint/layout path.")
        else:
            print("\nVerdict: no single measured child fully absorbs the MediaToolsPage cost.")
            print("Inspect cumulative tool_stack/layout behavior next.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
