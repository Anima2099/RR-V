from __future__ import annotations

import atexit
import os
from pathlib import Path
import shutil
import tempfile
import threading


_WORK_PREFIX = "rrv-yt-dlp-cookie-"
_WORK_LOCK = threading.Lock()
_WORK_DIR: Path | None = None


def _cleanup_directory(path: Path) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def _prepare_work_directory() -> Path:
    global _WORK_DIR
    with _WORK_LOCK:
        if _WORK_DIR is not None and _WORK_DIR.is_dir():
            return _WORK_DIR

        temp_root = Path(tempfile.gettempdir())
        # A crashed RR-V process can leave tiny cookie work copies behind.
        # Remove only our own stale directories before creating this process's
        # private work area.
        try:
            for candidate in temp_root.glob(f"{_WORK_PREFIX}*"):
                if candidate.is_dir():
                    _cleanup_directory(candidate)
        except OSError:
            pass

        work_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{_WORK_PREFIX}{os.getpid()}-",
                dir=str(temp_root),
            )
        )
        _WORK_DIR = work_dir
        atexit.register(_cleanup_directory, work_dir)
        return work_dir


def prepare_cookie_work_copy(source: Path) -> Path:
    """Return a disposable copy for yt-dlp's read/write cookie jar.

    yt-dlp writes the cookie jar passed through ``--cookies`` back to disk.
    RR-V authentication files are source-of-truth credentials, so they must
    never be handed to yt-dlp directly. Each command receives its own copy;
    copies are removed when RR-V exits, and stale crash leftovers are cleaned
    on the next use.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(source)

    work_dir = _prepare_work_directory()
    fd, temporary_name = tempfile.mkstemp(
        prefix="cookie-",
        suffix=".txt",
        dir=str(work_dir),
    )
    os.close(fd)
    destination = Path(temporary_name)
    try:
        shutil.copy2(source, destination)
    except Exception:
        try:
            destination.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    return destination
