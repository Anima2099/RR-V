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


def _safe_console_print(text: str) -> None:
    """진단 출력 실패가 다운로드 기능까지 중단시키지 않게 한다."""

    try:
        print(text, flush=True)
    except Exception:
        # Windows 콘솔 인코딩, 닫힌 stdout 등 로깅 환경 문제는 무시한다.
        pass


def initialize_download_log() -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return

    try:
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
    except Exception as error:
        _safe_console_print(
            f"RR-V download log initialization failed: {error!r}"
        )
        return
    _INITIALIZED = True


def write_download_event(event: str, **fields: Any) -> None:
    """다운로드 진단 로그는 실패해도 본 다운로드 흐름을 절대 막지 않는다."""

    try:
        initialize_download_log()
        parts = [f"[{datetime.now():%H:%M:%S.%f}"[:-3] + "]", event]
        for key, value in fields.items():
            parts.append(f"{key}={value}")
        line = " | ".join(parts)
    except Exception as error:
        _safe_console_print(f"RR-V download log event failed: {error!r}")
        return

    _safe_console_print(f"[DOWNLOAD] {line}")
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
    except Exception as error:
        _safe_console_print(f"RR-V download log write failed: {error!r}")
