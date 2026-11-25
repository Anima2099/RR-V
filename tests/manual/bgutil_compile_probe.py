"""Developer-only Stage03 P3: compile and probe a separate BgUtils executable.

Uses the already isolated and verified P2 lean installation as its build input.
Never modifies RR-V's production launcher or the original BgUtils install.
The pinned upstream provider is GPL-3.0-only; do not distribute test binaries.
"""

from __future__ import annotations

import argparse
from collections import deque
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from typing import BinaryIO
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.paths import find_executable
from services import bgutil_http_service as bgutil

# A self-extracting variant may be tried separately if native canvas cannot
# run from the ordinary compiled bundle. It is NOT the default: extraction
# adds file writes and can undermine the cold-start optimization objective.
VARIANTS = ("bundled", "extracted")
MARKER_NAME = "rrv-p3-compiled.json"
LEAN_MARKER = "rrv-lean-experiment.json"
BUILD_TIMEOUT = 360
BUNDLER_TIMEOUT = 120
BUNDLER_CACHE_NAME = "bgutil-stage03-p3-cache"
BUNDLER_MARKER = "rrv-p3-bundler-ready"
PROBE_TIMEOUT = 70.0
PROBE_LOG_STREAM_LIMIT = 256 * 1024
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
        str(deno), "compile", "--bundle", "--no-check", "--cached-only",
        "--frozen-lockfile", "--node-modules-dir=manual",
        "--allow-env", "--allow-net", "--allow-read=.", "--allow-ffi=.",
    ]
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
        marker = json.loads((target / MARKER_NAME).read_text(encoding="utf-8"))
        if not isinstance(marker, dict):
            return False
        binary = target / binary_name(variant)
        if (
            marker.get("schema") != 1
            or marker.get("source_commit") != bgutil.SOURCE_COMMIT
            or marker.get("variant") != variant
            or not isinstance(marker.get("size"), int)
            or marker["size"] < 1
            or not isinstance(marker.get("sha256"), str)
            or len(marker["sha256"]) != 64
            or any(character not in "0123456789abcdef" for character in marker["sha256"])
            or not binary.is_file()
            or binary.is_symlink()
            or binary.stat().st_size != marker["size"]
        ):
            return False
        if hash_file and _compiled_marker(variant, binary) != marker:
            return False
        return True
    except (OSError, ValueError, KeyError, TypeError):
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


