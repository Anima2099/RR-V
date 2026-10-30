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


class _BgUtilServer:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._home: Path | None = None
        self._deno: Path | None = None
        self._url = ""
        self._failed_until = 0.0
        self._verified_home: Path | None = None
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
            try:
                process = subprocess.Popen(
                    command,
                    cwd=str(server / "node_modules"),
                    env=environment,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0,
                )
            except OSError as error:
                self._status = f"deno-launch-failed:{type(error).__name__}"
                self._failed_until = time.monotonic() + _RETRY_DELAY
                return None

            self._home, self._deno = home, deno
            self._process, self._url = process, url
            deadline = time.monotonic() + _START_TIMEOUT
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    break
                if _ping_local_provider(url):
                    self._status = "ready"
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
            self._stop_locked()
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
