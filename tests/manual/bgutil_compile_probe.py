"""Developer-only Stage03 P3: compile and probe a separate BgUtils executable.

Uses the already isolated and verified P2 lean installation as its build input.
Never modifies RR-V's production launcher or the original BgUtils install.
The pinned upstream provider is GPL-3.0-only; do not distribute test binaries.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time
from urllib.error import URLError
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
PROBE_TIMEOUT = 70.0
PRODUCTION_FIRST_BUDGET_MS = 18_000
MIN_FREE_BYTES = 512 * 1024 * 1024


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
        if shutil.disk_usage(target.parent.parent).free < MIN_FREE_BYTES:
            return "insufficient-free-space"
        try:
            target.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            return "target-exists-unverified"
        succeeded = False
        try:
            output = target / binary_name(variant)
            environment = os.environ.copy()
            environment.update({
                "DENO_DIR": str(source / "deno-cache"),
                "DENO_NO_PROMPT": "1",
                "DENO_NO_UPDATE_CHECK": "1",
                "FORCE_COLOR": "false",
            })
            result = subprocess.run(
                compile_command(deno, output, variant),
                cwd=str(source / "server" / "node_modules"),
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=BUILD_TIMEOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            if result.returncode:
                return "compile-failed"
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


def _ping(url: str) -> bool:
    try:
        opener = build_opener(ProxyHandler({}))
        request = Request(url + "/ping", headers={"Accept": "application/json"})
        with opener.open(request, timeout=0.4) as response:
            if response.status != 200:
                return False
            body = json.loads(response.read(2048))
        return isinstance(body, dict) and body.get("version") == bgutil.PROVIDER_VERSION
    except (OSError, URLError, ValueError, TypeError):
        return False


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


def probe(target: Path, variant: str, *, timeout: float = PROBE_TIMEOUT) -> tuple[str, int, int]:
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
    try:
        process = subprocess.Popen(
            [str(binary), "--host", "127.0.0.1", "--port", str(port)],
            cwd=str(target),  # Never rely on an ambient node_modules cwd.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        url = f"http://127.0.0.1:{port}"
        while time.monotonic() - start < timeout:
            code = process.poll()
            if code is not None:
                return f"compiled-exited-before-ready:code={int(code)}", round((time.monotonic() - start) * 1000), attempts
            attempts += 1
            if _ping(url):
                elapsed = round((time.monotonic() - start) * 1000)
                return ("late-ready" if elapsed > PRODUCTION_FIRST_BUDGET_MS else "ready"), elapsed, attempts
            time.sleep(0.2)
        return "compiled-timeout", round((time.monotonic() - start) * 1000), attempts
    except (OSError, ValueError):
        return "compiled-launch-error", round((time.monotonic() - start) * 1000), attempts
    finally:
        if process is not None:
            _terminate(process)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage03 P3 isolated Deno bundle/compile experiment")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--build", action="store_true", help="Compile a separate candidate once")
    action.add_argument("--probe", action="store_true", help="Probe an existing candidate without pre-warming it")
    action.add_argument("--verify", action="store_true", help="Hash-check existing compiled file")
    parser.add_argument("--variant", choices=VARIANTS, default="bundled")
    args = parser.parse_args(argv)
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if not local or os.name != "nt":
        print("BGUTIL P3: requires-windows-localappdata")
        return 2
    source, target = paths_for(Path(local), args.variant)
    if args.build:
        status = build(source, target, find_executable("deno.exe"), args.variant)
        print(f"BGUTIL P3 BUILD: {status} | variant={args.variant}")
        print("Original BgUtils and RR-V production runtime were not modified.")
        return 0 if status in ("built", "already-built") else 1
    if args.verify:
        status = "verified" if _looks_prepared(target, args.variant, hash_file=True) else "not-built-or-invalid"
        print(f"BGUTIL P3 VERIFY: {status} | variant={args.variant}")
        return 0 if status == "verified" else 1
    status, elapsed, attempts = probe(target, args.variant)
    print(f"BGUTIL P3 PROBE: {status} | variant={args.variant} | elapsed_ms={elapsed} | ping_attempts={attempts}")
    print("No YouTube, WPC, Chrome, tokens, cookies or downloads were used.")
    return 0 if status in ("ready", "late-ready") else 1


if __name__ == "__main__":
    raise SystemExit(main())
