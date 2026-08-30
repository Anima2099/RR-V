from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter


ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_CONVERTER_RENDER_RESULT="


def _widget_text(widget) -> str:
    for name in ("text", "currentText", "placeholderText"):
        member = getattr(widget, name, None)
        if callable(member):
            try:
                value = str(member() or "").strip()
            except Exception:
                value = ""
            if value:
                return value
    return ""


def _explicitly_hidden(widget, root) -> bool:
    current = widget
    while current is not None and current is not root:
        try:
            if current.isHidden():
                return True
            current = current.parentWidget()
        except Exception:
            break
    return False


def _describe(widget, text: str) -> str:
    cls = type(widget).__name__
    name = widget.objectName() or "-"
    shown = text.replace("\n", " ")
    if len(shown) > 90:
        shown = shown[:87] + "..."
    return f"{cls} object={name!r} text={shown!r}"


def _collect_text_widgets(page):
    from PySide6.QtWidgets import QWidget

    result = []
    for widget in page.findChildren(QWidget):
        if _explicitly_hidden(widget, page):
            continue
        text = _widget_text(widget)
        if text:
            result.append((widget, text))
    return result


def _run_child(mode: str) -> int:
    from app.application import create_application
    from PySide6.QtWidgets import QStackedWidget
    from ui.tools.converter_page import ConverterPage

    app = create_application(sys.argv)

    started = perf_counter()
    page = ConverterPage()
    ctor_ms = (perf_counter() - started) * 1000.0

    candidates = _collect_text_widgets(page)
    timings: list[dict[str, object]] = []

    if mode == "text_metrics":
        for widget, text in candidates:
            tick = perf_counter()
            try:
                widget.fontMetrics().horizontalAdvance(text)
                error = ""
            except Exception as exc:
                error = repr(exc)
            elapsed = (perf_counter() - tick) * 1000.0
            timings.append(
                {
                    "ms": elapsed,
                    "desc": _describe(widget, text),
                    "error": error,
                }
            )
    elif mode == "size_hints":
        for widget, text in candidates:
            tick = perf_counter()
            try:
                widget.sizeHint()
                error = ""
            except Exception as exc:
                error = repr(exc)
            elapsed = (perf_counter() - tick) * 1000.0
            timings.append(
                {
                    "ms": elapsed,
                    "desc": _describe(widget, text),
                    "error": error,
                }
            )

    stack = QStackedWidget()
    tick = perf_counter()
    stack.addWidget(page)
    stack_add_ms = (perf_counter() - tick) * 1000.0

    timings.sort(key=lambda item: float(item["ms"]), reverse=True)
    top = timings[:15]
    hotspot = top[0] if top else {"ms": 0.0, "desc": "", "error": ""}

    payload = {
        "mode": mode,
        "converter_ctor_ms": ctor_ms,
        "candidate_count": len(candidates),
        "stack_add_ms": stack_add_ms,
        "hotspot": hotspot,
        "top": top,
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False))

    page.deleteLater()
    stack.deleteLater()
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
    print("=" * 88)
    print(completed.stdout.rstrip())
    if completed.returncode != 0:
        raise RuntimeError(f"child {mode!r} exited with {completed.returncode}")

    for line in reversed(completed.stdout.splitlines()):
        if line.startswith(RESULT_PREFIX):
            return json.loads(line[len(RESULT_PREFIX):])
    raise RuntimeError(f"child {mode!r} did not produce a result")


def _print_top(result: dict[str, object]) -> None:
    top = result.get("top") or []
    if not top:
        print("  (no pre-measurement candidates in this case)")
        return
    for index, item in enumerate(top[:10], 1):
        print(f"  {index:2d}. {float(item['ms']):9.3f} ms  {item['desc']}")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _run_child(sys.argv[2])

    print("RR-V ConverterPage render-trigger probe")
    print("Each case runs in a fresh Python process.")
    print("Product code is not modified by this experiment.")

    results = {
        mode: _run_fresh(mode)
        for mode in ("baseline", "text_metrics", "size_hints")
    }

    print("\nConverterPage render-trigger comparison")
    print("=" * 100)
    print(f"{'case':<16}{'ctor':>12}{'candidates':>12}{'pre hotspot':>16}{'stack add':>16}")
    print("-" * 100)
    for mode, result in results.items():
        hotspot = result.get("hotspot") or {}
        print(
            f"{mode:<16}"
            f"{float(result['converter_ctor_ms']):>11.3f} "
            f"{int(result['candidate_count']):>11d} "
            f"{float(hotspot.get('ms', 0.0)):>15.3f} "
            f"{float(result['stack_add_ms']):>15.3f}"
        )
    print("=" * 100)

    for mode in ("text_metrics", "size_hints"):
        print(f"\nTop hotspots: {mode}")
        _print_top(results[mode])

    baseline_add = float(results["baseline"]["stack_add_ms"])
    text_add = float(results["text_metrics"]["stack_add_ms"])
    size_add = float(results["size_hints"]["stack_add_ms"])
    text_hot = float((results["text_metrics"].get("hotspot") or {}).get("ms", 0.0))
    size_hot = float((results["size_hints"].get("hotspot") or {}).get("ms", 0.0))

    if baseline_add >= 500 and text_hot >= 500 and text_add <= baseline_add * 0.35:
        print("Verdict: a specific text/font-metrics calculation absorbs most of the cold-start cost.")
        print("Likely trigger:", (results["text_metrics"].get("hotspot") or {}).get("desc", ""))
    elif baseline_add >= 500 and size_hot >= 500 and size_add <= baseline_add * 0.35:
        print("Verdict: a specific widget sizeHint calculation absorbs most of the cold-start cost.")
        print("Likely trigger:", (results["size_hints"].get("hotspot") or {}).get("desc", ""))
    elif baseline_add >= 500 and min(text_add, size_add) <= baseline_add * 0.35:
        print("Verdict: pre-measuring child widgets moves most of the cost away from stack attachment,")
        print("but no single measured child dominates. Inspect the hotspot list and cumulative layout work.")
    else:
        print("Verdict: text metrics and individual sizeHint calls do not absorb the main cost.")
        print("The next target is container/layout activation or another deferred Qt operation during attachment.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
