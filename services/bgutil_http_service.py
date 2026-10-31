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
        return payload.get("version") == PROVIDER_VERSION
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

    def ensure(self, home: Path, deno: Path) -> BgUtilConnection | None:
        with self._lock:
            home = home.resolve()
            deno = deno.resolve()
            if not deno.is_file():
                self._status = "deno-executable-missing"
                return None
            if self._home != home or self._deno != deno:
                self._stop_locked()
                self._failed_until = 0.0
                self._verified_home = None
                self._cold_start_grace_available = True
                self._status = "starting"
                self._home, self._deno = home, deno
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
                self._stop_locked()

            if time.monotonic() < self._failed_until:
                self._status = "retry-cooldown"
                return None

            port = _free_loopback_port()
            url = f"http://127.0.0.1:{port}"
            server = home / "server"
            command = [
                str(deno), "run", "--allow-env", "--allow-net", "--allow-ffi=.",
                "--allow-read=.", "../src/main.ts", "--host", "127.0.0.1",
                "--port", str(port),
            ]
            environment = os.environ.copy()
            environment.update({
                "DENO_DIR": str(home / "deno-cache"),
                "DENO_NO_PROMPT": "1",
                "DENO_NO_UPDATE_CHECK": "1",
                "FORCE_COLOR": "false",
            })
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
                    phase=phase,
                    status=self._status,
                    startup_ms=max(0, round((time.monotonic() - started_at) * 1000)),
                    ping_attempts=attempts,
                    output_kind=kind,
                    first_output_ms=first_output_ms,
                )

            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(server / "node_modules"),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                )
            except OSError as error:
                self._status = f"deno-launch-failed:{type(error).__name__}"
                self._failed_until = time.monotonic() + _RETRY_DELAY
                startup_event("launch-failed", final=True)
                return None

            self._home, self._deno = home, deno
            self._process, self._url = process, url
            process_pid = int(getattr(process, "pid", 0) or 0)
            try:
                output.start(process)
            except (OSError, RuntimeError, AttributeError):
                # Diagnostic capture is not allowed to break media analysis.
                # Avoid leaving a child with an undrained stdout pipe.
                self._status = "output-monitor-failed"
                self._stop_locked()
                self._failed_until = time.monotonic() + _RETRY_DELAY
                startup_event("failed", final=True)
                return None
            self._status = "starting"
            startup_event("spawned")
            normal_deadline = time.monotonic() + _START_TIMEOUT
            allow_grace = self._cold_start_grace_available
            self._cold_start_grace_available = False
            final_deadline = normal_deadline + (_COLD_START_GRACE if allow_grace else 0)
            grace_logged = False
            while time.monotonic() < final_deadline:
                if process.poll() is not None:
                    break
                if not grace_logged and time.monotonic() >= normal_deadline:
                    grace_logged = True
                    startup_event("cold-grace")
                attempts += 1
                if _ping_local_provider(url):
                    self._status = "ready"
                    startup_event("ready", final=True)
                    # yt-dlp --plugin-dirs scans immediate children of this
                    # directory, including the verified plugin.zip archive.
                    # Passing home/plugins would scan inside yt_dlp_plugins and
                    # hide the provider namespace from the plugin loader.
                    return BgUtilConnection(home, url)
                time.sleep(0.2)
            exit_code = process.poll()
            self._status = (
                f"deno-exited-before-ready:code={exit_code}"
                if exit_code is not None else "server-ping-timeout"
            )
            # Stop the child and drain buffered output before classifying
            # startup failure. Never persist or print the actual output.
            self._stop_locked()
            output.wait_for_exit()
            startup_event("failed", final=True)
            self._failed_until = time.monotonic() + _RETRY_DELAY
            return None

    def _stop_locked(self) -> None:
        process = self._process
        self._process = None
        self._url = ""
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
            self._home = self._deno = None
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
        connection = _SERVER.ensure(Path(raw_home).expanduser(), deno)
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
