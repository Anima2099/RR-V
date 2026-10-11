from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.paths import SNAPSHOT_LOG_PATH, SNAPSHOT_TASK_LOGS_DIR, ensure_runtime_directories

_LOCK = Lock()
_INITIALIZED = False


def _safe_console_print(text: str) -> None:
    try:
        print(text, flush=True)
    except Exception:
        pass


def initialize_snapshot_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    try:
        ensure_runtime_directories()
        SNAPSHOT_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
        header = (
            "\n" + "=" * 72
            + f"\nRR-V snapshot session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
            + "=" * 72 + "\n"
        )
        _append(SNAPSHOT_LOG_PATH, header)
    except Exception as error:
        _safe_console_print(
            f"RR-V snapshot log initialization failed: {error!r}"
        )
        return
    _INITIALIZED = True


def write_snapshot_event(event: str, **fields: Any) -> None:
    try:
        initialize_snapshot_log()
        parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        line = " | ".join(parts)
    except Exception as error:
        _safe_console_print(
            f"RR-V snapshot log event failed: {error!r}"
        )
        return

    _safe_console_print(f"[SNAPSHOT] {line}")
    _append(SNAPSHOT_LOG_PATH, line + "\n")

def create_snapshot_task_log_path() -> Path:
    initialize_snapshot_log()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return SNAPSHOT_TASK_LOGS_DIR / f"{stamp}_snapshot.log"


def append_snapshot_task_log(path: Path, text: str) -> None:
    _append(path, text)


def snapshot_log_path() -> Path:
    initialize_snapshot_log()
    return SNAPSHOT_LOG_PATH


def _append(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
    except Exception as error:
        _safe_console_print(
            f"RR-V snapshot log write failed: {error!r}"
        )
