from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.paths import (
    THUMBNAIL_LOG_PATH,
    THUMBNAIL_TASK_LOGS_DIR,
    ensure_runtime_directories,
)

_LOCK = Lock()
_INITIALIZED = False


def initialize_thumbnail_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    ensure_runtime_directories()
    THUMBNAIL_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    header = (
        "\n"
        + "=" * 72
        + f"\nRR-V thumbnail session: {datetime.now():%Y-%m-%d %H:%M:%S}\n"
        + "=" * 72
        + "\n"
    )
    _append(THUMBNAIL_LOG_PATH, header)
    _INITIALIZED = True


def write_thumbnail_event(event: str, **fields: Any) -> None:
    initialize_thumbnail_log()
    parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
    for key, value in fields.items():
        parts.append(f"{key}={value}")
    line = " | ".join(parts)
    print(f"[THUMBNAIL] {line}", flush=True)
    _append(THUMBNAIL_LOG_PATH, line + "\n")


def create_thumbnail_task_log_path() -> Path:
    initialize_thumbnail_log()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return THUMBNAIL_TASK_LOGS_DIR / f"{stamp}_thumbnail.log"


def append_thumbnail_task_log(path: Path, text: str) -> None:
    _append(path, text)


def thumbnail_log_path() -> Path:
    initialize_thumbnail_log()
    return THUMBNAIL_LOG_PATH


def _append(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
    except OSError as error:
        print(f"RR-V thumbnail log write failed: {error}", flush=True)
