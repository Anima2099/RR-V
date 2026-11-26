"""Developer-only bridge to an independently installed BgUtils POT HTTP provider.

The GPL-3.0-only upstream server and plugin are never shipped in RR-V. An
explicit environment variable enables this experimental localhost integration.
No work runs at application startup unless a YouTube operation needs tokens.
"""

from __future__ import annotations

import atexit
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener
import zipfile

from app.bgutil_diagnostics import record_bgutil_diagnostic


ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"
ENV_COMPILED_EXE = "RRV_BGUTIL_STAGE03_COMPILED_EXE"
COMPILED_MARKER_NAME = "rrv-p3-compiled.json"
UNBUNDLED_EXE_NAME = "bgutil-p3-unbundled.exe"
PROVIDER_VERSION = "2.0.2"
SOURCE_COMMIT = "26475e9d3665b972c4aeb83b4dbaafcf64b88438"
PLUGIN_SHA256 = "a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef"
_START_TIMEOUT = 12.0
# A cold Deno dependency load can exceed the normal budget. Allow one
# bounded, explicitly logged grace period per external installation.
_COLD_START_GRACE = 6.0
_RETRY_DELAY = 60.0


@dataclass(frozen=True)
class BgUtilConnection:
    plugin_dir: Path
    base_url: str


def read_compiled_candidate(binary: Path, variant: str) -> dict | None:
    """Check local build metadata and size without reading the executable."""
    try:
        marker = json.loads((binary.parent / COMPILED_MARKER_NAME).read_text(encoding="utf-8"))
        if (
            isinstance(marker, dict)
            and marker.get("schema") == 1
            and marker.get("source_commit") == SOURCE_COMMIT
            and marker.get("variant") == variant
            and type(marker.get("size")) is int
            and marker["size"] > 0
            and isinstance(marker.get("sha256"), str)
            and re.fullmatch(r"[0-9a-f]{64}", marker["sha256"])
            and not binary.is_symlink()
            and binary.is_file()
            and binary.stat().st_size == marker["size"]
        ):
            return marker
    except (OSError, ValueError):
        pass
    return None


def _is_local_unbundled(binary: Path) -> bool:
    if not binary.is_absolute() or binary.drive.startswith(("\\\\", "//")) or binary.name != UNBUNDLED_EXE_NAME:
        return False
    try:
        return binary.resolve() == binary and read_compiled_candidate(binary, "unbundled") is not None
    except (OSError, ValueError, RuntimeError):
        return False


def _validate_external_home(home: Path) -> bool:
    """Require the exact pinned opt-in installation prepared by stage03 script."""
    try:
        manifest = json.loads((home / "rrv-stage03.json").read_text(encoding="utf-8"))
        if manifest != {
            "version": PROVIDER_VERSION,
            "source_commit": SOURCE_COMMIT,
            "plugin_sha256": PLUGIN_SHA256,
        }:
            return False
        server = home / "server"
        package = json.loads((server / "package.json").read_text(encoding="utf-8"))
        if package.get("version") != PROVIDER_VERSION or package.get("license") != "GPL-3.0-only":
            return False
        if not (home / "LICENSE").is_file() or not (server / "node_modules").is_dir():
            return False
        if not (server / "src" / "main.ts").is_file():
            return False
        archive = home / "plugin.zip"
        if hashlib.sha256(archive.read_bytes()).hexdigest() != PLUGIN_SHA256:
            return False
        with zipfile.ZipFile(archive) as bundle:
            for name in (
                "yt_dlp_plugins/extractor/getpot_bgutil.py",
                "yt_dlp_plugins/extractor/getpot_bgutil_http.py",
                "yt_dlp_plugins/extractor/getpot_bgutil_script.py",
            ):
                if (home / "plugins" / name).read_bytes() != bundle.read(name):
                    return False
    except (OSError, ValueError, KeyError, zipfile.BadZipFile):
        return False
    return True


def _free_loopback_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _ping_local_provider(url: str) -> bool:
    # Do not use environment-configured HTTP proxies for localhost.
    try:
        opener = build_opener(ProxyHandler({}))
        request = Request(url + "/ping", headers={"Accept": "application/json"})
        with opener.open(request, timeout=0.4) as response:
            if response.status != 200:
                return False
            payload = json.loads(response.read(2048))
        return isinstance(payload, dict) and payload.get("version") == PROVIDER_VERSION
    except (OSError, URLError, ValueError):
        return False


