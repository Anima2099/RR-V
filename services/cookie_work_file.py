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


def cleanup_stale_cookie_work_directories() -> None:
    """Remove leftover RR-V cookie work directories from earlier processes."""

    temp_root = Path(tempfile.gettempdir())
    with _WORK_LOCK:
        active_work_dir = _WORK_DIR

    try:
        for candidate in temp_root.glob(f"{_WORK_PREFIX}*"):
            if not candidate.is_dir():
                continue
            if active_work_dir is not None and candidate == active_work_dir:
                continue
            _cleanup_directory(candidate)
    except OSError:
        pass


def _prepare_work_directory() -> Path:
    global _WORK_DIR
    with _WORK_LOCK:
        if _WORK_DIR is not None and _WORK_DIR.is_dir():
            return _WORK_DIR

    # A crashed RR-V process can leave tiny cookie work copies behind.
    # Remove only RR-V's own stale work directories before creating this
    # process's private work area.
    cleanup_stale_cookie_work_directories()

    with _WORK_LOCK:
        if _WORK_DIR is not None and _WORK_DIR.is_dir():
            return _WORK_DIR

        temp_root = Path(tempfile.gettempdir())
        work_dir = Path(
            tempfile.mkdtemp(
                prefix=f"{_WORK_PREFIX}{os.getpid()}-",
                dir=str(temp_root),
            )
        )
        _WORK_DIR = work_dir
        atexit.register(_cleanup_directory, work_dir)
        return work_dir


def _is_managed_cookie_work_copy(path: Path) -> bool:
    candidate = Path(path)
    with _WORK_LOCK:
        work_dir = _WORK_DIR
    if work_dir is None:
        return False

    try:
        same_parent = candidate.parent.resolve() == work_dir.resolve()
    except OSError:
        return False
    return (
        same_parent
        and candidate.name.startswith("cookie-")
        and candidate.suffix.lower() == ".txt"
    )


def cleanup_cookie_work_copy(path: str | Path | None) -> None:
    """Delete one disposable cookie copy created by RR-V, if it is ours."""

    if path is None:
        return
    candidate = Path(path)
    if not _is_managed_cookie_work_copy(candidate):
        return
    try:
        candidate.unlink(missing_ok=True)
    except OSError:
        pass


def cleanup_cookie_work_copy_from_command(command: list[str] | tuple[str, ...]) -> None:
    """Delete protected cookie copies referenced by a completed yt-dlp command.

    Manually supplied cookie files are intentionally left untouched. Only files
    inside this process's RR-V cookie work directory pass the managed-file check.
    """

    for index, item in enumerate(command[:-1]):
        if str(item) != "--cookies":
            continue
        cleanup_cookie_work_copy(command[index + 1])


def prepare_cookie_work_copy(source: Path) -> Path:
    """Return a disposable copy for yt-dlp's read/write cookie jar.

    yt-dlp writes the cookie jar passed through ``--cookies`` back to disk.
    RR-V authentication files are source-of-truth credentials, so they must
    never be handed to yt-dlp directly. Each command receives its own copy;
    the copy should be removed as soon as that yt-dlp process finishes. The
    process work directory is kept for reuse and removed at RR-V exit, while
    stale crash leftovers are cleaned on the next primary RR-V start/use.
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
