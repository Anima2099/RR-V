from __future__ import annotations

from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Any

from app.paths import SUBTITLE_LOG_PATH, SUBTITLE_TASK_LOGS_DIR, ensure_runtime_directories

_LOCK = Lock()
_INITIALIZED = False


def initialize_subtitle_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    ensure_runtime_directories()
    SUBTITLE_TASK_LOGS_DIR.mkdir(parents=True, exist_ok=True)
    _append(
        SUBTITLE_LOG_PATH,
        "\n" + "=" * 72 + f"\nRR-V subtitle session: {datetime.now():%Y-%m-%d %H:%M:%S}\n" + "=" * 72 + "\n",
    )
    _INITIALIZED = True


def write_subtitle_event(event: str, **fields: Any) -> None:
    initialize_subtitle_log()
    parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
    parts.extend(f"{key}={value}" for key, value in fields.items())
    line = " | ".join(parts)
    print(f"[SUBTITLE] {line}", flush=True)
    _append(SUBTITLE_LOG_PATH, line + "\n")


def create_subtitle_task_log_path() -> Path:
    initialize_subtitle_log()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    return SUBTITLE_TASK_LOGS_DIR / f"{stamp}_subtitle.log"


def append_subtitle_task_log(path: Path, text: str) -> None:
    _append(path, text)


def subtitle_log_path() -> Path:
    initialize_subtitle_log()
    return SUBTITLE_LOG_PATH


def _append(path: Path, text: str) -> None:
    try:
        with _LOCK:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(text)
    except OSError as error:
        print(f"RR-V subtitle log write failed: {error}", flush=True)