def build(source: Path, target: Path, deno: Path | None, variant: str) -> str:
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
            result = subprocess.run(
                compile_command(deno, output, variant),
                cwd=str(source / "server" / "node_modules"),
                env=_deno_environment(cache / "deno-cache"),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
                timeout=BUILD_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
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
        except subprocess.TimeoutExpired:
            return "compile-timeout"
        except (OSError, ValueError):
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
        self.events: list[str] = []
        self.streams = {"stdout": bytearray(), "stderr": bytearray()}
        self.received = {"stdout": 0, "stderr": 0}

    def _record(self, event: str) -> None:
        elapsed_ms = round((time.monotonic() - self.start) * 1000)
        self.events.append(f"+{elapsed_ms} ms {event}")

    def record(self, event: str) -> None:
        with self.lock:
            self._record(event)

    def capture(self, channel: str, block: bytes) -> None:
        with self.lock:
            if not self.received[channel]:
                self._record(f"first {channel} bytes")
            self.received[channel] += len(block)
            buffer = self.streams[channel]
            remaining = PROBE_LOG_STREAM_LIMIT - len(buffer)
            buffer.extend(block[:remaining])

    def render(self, variant: str, status: str, elapsed: int, attempts: int) -> str:
        with self.lock:
            lines = [
                "RR-V Stage03 P3 verbose probe (local diagnostic)",
                f"started_at_utc={self.started_at}",
                f"variant={variant} expected_version={bgutil.PROVIDER_VERSION} timeout_s={PROBE_TIMEOUT}",
                f"result={status} elapsed_ms={elapsed} ping_attempts={attempts}",
                "\n--- timeline ---", *self.events,
            ]
            for channel, buffer in self.streams.items():
                lines.append(f"\n--- {channel} ({len(buffer)} of {self.received[channel]} bytes captured) ---")
                lines.append(buffer.decode("utf-8", errors="replace") if buffer else "(empty)")
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


def probe(
    target: Path, variant: str, *, timeout: float = PROBE_TIMEOUT, trace: _ProbeTrace | None = None,
) -> tuple[str, int, int]:
    """Launch only the compiled file from an isolated cwd. No source pre-run."""
    if variant not in VARIANTS:
        return "unsupported-variant", 0, 0
    if not _looks_prepared(target, variant, hash_file=False):
        return "not-built-or-invalid", 0, 0
    binary = target / binary_name(variant)
    try:
        port = _allocate_port()
    except OSError:
        return "local-port-unavailable", 0, 0
    start = time.monotonic()
    attempts = 0
    process = None
    # Drain continuously to avoid blocking the child on a full pipe.
    stderr_tail: deque[bytes] = deque(maxlen=16)
    readers = []
    record = trace.record if trace is not None else lambda event: None
    try:
        record("launch requested")
        process = subprocess.Popen(
            [str(binary), "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(target),  # Never rely on an ambient node_modules cwd.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE if trace is not None else subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        record("process launched")
        for channel in ("stderr", "stdout"):
            stream = getattr(process, channel, None)
            if stream is not None:
                reader = threading.Thread(
                    target=_drain_probe_stream, args=(stream, channel, stderr_tail, trace), daemon=True,
                )
                reader.start()
                readers.append(reader)
        url = f"http://127.0.0.1:{port}"
        while time.monotonic() - start < timeout:
            code = process.poll()
            if code is not None:
                elapsed = round((time.monotonic() - start) * 1000)
                record(f"process exited before readiness: code={code}")
                for reader in readers:
                    reader.join(timeout=0.2)
                reason = _probe_failure_reason(b"".join(stderr_tail.copy()))
                status = f"compiled-exited-before-ready:code={int(code)} | reason={reason}"
                return status, elapsed, attempts
            attempts += 1
            record(f"ping {attempts} started")
            ping_status = _ping_status(url)
            record(f"ping {attempts}: {ping_status}")
            if ping_status == "ready":
                elapsed = round((time.monotonic() - start) * 1000)
                return ("late-ready" if elapsed > PRODUCTION_FIRST_BUDGET_MS else "ready"), elapsed, attempts
            time.sleep(0.2)
        return "compiled-timeout", round((time.monotonic() - start) * 1000), attempts
    except (OSError, ValueError) as error:
        record(f"launch or probe failed: {type(error).__name__}, os_error={getattr(error, 'winerror', None) or getattr(error, 'errno', None)}")
        return "compiled-launch-error", round((time.monotonic() - start) * 1000), attempts
    finally:
        if process is not None:
            _terminate(process)
            record(f"cleanup finished: code={process.poll()}")
        for reader in readers:
            if reader.is_alive():
                reader.join(timeout=0.2)
                if reader.is_alive():
                    record("output stream did not finish draining")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage03 P3 isolated Deno bundle/compile experiment")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--prepare-bundler", action="store_true", help="Prepare esbuild in the isolated P3 cache")
    action.add_argument("--build", action="store_true", help="Compile a separate candidate once")
    action.add_argument("--probe", action="store_true", help="Probe an existing candidate without pre-warming it")
    action.add_argument("--verify", action="store_true", help="Hash-check existing compiled file")
    parser.add_argument("--variant", choices=VARIANTS, default="bundled")
    parser.add_argument("--verbose", action="store_true", help="With --probe, save a detailed log locally")
    args = parser.parse_args(argv)
    if args.verbose and not args.probe:
        parser.error("--verbose requires --probe")
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local or os.name != "nt":
        print("BGUTIL P3: requires-windows-localappdata")
        return 2
    source, target = paths_for(Path(local), args.variant)
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
