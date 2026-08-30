from __future__ import annotations

from collections import defaultdict
import inspect
import linecache
import sys
from time import perf_counter

from app.application import create_application


def _source_text(path: str, lineno: int) -> str:
    return linecache.getline(path, lineno).strip()


def main() -> int:
    app = create_application(sys.argv)

    # 제품 코드는 수정하지 않는다. DownloadPage.__init__ 한 프레임만 추적해
    # 각 소스 줄에서 다음 줄로 넘어가기까지 걸린 시간을 기록한다.
    # 호출한 줄 안에서 다른 Python/C++ 함수가 실행된 시간도 그 호출 줄에 포함된다.
    from ui.pages.download_page import DownloadPage

    target_code = DownloadPage.__init__.__code__
    source_path = inspect.getsourcefile(DownloadPage) or target_code.co_filename

    elapsed_by_line: dict[int, float] = defaultdict(float)
    hits_by_line: dict[int, int] = defaultdict(int)
    timeline: list[tuple[int, float]] = []

    active_line: int | None = None
    active_started = 0.0

    def local_trace(frame, event: str, arg):  # type: ignore[no-untyped-def]
        nonlocal active_line, active_started
        now = perf_counter()

        if event == "line":
            if active_line is not None:
                elapsed_ms = (now - active_started) * 1000.0
                elapsed_by_line[active_line] += elapsed_ms
                hits_by_line[active_line] += 1
                timeline.append((active_line, elapsed_ms))
            active_line = frame.f_lineno
            active_started = now
            return local_trace

        if event == "return":
            if active_line is not None:
                elapsed_ms = (now - active_started) * 1000.0
                elapsed_by_line[active_line] += elapsed_ms
                hits_by_line[active_line] += 1
                timeline.append((active_line, elapsed_ms))
            active_line = None
            return local_trace

        return local_trace

    def global_trace(frame, event: str, arg):  # type: ignore[no-untyped-def]
        nonlocal active_line, active_started
        if event == "call" and frame.f_code is target_code:
            active_line = None
            active_started = perf_counter()
            return local_trace
        return None

    page = None
    total_started = perf_counter()
    sys.settrace(global_trace)
    try:
        page = DownloadPage()
    finally:
        sys.settrace(None)
    total_ms = (perf_counter() - total_started) * 1000.0

    ranked = sorted(
        elapsed_by_line.items(),
        key=lambda item: item[1],
        reverse=True,
    )

    print("\nRR-V DownloadPage __init__ line profile")
    print("=" * 112)
    print(f"DownloadPage total: {total_ms:.3f} ms")
    print(f"Source: {source_path}")
    print("\nTop hotspots")
    print("-" * 112)
    print(f"{'rank':>4}  {'time':>12}  {'hits':>4}  {'line':>6}  source")

    for rank, (lineno, duration_ms) in enumerate(ranked[:30], start=1):
        text = _source_text(source_path, lineno)
        print(
            f"{rank:>4}  {duration_ms:>9.3f} ms  "
            f"{hits_by_line[lineno]:>4}  {lineno:>6}  {text}"
        )

    print("\nSequential lines taking >= 1.0 ms")
    print("-" * 112)
    for lineno, duration_ms in timeline:
        if duration_ms < 1.0:
            continue
        print(
            f"{duration_ms:>9.3f} ms  line {lineno:>6}  "
            f"{_source_text(source_path, lineno)}"
        )

    traced_ms = sum(elapsed_by_line.values())
    print("=" * 112)
    print(f"Time attributed to __init__ source lines: {traced_ms:.3f} ms")
    print(f"Unattributed profiler overhead/outside frame: {max(0.0, total_ms - traced_ms):.3f} ms")
    print(f"Restored task count: {len(getattr(page, 'tasks', ()) or ()) if page is not None else 0}")
    print("Profiler only: no download or Installer was started.")

    if page is not None:
        page.deleteLater()
        app.processEvents()
    app.quit()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
