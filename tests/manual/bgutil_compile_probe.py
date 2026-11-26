"""Developer-only Stage03 P3: compile and probe a separate BgUtils executable.

Uses the already isolated and verified P2 lean installation as its build input.
Never modifies RR-V's production launcher or the original BgUtils install.
The pinned upstream provider is GPL-3.0-only; do not distribute test binaries.
"""

from __future__ import annotations

import argparse
from collections import deque
from contextlib import contextmanager
import ctypes
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import runpy
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO, Callable, Iterator
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.paths import find_executable
from services import bgutil_http_service as bgutil

# A self-extracting variant may be tried separately if native canvas cannot
# run from the ordinary compiled bundle. It is NOT the default: extraction
# adds file writes and can undermine the cold-start optimization objective.
VARIANTS = ("bundled", "extracted", "unbundled")
MARKER_NAME = bgutil.COMPILED_MARKER_NAME
LEAN_MARKER = "rrv-lean-experiment.json"
BUILD_TIMEOUT = 360
BUNDLER_TIMEOUT = 120
BUNDLER_CACHE_NAME = "bgutil-stage03-p3-cache"
BUNDLER_MARKER = "rrv-p3-bundler-ready"
PROBE_TIMEOUT = 70.0
LAUNCH_PROGRESS_INTERVAL = 5.0
TOKEN_PROBE_TIMEOUT = 150
PROBE_LOG_STREAM_LIMIT = 256 * 1024
PROBE_LOG_TAIL_LIMIT = 32 * 1024
PRODUCTION_FIRST_BUDGET_MS = 18_000
MIN_FREE_BYTES = 512 * 1024 * 1024
# server/deno.lock from bgutil.SOURCE_COMMIT, normalized to LF.
PUBLIC_LOCK_SHA256 = "5b251ee1b127499e72b8faf9f6a9cee36b6d8dc3970bc8249e58f6f840550c59"
PUBLIC_DEPENDENCY_HOSTS = ("registry.npmjs.org", "jsr.io", "deno.land", "esm.sh")
# Deno's bundler fetches these independently of BgUtils's lockfile.
PUBLIC_WINDOWS_BUNDLER_PACKAGES = ("@esbuild/win32-x64", "@esbuild/win32-arm64")


def paths_for(local_appdata: Path, variant: str) -> tuple[Path, Path]:
    if variant not in VARIANTS:
        raise ValueError("unknown variant")
    root = local_appdata / "RR-V" / "diagnostics"
    source = root / "bgutil-stage03-lean-experiment"
    target = root / ("bgutil-stage03-compiled-" + variant)
    return source, target


def binary_name(variant: str) -> str:
    if variant not in VARIANTS:
        raise ValueError("unknown variant")
    return "bgutil-p3-" + variant + ".exe"


def _is_lean_source(source: Path) -> bool:
    try:
        marker = json.loads((source / LEAN_MARKER).read_text(encoding="utf-8"))
        return marker == {
            "schema": 1,
            "source_commit": bgutil.SOURCE_COMMIT,
            "method": "prod-entrypoint-frozen",
        } and bgutil._validate_external_home(source)
    except (OSError, ValueError, TypeError):
        return False


def _deno_environment(cache: Path) -> dict[str, str]:
    return {
        **os.environ,
        "DENO_DIR": str(cache),
        "DENO_NO_PROMPT": "1",
        "DENO_NO_UPDATE_CHECK": "1",
        "FORCE_COLOR": "false",
    }


def _bundler_ready(cache: Path) -> bool:
    try:
        deno_cache = cache / "deno-cache"
        return (
            deno_cache.resolve() == deno_cache.absolute()
            and deno_cache.is_dir()
            and (cache / BUNDLER_MARKER).read_text(encoding="ascii") == bgutil.SOURCE_COMMIT
        )
    except (OSError, UnicodeError):
        return False