class _SafeDenoOutput:
    """Drain Deno output and retain only fixed startup codes, never raw logs.

    Upstream may print sensitive errors during token requests. Once startup
    finishes, any buffered bytes are erased; draining continues so Deno
    cannot block on a full stdout pipe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tail = b""
        self._kind = "no-output"
        self._first_output_ms = 0
        self._started_at = time.monotonic()
        self._sealed = False
        self._thread: threading.Thread | None = None

    @staticmethod
    def _categorize(chunk: bytes) -> str:
        text = chunk.lower()
        if b"could not listen on" in text or b"eaddrinuse" in text:
            return "listen-error"
        if (b"module not found" in text or b"cannot find module" in text
                or b"err_module_not_found" in text):
            return "module-error"
        if b"permission denied" in text or b"requires --allow" in text:
            return "permission-error"
        if b"failed to fetch" in text or b"error sending request" in text:
            return "dependency-fetch-error"
        if b"started pot server" in text:
            return "server-announced"
        if b"download" in text or b"compil" in text:
            return "dependency-loading"
        return "other-output"

    def feed(self, chunk: bytes) -> None:
        if not chunk:
            return
        with self._lock:
            if self._sealed:
                return
            if self._kind == "no-output":
                self._first_output_ms = max(
                    0, round((time.monotonic() - self._started_at) * 1000)
                )
            # 128 bytes in memory, solely to match messages split across
            # small pipe reads; never sent to disk, logs or the console.
            combined = self._tail + chunk
            self._tail = combined[-128:]
            kind = self._categorize(combined)
            severity = {
                "no-output": 0, "other-output": 1, "dependency-loading": 2,
                "server-announced": 3, "listen-error": 4, "module-error": 4,
                "permission-error": 4, "dependency-fetch-error": 4,
            }
            if severity[kind] > severity[self._kind]:
                self._kind = kind

    def snapshot(self, *, seal: bool = False) -> tuple[str, int]:
        with self._lock:
            if seal:
                self._sealed = True
                self._tail = b""
            return self._kind, self._first_output_ms

    def start(self, process: subprocess.Popen[bytes]) -> None:
        stream = getattr(process, "stdout", None)
        if stream is None:
            return

        def drain() -> None:
            try:
                read_one = getattr(stream, "read1", stream.read)
                while True:
                    block = read_one(1024)
                    if not block:
                        break
                    self.feed(block)
            except (OSError, ValueError):
                pass
            finally:
                try:
                    stream.close()
                except OSError:
                    pass

        self._thread = threading.Thread(
            target=drain, name="RRV-BgUtils-safe-output", daemon=True,
        )
        self._thread.start()

    def wait_for_exit(self) -> None:
        if self._thread is not None:
            # Only called after the child has exited or been stopped. Drain
            # any buffered startup error before converting it to a safe code.
            self._thread.join(timeout=0.2)


class _BgUtilServer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._home: Path | None = None
        self._deno: Path | None = None
        self._compiled: Path | None = None
        self._compiled_failed = False
        self._runtime = "none"
        self._url = ""
        self._failed_until = 0.0
        self._verified_home: Path | None = None
        self._cold_start_grace_available = True
        # Diagnostic states contain no cookies, tokens or personal filesystem paths.
        self._status = "not-started"

    def status(self) -> str:
        with self._lock:
            return self._status

    def record_status(self, status: str) -> None:
        with self._lock:
            self._status = status

    def process_pid(self) -> int:
        """Return a server PID, not the server command line or credentials."""
        with self._lock:
            process = self._process
            if process is None:
                return 0
            try:
                if process.poll() is None:
                    return int(getattr(process, "pid", 0) or 0)
            except (OSError, ValueError, TypeError):
                pass
            return 0

    def ensure(self, home: Path, deno: Path, compiled: Path | None = None) -> BgUtilConnection | None:
        with self._lock:
            home = home.resolve()
            deno = deno.resolve()
            if not deno.is_file():
                self._status = "deno-executable-missing"
                return None
            if (self._home, self._deno, self._compiled) != (home, deno, compiled):
                self._stop_locked()
                self._failed_until = 0.0
                self._verified_home = None
                self._cold_start_grace_available = True
                self._status = "starting"
                self._home, self._deno = home, deno
                self._compiled = compiled
                self._compiled_failed = False
            if self._verified_home != home:
                if not _validate_external_home(home):
                    self._status = "invalid-external-installation"
                    return None
                self._verified_home = home

            if self._process is not None:
                if self._process.poll() is None and _ping_local_provider(self._url):
                    self._status = "ready"
                    return BgUtilConnection(home, self._url)
                self._status = "server-stopped-or-not-responding"
                if self._runtime == "compiled":
                    self._compiled_failed = True
                    self._log_compiled_fallback()
                self._stop_locked()

            if time.monotonic() < self._failed_until:
                self._status = "retry-cooldown"
                return None

            if compiled is not None and not self._compiled_failed:
                if _is_local_unbundled(compiled):
                    connection = self._start_locked(home, compiled, runtime="compiled")
                    if connection is not None:
                        return connection
                    self._compiled_failed = True
                else:
                    self._status = "compiled-candidate-unavailable"
                self._log_compiled_fallback()

            connection = self._start_locked(home, deno, runtime="deno")
            if connection is None:
                self._failed_until = time.monotonic() + _RETRY_DELAY
            return connection

    def _log_compiled_fallback(self) -> None:
        record_bgutil_diagnostic(
            "bgutil.runtime", pid=os.getpid(), runtime="compiled", result="fallback", status=self._status,
        )

    def _start_locked(self, home: Path, executable: Path, *, runtime: str) -> BgUtilConnection | None:
        port = _free_loopback_port()
        url = f"http://127.0.0.1:{port}"
        compiled = runtime == "compiled"
        command = [str(executable)]
        environment = os.environ.copy()
        environment.update({"DENO_NO_PROMPT": "1", "DENO_NO_UPDATE_CHECK": "1", "FORCE_COLOR": "false"})
        if compiled:
            cwd = executable.parent
        else:
            cwd = home / "server" / "node_modules"
            command.extend(["run", "--allow-env", "--allow-net", "--allow-ffi=.", "--allow-read=.", "../src/main.ts"])
            environment["DENO_DIR"] = str(home / "deno-cache")
        command.extend(["--host", "127.0.0.1", "--port", str(port)])
        started_at = time.monotonic()
        output = _SafeDenoOutput()
        attempts = 0
        process_pid = 0

        def startup_event(phase: str, *, final: bool = False) -> None:
            kind, first_output_ms = output.snapshot(seal=final)
            record_bgutil_diagnostic(
                "bgutil.startup",
                pid=os.getpid(),
                server_pid=process_pid,
                runtime=runtime,
                phase=phase,
                status=self._status,
                startup_ms=max(0, round((time.monotonic() - started_at) * 1000)),
                ping_attempts=attempts,
                output_kind=kind,
                first_output_ms=first_output_ms,
            )

        try:
            process = subprocess.Popen(
                command, cwd=str(cwd), env=environment,
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
            )
        except (OSError, ValueError) as error:
            self._status = f"{runtime}-launch-failed:{type(error).__name__}"
            startup_event("launch-failed", final=True)
            return None

        self._process, self._url, self._runtime = process, url, runtime
        process_pid = int(getattr(process, "pid", 0) or 0)
        try:
            output.start(process)
        except (OSError, RuntimeError, AttributeError):
            self._status = "output-monitor-failed"
            self._stop_locked()
            startup_event("failed", final=True)
            return None

        self._status = "starting"
        startup_event("spawned")
        if compiled:
            normal_deadline = final_deadline = started_at + _START_TIMEOUT + _COLD_START_GRACE
        else:
            normal_deadline = time.monotonic() + _START_TIMEOUT
            final_deadline = normal_deadline + (_COLD_START_GRACE if self._cold_start_grace_available else 0)
            self._cold_start_grace_available = False
        grace_logged = False
        while time.monotonic() < final_deadline:
            if process.poll() is not None:
                break
            if not grace_logged and time.monotonic() >= normal_deadline:
                grace_logged = True
                startup_event("cold-grace")
            attempts += 1
            if _ping_local_provider(url) and (not compiled or time.monotonic() <= final_deadline):
                self._status = "ready"
                startup_event("ready", final=True)
                # yt-dlp discovers the verified plugin.zip directly under home.
                return BgUtilConnection(home, url)
            time.sleep(0.2)
        exit_code = process.poll()
        if exit_code is None:
            self._status = "server-ping-timeout"
        elif compiled:
            self._status = f"compiled-exited-before-ready-code-{exit_code}"
        else:
            self._status = f"deno-exited-before-ready:code={exit_code}"
        self._stop_locked()
        output.wait_for_exit()
        startup_event("failed", final=True)
        return None

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._url = ""
        self._runtime = "none"
        if process is None or process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def close(self) -> None:
        with self._lock:
            self._stop_locked()
            self._home = self._deno = self._compiled = None
            self._status = "stopped"
            self._failed_until = 0.0


_SERVER = _BgUtilServer()


def connect_bgutil_http(deno: Path | None) -> BgUtilConnection | None:
    """Explicit opt-in only. Failure never blocks the existing WPC provider."""
    raw_home = os.environ.get(ENV_HOME, "").strip()
    if not raw_home:
        return None
    if deno is None:
        _SERVER.record_status("deno-executable-missing")
        record_bgutil_diagnostic(
            "bgutil.connection",
            pid=os.getpid(),
            result="fallback",
            status=_SERVER.status(),
            server_pid=0,
        )
        return None
    try:
        raw_compiled = os.environ.get(ENV_COMPILED_EXE, "").strip() if sys.platform == "win32" else ""
        compiled = Path(raw_compiled) if raw_compiled else None
        connection = _SERVER.ensure(Path(raw_home).expanduser(), deno, compiled)
    except (OSError, ValueError) as error:
        _SERVER.record_status(f"connection-setup-failed:{type(error).__name__}")
        connection = None

    record_bgutil_diagnostic(
        "bgutil.connection",
        pid=os.getpid(),
        result="ready" if connection is not None else "fallback",
        status=_SERVER.status(),
        server_pid=_SERVER.process_pid(),
    )
    return connection


def bgutil_http_status() -> str:
    """Return a safe, short reason for the most recent connection decision."""
    if not os.environ.get(ENV_HOME, "").strip():
        return "disabled"
    return _SERVER.status()


def shutdown_bgutil_http() -> None:
    server_pid = _SERVER.process_pid()
    _SERVER.close()
    if server_pid:
        record_bgutil_diagnostic(
            "bgutil.stopped",
            pid=os.getpid(),
            server_pid=server_pid,
            status="stopped",
        )


atexit.register(shutdown_bgutil_http)
