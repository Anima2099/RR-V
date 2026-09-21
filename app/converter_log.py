from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.paths import (
    CONVERTER_LOG_PATH,
    CONVERSION_TASK_LOGS_DIR,
    ensure_runtime_directories,
)

_LOCK = Lock()
_INITIALIZED = False


def _safe_console_print(text: str) -> None:
    try:
        print(text, flush=True)
    except Exception:
        pass


def initialize_converter_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    try:
        ensure_runtime_directories()
        CONVERSION_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        header = (
            "\n"
            + "=" * 72
            + f"\nRR-V converter session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            + "=" * 72
            + "\n"
        )
        _append(CONVERTER_LOG_PATH, header)
    except Exception as error:
        _safe_console_print(
            f"RR-V converter log initialization failed: {error!r}"
        )
        return
    _INITIALIZED = True


def write_converter_event(event: str, **fields: Any) -> None:
    try:
        initialize_converter_log()
        parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        line = " | ".join(parts)
    except Exception as error:
        _safe_console_print(
            f"RR-V converter log event failed: {error!r}"
        )
        return

    _safe_console_print(f"[CONVERTER] {line}")
    _append(CONVERTER_LOG_PATH, line + "\n")

def create_conversion_log_path(output_format: str) -> Path:
    initialize_converter_log()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_format = "".join(ch for ch in output_format.lower() if ch.isalnum())[:12]
    return CONVERSION_TASK_LOGS_DIR / f"{stamp}_{safe_format or 'convert'}.log"


def append_conversion_log(path: Path, text: str) -> None:
    _append(path, text)


def converter_log_path() -> Path:
    initialize_converter_log()
    return CONVERTER_LOG_PATH


def _append(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
    except Exception as error:
        _safe_console_print(
            f"RR-V converter log write failed: {error!r}"
        )
