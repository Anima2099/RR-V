from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.paths import (
    DOWNLOAD_LOG_PATH,
    DOWNLOAD_TASK_LOGS_DIR,
    ensure_runtime_directories,
)


_LOCK = Lock()
_INITIALIZED = False


def initialize_download_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    ensure_runtime_directories()
    DOWNLOAD_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        "\n"
        + "=" * 72
        + f"\nRR-V download session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        + "=" * 72
        + "\n"
    )
    _append(DOWNLOAD_LOG_PATH, header)
    _INITIALIZED = True


def write_download_event(event: str, **fields: Any) -> None:
    initialize_download_log()
    parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    line = " | ".join(parts)
    print(f"[DOWNLOAD] {line}", flush=True)
    _append(DOWNLOAD_LOG_PATH, line + "\n")


def create_task_log_path(task_id: str) -> Path:
    initialize_download_log()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_id = "".join(ch for ch in task_id if ch.isalnum() or ch in "-_")[:24]
    return DOWNLOAD_TASK_LOGS_DIR / f"{stamp}_{safe_id or 'task'}.log"


def download_log_path() -> Path:
    initialize_download_log()
    return DOWNLOAD_LOG_PATH


def _append(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
    except OSError as error:
        print(f"RR-V download log write failed: {error}", flush=True)
