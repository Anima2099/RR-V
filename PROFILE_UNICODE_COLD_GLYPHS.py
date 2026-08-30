from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_GLYPH_RESULT="

# Each candidate runs in its own fresh Python process. The widget type mirrors
# the way RR-V currently uses the glyph so one slow glyph cannot warm the font
# fallback cache for the next candidate.
CANDIDATES = (
    ("ascii", "A", "button", "ASCII control"),
    ("retry", "↻", "button", "download retry"),
    ("details_down", "▾", "button", "converter details down"),
    ("details_up", "▴", "button", "converter details up"),
    ("check", "✓", "label", "settings success/normal"),
    ("cross", "✕", "label", "settings missing/error"),
    ("warning", "⚠", "label", "settings warning/repair"),
    ("up_arrow", "↑", "label", "settings update available"),
    ("right_arrow", "→", "label", "converter title"),
    ("triangle_down", "▼", "button", "converter expanded section"),
    ("triangle_right", "▶", "button", "converter collapsed section"),
    ("multiply", "×", "button", "converter remove row"),
    ("down_arrow", "↓", "button", "download bulk path change"),
    ("middle_dot", "·", "label", "common separator control"),
    ("ellipsis", "…", "label", "common ellipsis control"),
)


def _candidate(key: str) -> tuple[str, str, str, str]:
    for candidate in CANDIDATES:
        if candidate[0] == key:
            return candidate
    raise KeyError(key)


def _run_child(key: str) -> int:
    from app.application import create_application
    from PySide6.QtWidgets import QLabel, QPushButton

    app = create_application(sys.argv)
    _key, glyph, widget_kind, note = _candidate(key)

    text = f"테스트 {glyph} 상태"
    widget = QPushButton(text) if widget_kind == "button" else QLabel(text)

    started = perf_counter()
    width = widget.fontMetrics().horizontalAdvance(text)
    metrics_ms = (perf_counter() - started) * 1000.0

    started = perf_counter()
    hint = widget.sizeHint()
    size_hint_ms = (perf_counter() - started) * 1000.0

    payload = {
        "key": key,
        "glyph": glyph,
        "widget": widget_kind,
        "note": note,
        "metrics_ms": metrics_ms,
        "size_hint_ms": size_hint_ms,
        "width": int(width),
        "hint_w": int(hint.width()),
        "hint_h": int(hint.height()),
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False))

    widget.deleteLater()
    app.processEvents()
    app.quit()
    return 0


def _run_fresh(key: str) -> dict[str, object]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--child", key],
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        print(completed.stdout.rstrip())
        raise RuntimeError(f"glyph child {key!r} exited with {completed.returncode}")

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    print(completed.stdout.rstrip())
    raise RuntimeError(f"glyph child {key!r} did not produce a result")


def _classify(ms: float) -> str:
    if ms >= 500.0:
        return "BOMB"
    if ms >= 100.0:
        return "SLOW"
    return "ok"


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _run_child(sys.argv[2])

    print("RR-V Unicode cold-glyph probe")
    print("Every glyph is measured in a fresh Python process.")
    print("The product code is not modified by this experiment.")
    print("This can take a little while because known slow glyphs may each cost ~2 seconds.\n")

    results = [_run_fresh(key) for key, _glyph, _widget, _note in CANDIDATES]
    results.sort(key=lambda item: float(item["metrics_ms"]), reverse=True)

    print("Unicode cold-glyph comparison")
    print("=" * 108)
    print(
        f"{'rank':>4}  {'glyph':^7}  {'widget':<7}  {'metrics':>11}  {'sizeHint':>11}  "
        f"{'class':<6}  usage"
    )
    print("-" * 108)
    for index, result in enumerate(results, 1):
        metrics_ms = float(result["metrics_ms"])
        print(
            f"{index:>4}  {str(result['glyph']):^7}  {str(result['widget']):<7}  "
            f"{metrics_ms:>10.3f} ms  {float(result['size_hint_ms']):>10.3f} ms  "
            f"{_classify(metrics_ms):<6}  {result['note']}"
        )
    print("=" * 108)

    bombs = [result for result in results if float(result["metrics_ms"]) >= 500.0]
    slow = [
        result
        for result in results
        if 100.0 <= float(result["metrics_ms"]) < 500.0
    ]

    if bombs:
        print("Replace these decorative glyphs first:")
        for result in bombs:
            print(
                f"  {result['glyph']}  {float(result['metrics_ms']):.1f} ms  "
                f"({result['note']})"
            )
    else:
        print("No >=500 ms cold glyphs were found in this candidate set.")

    if slow:
        print("Noticeable but secondary candidates:")
        for result in slow:
            print(
                f"  {result['glyph']}  {float(result['metrics_ms']):.1f} ms  "
                f"({result['note']})"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
