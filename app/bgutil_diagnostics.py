"""Privacy-minimal diagnostic log for the opt-in Stage03 BgUtils integration.

Only short machine-readable status codes are accepted. Never write URLs,
filesystem locations, command lines, cookies, credentials or PO Tokens here.
Logging must not interrupt analysis or downloads if the disk is unavailable.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import re
from threading import Lock

from app.paths import RRV_LOGS_DIR


BGUTIL_DIAGNOSTIC_LOG_PATH = RRV_LOGS_DIR / "bgutil-stage03.log"
_LOG_LIMIT_BYTES = 512 * 1024
_LOCK = Lock()
_SAFE_ATOM = re.compile(r"[A-Za-z0-9_.:-]{1,72}\Z", re.ASCII)
_ALLOWED_FIELDS = frozenset({
    "pid", "server_pid", "mode", "runtime", "stage", "deno", "server",
    "bgutil", "wpc", "route", "status", "result",
    "scenario", "trial", "setup_ms", "extract_ms", "total_ms",
    "token_source", "chrome_signal",
})


def _safe_atom(value: object) -> str:
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int):
        return str(value) if 0 <= value <= 2147483647 else "redacted"
    if isinstance(value, str):
        # Preserve an integer Deno exit code without permitting arbitrary
        # key=value strings or terminal control characters.
        prefix = "deno-exited-before-ready:code="
        if value.startswith(prefix) and re.fullmatch(r"-?[0-9]{1,6}", value[len(prefix):]):
            exit_code = value[len(prefix):].replace("-", "minus")
            return f"deno-exited-before-ready-code-{exit_code}"
        if _SAFE_ATOM.fullmatch(value):
            return value
    return "redacted"


def record_bgutil_diagnostic(event: str, **fields: object) -> None:
    """Append only redacted status codes, never untrusted free-form details."""
    try:
        name = _safe_atom(event)
        permitted = [
            f"{key}={_safe_atom(value)}"
            for key, value in fields.items()
            if key in _ALLOWED_FIELDS
        ]
        now = datetime.now().isoformat(timespec="milliseconds")
        line = " | ".join((now, f"event={name}", *permitted)) + "\n"
        with _LOCK:
            path = BGUTIL_DIAGNOSTIC_LOG_PATH
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.is_file() and path.stat().st_size > _LOG_LIMIT_BYTES:
                previous = path.with_suffix(".log.1")
                try:
                    previous.unlink(missing_ok=True)
                    path.replace(previous)
                except OSError:
                    # A competing process may own the log on Windows; never
                    # let a diagnostics failure block the media operation.
                    pass
            with path.open("a", encoding="utf-8") as handle:
                handle.write(line)
    except Exception:
        # Diagnostics are optional, and exception messages can contain paths.
        pass
