from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from time import perf_counter

ROOT = Path(__file__).resolve().parent
RESULT_PREFIX = "RRV_STARTUP_NEXT_RESULT="


def _widget_text(widget) -> str:
    for name in ("text", "currentText", "placeholderText", "title"):
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


def _describe(widget, text: str = "") -> str:
    cls = type(widget).__name__
    try:
        name = widget.objectName() or "-"
    except Exception:
        name = "-"
    shown = text.replace("\n", " ")
    if len(shown) > 100:
        shown = shown[:97] + "..."
    return f"{cls} object={name!r} text={shown!r}"


def _collect_visible_widgets(window):
    from PySide6.QtWidgets import QWidget

    widgets = []
    for widget in window.findChildren(QWidget):
        if _explicitly_hidden(widget, window):
            continue
        widgets.append(widget)
    return widgets


def _direct_application_font():
    from PySide6.QtGui import QFont
    from app.constants import DEFAULT_FONT_SIZE

    font = QFont("Malgun Gothic")
    font.setPointSize(DEFAULT_FONT_SIZE)
    font.setWeight(QFont.Weight.Normal)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def _run_child(mode: str) -> int:
    child_started = perf_counter()

    import app.application as application_module

    if mode == "direct_font":
        application_module.choose_application_font = _direct_application_font

    tick = perf_counter()
    app = application_module.create_application(sys.argv)
    create_application_ms = (perf_counter() - tick) * 1000.0

    tick = perf_counter()
    from ui.main_window import MainWindow
    main_window_import_ms = (perf_counter() - tick) * 1000.0

    tick = perf_counter()
    window = MainWindow()
    main_window_ctor_ms = (perf_counter() - tick) * 1000.0

    candidates = _collect_visible_widgets(window)
    timings: list[dict[str, object]] = []
    premeasure_ms = 0.0

    if mode == "pre_text":
        tick_all = perf_counter()
        for widget in candidates:
            text = _widget_text(widget)
            if not text:
                continue
            tick = perf_counter()
            try:
                widget.fontMetrics().horizontalAdvance(text)
                error = ""
            except Exception as exc:
                error = repr(exc)
            elapsed = (perf_counter() - tick) * 1000.0
            timings.append({"ms": elapsed, "desc": _describe(widget, text), "error": error})
        premeasure_ms = (perf_counter() - tick_all) * 1000.0

    elif mode == "pre_size":
        tick_all = perf_counter()
        for widget in candidates:
            text = _widget_text(widget)
            tick = perf_counter()
            try:
                widget.sizeHint()
                error = ""
            except Exception as exc:
                error = repr(exc)
            elapsed = (perf_counter() - tick) * 1000.0
            timings.append({"ms": elapsed, "desc": _describe(widget, text), "error": error})
        premeasure_ms = (perf_counter() - tick_all) * 1000.0

    tick = perf_counter()
    window.show()
    show_ms = (perf_counter() - tick) * 1000.0

    tick = perf_counter()
    app.processEvents()
    first_events_ms = (perf_counter() - tick) * 1000.0

    tick = perf_counter()
    app.processEvents()
    second_events_ms = (perf_counter() - tick) * 1000.0

    total_ms = (perf_counter() - child_started) * 1000.0

    timings.sort(key=lambda item: float(item["ms"]), reverse=True)
    top = timings[:15]
    hotspot = top[0] if top else {"ms": 0.0, "desc": "", "error": ""}

    payload = {
        "mode": mode,
        "create_application_ms": create_application_ms,
        "main_window_import_ms": main_window_import_ms,
        "main_window_ctor_ms": main_window_ctor_ms,
        "candidate_count": len(candidates),
        "premeasure_ms": premeasure_ms,
        "hotspot": hotspot,
        "top": top,
        "show_ms": show_ms,
        "first_events_ms": first_events_ms,
        "second_events_ms": second_events_ms,
        "total_ms": total_ms,
    }
    print(RESULT_PREFIX + json.dumps(payload, ensure_ascii=False))

    try:
        window._force_exit = True
    except Exception:
        pass
    window.close()
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


