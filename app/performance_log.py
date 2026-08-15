from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime
from pathlib import Path
from threading import Lock
from time import perf_counter
from typing import Any

from app.paths import PERFORMANCE_LOG_PATH, ensure_runtime_directories


_LOCK = Lock()
_INITIALIZED = False


def initialize_performance_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    ensure_runtime_directories()
    session_line = (
        "\n"
        + "=" * 72
        + f"\nRR-V performance session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        + "=" * 72
        + "\n"
    )
    _append_text(PERFORMANCE_LOG_PATH, session_line)
    _INITIALIZED = True


def write_performance(
    event: str,
    duration_ms: float | None = None,
    **fields: Any,
) -> None:
    initialize_performance_log()

    parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
    if duration_ms is not None:
        parts.append(f"{duration_ms:.3f} ms")
    for key, value in fields.items():
        parts.append(f"{key}={value}")

    line = " | ".join(parts)
    print(f"[PERF] {line}", flush=True)
    _append_text(PERFORMANCE_LOG_PATH, line + "\n")


class PerformanceSpan(AbstractContextManager["PerformanceSpan"]):
    def __init__(self, event: str, **fields: Any) -> None:
        self.event = event
        self.fields = fields
        self.started_at = 0.0

    def __enter__(self) -> "PerformanceSpan":
        self.started_at = perf_counter()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> bool:
        elapsed_ms = (perf_counter() - self.started_at) * 1000.0
        fields = dict(self.fields)
        if exc_value is not None:
            fields["error"] = type(exc_value).__name__
        write_performance(self.event, elapsed_ms, **fields)
        return False


def performance_log_path() -> Path:
    initialize_performance_log()
    return PERFORMANCE_LOG_PATH


def _append_text(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as log_file:
                log_file.write(text)
    except OSError as error:
        print(f"RR-V performance log write failed: {error}", flush=True)