def prepare_bundler(source: Path, cache: Path, deno: Path | None) -> str:
    """Warm Deno's esbuild helper using a standalone, dependency-free input."""
    try:
        source = source.resolve()
        resolved_cache = cache.resolve()
        if source.is_relative_to(resolved_cache) or resolved_cache.is_relative_to(source):
            return "source-target-overlap"
        if not _is_lean_source(source):
            return "lean-source-unverified"
        if deno is None or not deno.is_file():
            return "deno-missing"
        source_cache = source / "deno-cache"
        if not source_cache.is_dir():
            return "lean-cache-missing"
        try:
            cache.mkdir(parents=False)
        except FileExistsError:
            return "already-prepared" if _bundler_ready(cache) else "cache-exists-unverified"
        prepared = False
        try:
            deno_cache = cache / "deno-cache"
            shutil.copytree(source_cache, deno_cache)
            with tempfile.TemporaryDirectory(dir=cache) as temporary:
                workdir = Path(temporary)
                (workdir / "main.ts").write_text("export const ready = true;\n", encoding="utf-8")
                result = subprocess.run(
                    [str(deno), "bundle", "--no-config", "--no-lock", "--node-modules-dir=none", "main.ts"],
                    cwd=workdir, env=_deno_environment(deno_cache),
                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                    timeout=BUNDLER_TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            if result.returncode:
                reason = _compile_failure_reason(result.stderr)
                return f"bundle-failed | exit_code={result.returncode} | reason={reason}"
            (cache / BUNDLER_MARKER).write_text(bgutil.SOURCE_COMMIT, encoding="ascii")
            prepared = True
            return "prepared"
        except subprocess.TimeoutExpired:
            return "bundle-timeout"
        finally:
            if not prepared:
                shutil.rmtree(cache, ignore_errors=True)
    except (OSError, ValueError):
        return "prepare-setup-failed"


def compile_command(deno: Path, output: Path, variant: str) -> list[str]:
    """Use cached, pinned dependencies and the source launcher permissions."""
    if variant not in VARIANTS:
        raise ValueError("unknown variant")
    command = [
        str(deno), "compile", "--no-check", "--cached-only",
        "--frozen-lockfile", "--node-modules-dir=manual",
        "--allow-env", "--allow-net", "--allow-read=.", "--allow-ffi=.",
    ]
    if variant != "unbundled":
        command.insert(2, "--bundle")
    if variant == "extracted":
        command.append("--self-extracting")
    command.extend(["--output", str(output), "../src/main.ts"])
    return command


def _compiled_marker(variant: str, binary: Path) -> dict[str, str | int]:
    """Hash once during build, but NEVER in the cold-start probe."""
    digest = hashlib.sha256()
    with binary.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return {
        "schema": 1,
        "source_commit": bgutil.SOURCE_COMMIT,
        "variant": variant,
        "size": binary.stat().st_size,
        "sha256": digest.hexdigest(),
    }


def _looks_prepared(target: Path, variant: str, *, hash_file: bool = False) -> bool:
    """Check a tiny marker and stat. Do not pre-warm binary for a cold probe."""
    try:
        binary = target / binary_name(variant)
        marker = bgutil.read_compiled_candidate(binary, variant)
        return marker is not None and (not hash_file or _compiled_marker(variant, binary) == marker)
    except (OSError, ValueError):
        return False


def _compile_failure_reason(stderr: bytes) -> str:
    """Classify known Deno errors without copying any compiler output."""
    message = stderr.decode("utf-8", errors="replace").lower()
    if not message.strip():
        return "no-stderr"
    invalid_option = re.search(r"(?:unexpected|unknown) (?:argument|option)\s+['`\"]?(--[\w-]+)", message)
    if invalid_option:
        option = invalid_option[1]
        if option in ("--bundle", "--cached-only", "--frozen-lockfile", "--node-modules-dir", "--self-extracting"):
            return f"unsupported-cli-option:{option}"
        return "unsupported-cli-option"
    for pattern, reason in (
        (r"lockfile.*(?:out of date|frozen|integrity|version)|(?:frozen|invalid).*lockfile", "lockfile-error"),
        (r"not (?:found in (?:the )?cache|cached)", "dependency-cache-error"),
        (r"permission denied|access is denied|os error 5\b", "access-denied"),
        (r"native (?:addon|module)|napi|\.node\b", "native-addon-error"),
        (r"failed to download|error downloading", "download-error"),
        (r"module not found|cannot find (?:module|package)|could not resolve", "module-resolution-error"),
    ):
        if re.search(pattern, message):
            return reason
    return "unclassified"


def _cache_miss_reference(stderr: bytes, lockfile: Path) -> str:
    """Report only a pinned public package name or known public host."""
    match = re.search(
        r"\b(?P<npm>npm )?(?:package|specifier|module) not found in (?:the )?cache:"
        r"[ \t]*[\"']?(?P<reference>[^\s,\"']+)",
        stderr.decode("utf-8", errors="replace"),
        re.IGNORECASE,
    )
    if not match:
        return "unavailable"
    reference = match["reference"]
    if reference.startswith(("https://", "http://")):
        try:
            host = urlsplit(reference).netloc.lower()
        except ValueError:
            return "remote"
        return host if host in PUBLIC_DEPENDENCY_HOSTS else "remote"
    if not match["npm"] and not reference.startswith("npm:"):
        return "unavailable"
    package = re.match(r"(?:npm:)?((?:@[a-z0-9_.-]+/)?[a-z0-9_.-]+)(?=[@/]|$)", reference)
    if not package:
        return "npm"
    name = package[1]
    if name in PUBLIC_WINDOWS_BUNDLER_PACKAGES:
        return f"npm:{name}"
    try:
        with lockfile.open("rb") as stream:
            data = stream.read(128 * 1024).replace(b"\r\n", b"\n")
        if hashlib.sha256(data).hexdigest() == PUBLIC_LOCK_SHA256:
            if any(key.startswith(name + "@") for key in json.loads(data)["npm"]):
                return f"npm:{name}"
    except OSError:
        pass
    return "npm"


def build(
    source: Path, target: Path, deno: Path | None, variant: str, *, trace: _ProbeTrace | None = None,
) -> str:
    """Compile to a new, fixed, diagnostics-only directory; never overwrite."""
    if variant not in VARIANTS:
        return "unsupported-variant"
    try:
        source = source.resolve()
        target = target.resolve()
        if source == target or source in target.parents or target in source.parents:
            return "source-target-overlap"
        if target.exists() or target.is_symlink():
            return "already-built" if _looks_prepared(target, variant, hash_file=True) else "target-exists-unverified"
        if not _is_lean_source(source):
            return "lean-source-unverified"
        if deno is None or not deno.is_file():
            return "deno-missing"
        cache = target.parent / BUNDLER_CACHE_NAME
        if not _bundler_ready(cache):
            return "bundler-not-prepared"
        if shutil.disk_usage(target.parent.parent).free < MIN_FREE_BYTES:
            return "insufficient-free-space"
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return "target-exists-unverified"
        succeeded = False
        try:
            output = target / binary_name(variant)
            command = compile_command(deno, output, variant)
            if trace is not None:
                trace.record("compile requested")
            result = subprocess.run(
                command,
                cwd=str(source / "server" / "node_modules"),
                env=_deno_environment(cache / "deno-cache"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if trace is not None else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=BUILD_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if trace is not None:
                trace.record(f"compiler exited: code={result.returncode}")
                trace.capture("stdout", result.stdout or b"", live=False)
                trace.capture("stderr", result.stderr or b"", live=False)
            if result.returncode:
                reason = _compile_failure_reason(result.stderr)
                summary = f"compile-failed | exit_code={result.returncode} | reason={reason}"
                if reason == "dependency-cache-error":
                    reference = _cache_miss_reference(result.stderr, source / "server" / "deno.lock")
                    summary += f" | cache_ref={reference}"
                return summary
            if not output.is_file() or output.stat().st_size < 1:
                return "compiled-binary-missing"
            metadata = _compiled_marker(variant, output)
            (target / MARKER_NAME).write_text(
                json.dumps(metadata, sort_keys=True), encoding="utf-8",
            )
            if not _looks_prepared(target, variant, hash_file=False):
                return "compiled-verification-failed"
            succeeded = True
            return "built"
        except subprocess.TimeoutExpired as error:
            if trace is not None:
                trace.record("compiler timed out")
                trace.capture("stdout", error.stdout or b"", live=False)
                trace.capture("stderr", error.stderr or b"", live=False)
            return "compile-timeout"
        except (OSError, ValueError) as error:
            if trace is not None:
                trace.record(f"compile setup error: {type(error).__name__}, os_error={getattr(error, 'winerror', None) or getattr(error, 'errno', None)}")
            return "compile-setup-failed"
        finally:
            if not succeeded:
                # Delete only the directory that this invocation created.
                shutil.rmtree(target, ignore_errors=True)
    except (OSError, ValueError):
        return "build-preflight-failed"


def _allocate_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _ping_status(url: str) -> str:
    try:
        opener = build_opener(ProxyHandler({}))
        request = Request(url + "/ping", headers={"Accept": "application/json"})
        with opener.open(request, timeout=0.4) as response:
            if response.status != 200:
                return f"http-{response.status}"
            body = json.loads(response.read(2048))
    except HTTPError as error:
        error.close()
        return f"http-{error.code}"
    except URLError as error:
        if isinstance(error.reason, TimeoutError):
            return "timeout"
        if isinstance(error.reason, ConnectionRefusedError):
            return "connection-refused"
        return "connection-error"
    except TimeoutError:
        return "timeout"
    except OSError:
        return "connection-error"
    except (ValueError, TypeError):
        return "invalid-response"
    return "ready" if isinstance(body, dict) and body.get("version") == bgutil.PROVIDER_VERSION else "version-mismatch"


def _terminate(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass


class _ProbeTrace:
    """In-memory capture for the explicitly requested local report."""

    def __init__(self) -> None:
        self.started_at = datetime.now(timezone.utc).isoformat()
        self.start = time.monotonic()
        self.lock = threading.Lock()
        self.capture_enabled = True
        self.progress: Callable[[str], None] | None = None
        self.events: list[str] = []
        self.streams = {"stdout": bytearray(), "stderr": bytearray()}
        self.overflow = {"stdout": bytearray(), "stderr": bytearray()}
        self.received = {"stdout": 0, "stderr": 0}

    def _record(self, event: str) -> None:
        elapsed_ms = round((time.monotonic() - self.start) * 1000)
        self.events.append(f"+{elapsed_ms} ms {event}")

    def record(self, event: str) -> None:
        with self.lock:
            self._record(event)

    def capture(self, channel: str, block: bytes, *, live: bool = True) -> None:
        with self.lock:
            if not self.capture_enabled:
                return
            if live and block and not self.received[channel]:
                self._record(f"first {channel} bytes")
            self.received[channel] += len(block)
            buffer = self.streams[channel]
            remaining = PROBE_LOG_STREAM_LIMIT - len(buffer)
            buffer.extend(block[:remaining])
            if len(block) > remaining:
                tail = self.overflow[channel]
                tail.extend(block[max(remaining, len(block) - PROBE_LOG_TAIL_LIMIT):])
                del tail[:-PROBE_LOG_TAIL_LIMIT]

    def stop_capture(self) -> None:
        with self.lock:
            self.capture_enabled = False

    def render(self, variant: str, status: str, elapsed: int, attempts: int | None) -> str:
        with self.lock:
            probing = attempts is not None
            phase = "probe" if probing else "build"
            timeout = PROBE_TIMEOUT if probing else BUILD_TIMEOUT
            result = f"result={status} elapsed_ms={elapsed}"
            if probing:
                result += f" ping_attempts={attempts}"
            lines = [
                f"RR-V Stage03 P3 verbose {phase}",
                f"started_at_utc={self.started_at}",
                f"variant={variant} expected_version={bgutil.PROVIDER_VERSION} timeout_s={timeout}",
                result,
                "\n--- timeline ---", *self.events,
            ]
            for channel, buffer in self.streams.items():
                lines.append(f"\n--- {channel} ({len(buffer)} of {self.received[channel]} bytes captured) ---")
                lines.append(buffer.decode("utf-8", errors="replace") if buffer else "(empty)")
                tail = self.overflow[channel]
                if tail:
                    omitted = self.received[channel] - len(buffer) - len(tail)
                    lines.append(f"--- {channel} continuation ({omitted} intervening bytes omitted) ---")
                    lines.append(tail.decode("utf-8", errors="replace"))
            return "\n".join(lines) + "\n"


def _drain_probe_stream(
    stream: BinaryIO, channel: str, tail: deque[bytes], trace: _ProbeTrace | None,
) -> None:
    try:
        with stream:
            read = getattr(stream, "read1", stream.read)
            while block := read(1024):
                if channel == "stderr":
                    tail.append(block)
                if trace is not None:
                    trace.capture(channel, block)
    except (OSError, ValueError):
        pass


def _probe_failure_reason(stderr: bytes) -> str:
    """Recognize startup signatures without returning any child output."""
    message = stderr.lower()
    if not message.strip():
        return "no-stderr"
    for pattern, reason in (
        (rb"eaddrinuse|could not listen on|address already in use", "listen-error"),
        (rb"notcapable|permission denied|requires? (?:--allow|(?:ffi|read|env|net) access)", "permission-error"),
        (rb"dynamic require of .*not supported|require is not defined|err_require_esm", "module-format-error"),
        (rb"err_dlopen_failed|\bdlopen\b|native (?:addon|module)|\.node\b", "native-addon-error"),
        (rb"err_module_not_found|module not found|cannot find (?:module|package)", "module-resolution-error"),
        (rb"enoent|no such file or directory|os error [23]\b", "file-not-found"),
    ):
        if re.search(pattern, message):
            return reason
    return "unclassified"


@contextmanager
def _launch_progress(notify: Callable[[str], None] | None, started_at: float, timeout: float) -> Iterator[None]:
    if notify is None:
        yield
        return
    notify("launch-requested")
    finished = threading.Event()

    def heartbeat() -> None:
        while not finished.wait(LAUNCH_PROGRESS_INTERVAL):
            elapsed = time.monotonic() - started_at
            message = f"waiting-for-process | elapsed_ms={round(elapsed * 1000)}"
            if elapsed >= timeout:
                message += " | startup-budget-elapsed"
            try:
                notify(message)
            except OSError:
                return

    worker = threading.Thread(target=heartbeat, daemon=True)
    worker.start()
    try:
        yield
    finally:
        finished.set()
        worker.join()


def probe(
    target: Path, variant: str, *, timeout: float = PROBE_TIMEOUT, trace: _ProbeTrace | None = None,
    after_ready: Callable[[str], None] | None = None,
) -> tuple[str, int, int]:
    """Launch only the compiled file from an isolated cwd. No source pre-run."""
    if variant not in VARIANTS:
        return "unsupported-variant", 0, 0
    if not _looks_prepared(target, variant, hash_file=False):
        return "not-built-or-invalid", 0, 0
    return _probe_server([str(target / binary_name(variant))], target, timeout=timeout,
                         trace=trace, after_ready=after_ready)


def _probe_server(
    command: list[str], cwd: Path, *, timeout: float = PROBE_TIMEOUT,
    trace: _ProbeTrace | None = None, after_ready: Callable[[str], None] | None = None,
    env: dict[str, str] | None = None, kind: str = "compiled",
) -> tuple[str, int, int]:
    try:
        port = _allocate_port()
    except OSError:
        return "local-port-unavailable", 0, 0
    start = time.monotonic()
    attempts = 0
    process = None
    phase = "launch"
    ready_elapsed = None
    # Drain continuously to avoid blocking the child on a full pipe.
    stderr_tail: deque[bytes] = deque(maxlen=16)
    readers = []
    record = trace.record if trace is not None else lambda event: None
    notify = trace.progress if trace is not None else None
    try:
        record("launch requested")
        with _launch_progress(notify, start, timeout):
            process = subprocess.Popen(
                [*command, "--host", "127.0.0.1", "--port", str(port)],
                cwd=str(cwd), env=env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if trace is not None else subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            launch_elapsed = time.monotonic() - start
            record("process launched")
        phase = "readiness"
        if notify is not None:
            notify(f"process-launched | elapsed_ms={round(launch_elapsed * 1000)}")
        for channel in ("stderr", "stdout"):
            stream = getattr(process, channel, None)
            if stream is not None:
                reader = threading.Thread(
                    target=_drain_probe_stream, args=(stream, channel, stderr_tail, trace), daemon=True,
                )
                reader.start()
                readers.append(reader)
        if launch_elapsed >= timeout:
            return f"{kind}-launch-timeout", round(launch_elapsed * 1000), attempts
        url = f"http://127.0.0.1:{port}"
        while time.monotonic() - start < timeout:
            code = process.poll()
            if code is not None:
                elapsed = round((time.monotonic() - start) * 1000)
                record(f"process exited before readiness: code={code}")
                for reader in readers:
                    reader.join(timeout=0.2)
                reason = _probe_failure_reason(b"".join(stderr_tail.copy()))
                status = f"{kind}-exited-before-ready:code={int(code)} | reason={reason}"
                return status, elapsed, attempts
            attempts += 1
            record(f"ping {attempts} started")
            ping_status = _ping_status(url)
            record(f"ping {attempts}: {ping_status}")
            if ping_status == "ready":
                ready_elapsed = round((time.monotonic() - start) * 1000)
                if after_ready is not None:
                    phase = "token"
                    if trace is not None:
                        trace.stop_capture()
                    if notify is not None:
                        notify(f"ready | elapsed_ms={ready_elapsed} | checking-token")
                    after_ready(url)
                return ("late-ready" if ready_elapsed > PRODUCTION_FIRST_BUDGET_MS else "ready"), ready_elapsed, attempts
            time.sleep(0.2)
        return f"{kind}-timeout", round((time.monotonic() - start) * 1000), attempts
    except KeyboardInterrupt:
        if notify is None:
            raise
        interrupted_at = round((time.monotonic() - start) * 1000)
        record(f"interrupted during {phase} at elapsed_ms={interrupted_at}")
        notify(f"interrupted-{phase} | elapsed_ms={interrupted_at}")
        return f"{kind}-interrupted-{phase}", interrupted_at if ready_elapsed is None else ready_elapsed, attempts
    except (OSError, ValueError) as error:
        record(f"launch or probe failed: {type(error).__name__}, os_error={getattr(error, 'winerror', None) or getattr(error, 'errno', None)}")
        return f"{kind}-launch-error", round((time.monotonic() - start) * 1000), attempts
    finally:
        if process is not None:
            _terminate(process)
            record(f"cleanup finished: code={process.poll()}")
        for reader in readers:
            if reader.is_alive():
                reader.join(timeout=0.2)
                if reader.is_alive():
                    record("output stream did not finish draining")


def _comparison_metadata(source: Path, deno: Path | None, ytdlp: Path | None = None) -> str:
    commands = [
        ("git_commit", ["git", "rev-parse", "HEAD"], rb"(?m)^([a-f0-9]{40,64})\r?$"),
    ]
    if deno is not None:
        commands.append(("deno", [str(deno), "--version"], rb"(?m)^deno ([0-9]+\.[0-9]+\.[0-9]+[\w.+-]*)"))
    if ytdlp is not None:
        commands.append(("yt_dlp", [str(ytdlp), "--version"], rb"(?m)^([0-9]+\.[0-9]+\.[0-9]+[\w.+-]*)\r?$"))
    fields = [f"os={platform.system()} {platform.version()} arch={platform.machine()}",
              f"bgutils={bgutil.PROVIDER_VERSION}"]
    for name, command, pattern in commands:
        value = "unavailable"
        try:
            result = subprocess.run(
                command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            match = re.search(pattern, result.stdout or b"")
            if result.returncode == 0 and match:
                value = match[1].decode("ascii")
        except (OSError, subprocess.TimeoutExpired):
            pass
        fields.append(f"{name}={value}")
    try:
        lock = json.loads((source / "server" / "deno.lock").read_text(encoding="utf-8"))
        for package in ("jsdom", "canvas"):
            versions = sorted({
                match[0] for specifier, resolved in lock["specifiers"].items()
                if specifier.startswith(f"npm:{package}@") and isinstance(resolved, str)
                and (match := re.match(r"\d+\.\d+\.\d+", resolved))
            })
            fields.append(f"{package}={','.join(versions) or 'unavailable'}")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        fields.append("npm_lock_versions=unavailable")
    return "\n".join(fields) + "\n"


def _redact_comparison_report(report: str) -> str:
    report = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", report)
    for home in {str(Path.home()), os.environ.get("USERPROFILE", "")}:
        if not home or len(home.rstrip("\\/")) < 4:
            continue
        forward = home.replace("\\", "/")
        for form in {home, forward, home.replace("\\", "\\\\"), quote(forward, safe="/:")}:
            report = re.sub(re.escape(form), "<user-home>", report, flags=re.IGNORECASE)
    report = re.sub(r"(?i)[a-z]:[/\\]+users[/\\]+[^/\\\r\n\"'<>]+(?=[/\\])", "<user-home>", report)
    report = re.sub(r"(?i)(https?://)[^\s/@]+@", r"\1<redacted>@", report)
    report = re.sub(r"(?i)([?&](?:pot|sig|lsig|spc|token|sessionid|jwt|access_token|refresh_token|api_key)=)[^&\s\"']+", r"\1<redacted>", report)
    report = re.sub(r"(?im)(\b(?:authorization|proxy-authorization|cookie|set-cookie)\s*:\s*)[^\r\n]+", r"\1<redacted>", report)
    report = re.sub(
        r"(?i)(\b(?:password|passwd|api[_-]?key|(?:access|refresh|po)[_ -]?token|token|client[_-]?secret)"
        r"\b[\"']?\s*[=:]\s*)(?:\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*'|[^\s,&;\"'}\]]+)",
        r"\1<redacted>", report,
    )
    report = re.sub(r"(?i)(\b(?:authorization|proxy-authorization|cookie|set-cookie)[\"']\s*:\s*)"
                    r"(?:\"(?:\\.|[^\"\\\r\n])*\"|'(?:\\.|[^'\\\r\n])*')", r"\1<redacted>", report)
    return report


def compare_unbundled(source: Path, target: Path, deno: Path | None) -> int:
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="bgutil-p3-compare-", suffix=".log",
            dir=target.parent, delete=False,
        ) as report:
            report.write(_comparison_metadata(source, deno))
            compile_args = compile_command(Path("deno.exe"), Path("candidate.exe"), "unbundled")[1:]
            report.write("compile_arguments=" + " ".join(compile_args) + "\n")
            build_trace = _ProbeTrace()
            build_status = build(source, target, deno, "unbundled", trace=build_trace)
            elapsed = round((time.monotonic() - build_trace.start) * 1000)
            report.write("\n" + _redact_comparison_report(build_trace.render("unbundled", build_status, elapsed, None)))
            report.flush()
            print(f"BGUTIL P3 BUILD: {build_status} | variant=unbundled", flush=True)
            probe_status = "skipped-build-failed"
            if build_status in ("built", "already-built"):
                report.write(f"\ncandidate_bytes={(target / binary_name('unbundled')).stat().st_size}\n")
                probe_trace = _ProbeTrace()
                probe_status, elapsed, attempts = probe(target, "unbundled", trace=probe_trace)
                report.write("\n" + _redact_comparison_report(probe_trace.render("unbundled", probe_status, elapsed, attempts)))
                print(f"BGUTIL P3 PROBE: {probe_status} | variant=unbundled | elapsed_ms={elapsed} | ping_attempts={attempts}")
            else:
                report.write("\nprobe=skipped-build-failed\n")
        print(f"BGUTIL P3 LOG: %LOCALAPPDATA%\\RR-V\\diagnostics\\{Path(report.name).name}")
        return 0 if probe_status in ("ready", "late-ready") else 1
    except OSError:
        print("BGUTIL P3 COMPARE: report-or-candidate-io-error")
        return 1


def _boot_snapshot() -> str:
    try:
        get_uptime = ctypes.windll.kernel32.GetTickCount64
        get_uptime.restype = ctypes.c_uint64
        uptime_ms = get_uptime()
        estimated_boot = datetime.now(timezone.utc) - timedelta(milliseconds=uptime_ms)
        return f"boot_utc_estimate={estimated_boot.isoformat(timespec='seconds')} uptime_at_start_ms={uptime_ms}\n"
    except (AttributeError, OSError):
        return "boot_utc_estimate=unavailable uptime_at_start_ms=unavailable\n"


def _verify_live_token(source: Path, base_url: str, ytdlp: Path | None, deno: Path | None) -> tuple[str, dict]:
    if ytdlp is None or deno is None:
        return "simulation-tools-missing", {}
    if not _is_lean_source(source):
        return "lean-plugin-unverified", {}
    helpers = runpy.run_path(str(Path(__file__).with_name("bgutil_token_fallback_probe.py")))
    command = helpers["_build_command"](ytdlp, deno, source, base_url, False, helpers["DEFAULT_VIDEO"])
    try:
        completed = subprocess.run(
            command, stdin=subprocess.DEVNULL, capture_output=True, encoding="utf-8", errors="replace",
            timeout=TOKEN_PROBE_TIMEOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return "simulation-timeout", {}
    except OSError:
        return "simulation-launch-failed", {}
    combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
    signals = helpers["inspect_trace"](combined, completed.returncode)
    return helpers["classify"]("bgutil", signals), asdict(signals)


def cold_check(source: Path, target: Path, mode: str, deno: Path | None, ytdlp: Path | None) -> int:
    trace = _ProbeTrace()
    token_status = "skipped-server-not-ready"
    token_elapsed = None
    token_details = {}

    def verify_token(base_url: str) -> None:
        nonlocal token_status, token_elapsed, token_details
        trace.record("yt-dlp token simulation requested; server output capture stopped")
        start = time.monotonic()
        token_status, token_details = _verify_live_token(source, base_url, ytdlp, deno)
        token_elapsed = round((time.monotonic() - start) * 1000)
        trace.record(f"yt-dlp token simulation finished: {token_status}")

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix=f"bgutil-p3-cold-{mode}-", suffix=".log",
            dir=target.parent, delete=False,
        ) as report:
            report.write(f"mode={mode} startup_budget_ms={PRODUCTION_FIRST_BUDGET_MS}\n" + _boot_snapshot())
            report.flush()
            print(f"BGUTIL P3 LOG: %LOCALAPPDATA%\\RR-V\\diagnostics\\{Path(report.name).name}", flush=True)

            def show_progress(message: str) -> None:
                report.write(f"progress={message}\n")
                report.flush()
                print(f"BGUTIL P3 PROGRESS: {message}", flush=True)

            trace.progress = show_progress
            if mode == "compiled":
                status, elapsed, attempts = probe(target, "unbundled", trace=trace, after_ready=verify_token)
            elif deno is None or not deno.is_file():
                status, elapsed, attempts = "deno-executable-missing", 0, 0
            elif not _is_lean_source(source):
                status, elapsed, attempts = "lean-source-unverified", 0, 0
            else:
                status, elapsed, attempts = _probe_server(
                    [str(deno), "run", "--allow-env", "--allow-net", "--allow-ffi=.", "--allow-read=.", "../src/main.ts"],
                    source / "server" / "node_modules", env=_deno_environment(source / "deno-cache"),
                    kind="source", trace=trace, after_ready=verify_token,
                )
            variant = "unbundled" if mode == "compiled" else "p2-lean-source"
            if status.endswith("-interrupted-token"):
                token_status = "interrupted"
            report.write(_redact_comparison_report(trace.render(variant, status, elapsed, attempts)))
            report.write(f"\ntoken_result={token_status}\n")
            if token_elapsed is not None:
                report.write(f"token_elapsed_ms={token_elapsed}\n")
            report.write("".join(f"token_{key}={value}\n" for key, value in token_details.items()))
            report.flush()
            # Read tool versions only after server timing, so Deno is not pre-warmed.
            if "-interrupted-" in status:
                report.write("\nenvironment=skipped-after-interrupt\n")
            else:
                version_deno = deno
                if status == "source-launch-timeout":
                    version_deno = None
                    report.write("\ndeno_version_probe=skipped-after-launch-timeout\n")
                report.write("\n--- environment ---\n" + _comparison_metadata(source, version_deno, ytdlp))
            if mode == "compiled" and status in ("ready", "late-ready"):
                report.write(f"candidate_bytes={(target / binary_name('unbundled')).stat().st_size}\n")
        print(f"BGUTIL P3 COLD: {status} | mode={mode} | elapsed_ms={elapsed} | ping_attempts={attempts}")
        print(f"BGUTIL P3 TOKEN: {token_status}")
        if "-interrupted-" in status:
            return 130
        return 0 if status in ("ready", "late-ready") and token_status == "bgutil-token-confirmed" else 1
    except OSError:
        print("BGUTIL P3 COLD: report-io-error")
        return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage03 P3 isolated Deno bundle/compile experiment")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-bundler", action="store_true", help="Prepare esbuild in the isolated P3 cache")
    action.add_argument("--build", action="store_true", help="Compile a separate candidate once")
    action.add_argument("--probe", action="store_true", help="Probe an existing candidate without pre-warming it")
    action.add_argument("--verify", action="store_true", help="Hash-check existing compiled file")
    action.add_argument("--compare", action="store_true", help="Build and probe an unbundled candidate with a local report")
    action.add_argument("--cold-check", choices=("compiled", "source"), help="Time one first start and verify live token issuance")
    parser.add_argument("--variant", choices=VARIANTS, default="bundled")
    parser.add_argument("--verbose", action="store_true", help="With --probe, save a detailed log locally")
    args = parser.parse_args(argv)
    if args.verbose and not args.probe:
        parser.error("--verbose requires --probe")
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local or os.name != "nt":
        print("BGUTIL P3: requires-windows-localappdata")
        return 2
    source, target = paths_for(Path(local), "unbundled" if args.compare or args.cold_check else args.variant)
    if args.cold_check:
        return cold_check(source, target, args.cold_check, find_executable("deno.exe"), find_executable("yt-dlp.exe"))
    if args.compare:
        return compare_unbundled(source, target, find_executable("deno.exe"))
    if args.prepare_bundler:
        status = prepare_bundler(source, target.parent / BUNDLER_CACHE_NAME, find_executable("deno.exe"))
        print(f"BGUTIL P3 PREPARE: {status}")
        return 0 if status in ("prepared", "already-prepared") else 1
    if args.build:
        status = build(source, target, find_executable("deno.exe"), args.variant)
        print(f"BGUTIL P3 BUILD: {status} | variant={args.variant}")
        print("Original BgUtils and RR-V production runtime were not modified.")
        return 0 if status in ("built", "already-built") else 1
    if args.verify:
        status = "verified" if _looks_prepared(target, args.variant, hash_file=True) else "not-built-or-invalid"
        print(f"BGUTIL P3 VERIFY: {status} | variant={args.variant}")
        return 0 if status == "verified" else 1
    if args.verbose:
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix="bgutil-p3-probe-", suffix=".log",
                dir=target.parent, delete=False,
            ) as report:
                trace = _ProbeTrace()
                status, elapsed, attempts = probe(target, args.variant, trace=trace)
                report.write(trace.render(args.variant, status, elapsed, attempts))
            print(f"BGUTIL P3 LOG: %LOCALAPPDATA%\\RR-V\\diagnostics\\{Path(report.name).name}")
        except OSError:
            print("BGUTIL P3 LOG: write-failed")
            return 1
    else:
        status, elapsed, attempts = probe(target, args.variant)
    print(f"BGUTIL P3 PROBE: {status} | variant={args.variant} | elapsed_ms={elapsed} | ping_attempts={attempts}")
    print("No YouTube, WPC, Chrome, tokens, cookies or downloads were used.")
    return 0 if status in ("ready", "late-ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