def _print_top(result: dict[str, object]) -> None:
    top = result.get("top") or []
    if not top:
        print("  (no pre-measurement in this case)")
        return
    for index, item in enumerate(top[:10], 1):
        print(f"  {index:2d}. {float(item['ms']):9.3f} ms  {item['desc']}")


def main() -> int:
    if len(sys.argv) >= 3 and sys.argv[1] == "--child":
        return _run_child(sys.argv[2])

    print("RR-V startup next-target probe")
    print("Each case runs in a fresh Python process.")
    print("The normal RR-V app should be closed before running this profiler.")
    print("Product code is not modified by this experiment.")

    modes = ("baseline", "direct_font", "pre_text", "pre_size")
    results = {mode: _run_fresh(mode) for mode in modes}

    print("\nStartup next-target comparison")
    print("=" * 122)
    print(
        f"{'case':<14}{'create app':>14}{'MW import':>12}{'MW ctor':>12}"
        f"{'premeasure':>14}{'hotspot':>12}{'show':>12}{'events':>12}{'total':>12}"
    )
    print("-" * 122)
    for mode in modes:
        result = results[mode]
        hotspot = result.get("hotspot") or {}
        print(
            f"{mode:<14}"
            f"{float(result['create_application_ms']):>13.3f} "
            f"{float(result['main_window_import_ms']):>11.3f} "
            f"{float(result['main_window_ctor_ms']):>11.3f} "
            f"{float(result['premeasure_ms']):>13.3f} "
            f"{float(hotspot.get('ms', 0.0)):>11.3f} "
            f"{float(result['show_ms']):>11.3f} "
            f"{float(result['first_events_ms']):>11.3f} "
            f"{float(result['total_ms']):>11.3f}"
        )
    print("=" * 122)

    for mode in ("pre_text", "pre_size"):
        print(f"\nTop hotspots: {mode}")
        _print_top(results[mode])

    baseline = results["baseline"]
    direct = results["direct_font"]
    pre_text = results["pre_text"]
    pre_size = results["pre_size"]

    baseline_total = float(baseline["total_ms"])
    direct_total = float(direct["total_ms"])
    baseline_show = float(baseline["show_ms"])
    text_show = float(pre_text["show_ms"])
    size_show = float(pre_size["show_ms"])
    text_hot = float((pre_text.get("hotspot") or {}).get("ms", 0.0))
    size_hot = float((pre_size.get("hotspot") or {}).get("ms", 0.0))

    print("\nVerdict hints")
    print("-" * 100)
    print(f"Direct-font end-to-end saving: {baseline_total - direct_total:.3f} ms")
    print(f"Pre-text show saving         : {baseline_show - text_show:.3f} ms")
    print(f"Pre-size show saving         : {baseline_show - size_show:.3f} ms")

    if baseline_total - direct_total >= 500:
        print("Font verdict: direct Malgun Gothic selection appears to save meaningful end-to-end startup time.")
    elif float(baseline["create_application_ms"]) - float(direct["create_application_ms"]) >= 500:
        print("Font verdict: font enumeration moves elsewhere; create_application is faster but end-to-end is not.")
    else:
        print("Font verdict: direct font selection does not provide a large reliable saving in this probe.")

    if baseline_show >= 500 and text_hot >= 500 and text_show <= baseline_show * 0.35:
        print("Show verdict: a specific text/font-metrics calculation absorbs most of window.show cost.")
        print("Likely trigger:", (pre_text.get("hotspot") or {}).get("desc", ""))
    elif baseline_show >= 500 and size_hot >= 500 and size_show <= baseline_show * 0.35:
        print("Show verdict: a specific widget sizeHint calculation absorbs most of window.show cost.")
        print("Likely trigger:", (pre_size.get("hotspot") or {}).get("desc", ""))
    elif baseline_show >= 500 and min(text_show, size_show) <= baseline_show * 0.35:
        print("Show verdict: child pre-measurement moves most show cost, but no single widget dominates.")
    else:
        print("Show verdict: window.show cost is not explained by individual text metrics or sizeHint alone.")
        print("Next target would be top-level polish/layout/native window realization.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
