"""Developer-only cross-boot Deno runtime / BgUtils import / server probe.

Run different --first modes on separate Windows boots. No YouTube, WPC, tokens,
cookies or downloads. Deno stdout/stderr and private paths are never printed
or recorded. This tool never changes production startup budgets.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_PREVIOUS_SCRIPT = Path(__file__).with_name("bgutil_startup_trace.py")
_SPEC = importlib.util.spec_from_file_location("rrv_bgutil_startup_trace_boot", _PREVIOUS_SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
TRACE = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = TRACE
_SPEC.loader.exec_module(TRACE)

# The production budget is 12 seconds plus up to 6 seconds on the first use.
# These limits apply ONLY to this manual diagnostic tool.
PROBE_DEADLINE = 60.0
ORDERS = {
    "server": ("server", "server-repeat", "imports", "runtime"),
    "runtime": ("runtime", "imports", "server", "server-repeat"),
    "imports": ("imports", "runtime", "server", "server-repeat"),
}
_MARKER_RUNTIME = "RRV_DIAGNOSTIC_DENO_RUNTIME_READY"
_MARKER_IMPORTS = "RRV_DIAGNOSTIC_BGUTIL_IMPORTS_READY"
# Importing the module by an absolute file URI ensures that Deno resolves
# relative imports exactly as the real upstream source does on Windows. The
# URI is passed ONLY through stdin, never in the command line or diagnostics.
def _module_stdin(home: Path) -> str:
    uri = (home / "server" / "src" / "session_manager.ts").resolve().as_uri()
    return (
        "import { SessionManager } from " + json.dumps(uri) + ";\n"
        'if (typeof SessionManager !== "function") throw new Error("unexpected module");\n'
        f'console.log("{_MARKER_IMPORTS}");\n'
    )


@dataclass(frozen=True)
class StageResult:
    stage: str
    result: str
    elapsed_ms: int
    first_output_ms: int = 0
    announced_ms: int = 0
    tcp_ms: int = 0
    ping_ms: int = 0


def stage_sequence(first: str) -> tuple[str, ...]:
    if first not in ORDERS:
        raise ValueError("invalid first phase")
    return ORDERS[first]


def _deno_env(home: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update({
        "DENO_DIR": str(home / "deno-cache"),
        "DENO_NO_PROMPT": "1",
        "DENO_NO_UPDATE_CHECK": "1",
        "FORCE_COLOR": "false",
    })
    return env


def run_deno_stage(stage: str, deno: Path, home: Path,
                   timeout: float = PROBE_DEADLINE) -> StageResult:
    """Measure a bare JS runtime or local BgUtils import graph, no network I/O.

    Raw Deno output is captured in process memory and immediately discarded;
    only an exact success marker and exit code determine a fixed result.
    """
    if stage not in ("runtime", "imports"):
        raise ValueError("unexpected Deno probe stage")
    if stage == "runtime":
        command = [str(deno), "eval", f'console.log("{_MARKER_RUNTIME}")']
        stdin = None
        marker = _MARKER_RUNTIME
    else:
        command = [
            str(deno), "run", "--cached-only", "--allow-env", "--allow-net",
            "--allow-ffi=.", "--allow-read=.", "-",
        ]
        stdin = _module_stdin(home)
        marker = _MARKER_IMPORTS
    start = perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=str(home / "server" / "node_modules"),
            env=_deno_env(home),
            input=stdin, stdin=subprocess.DEVNULL if stdin is None else None,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        # Some upstream modules may output informational messages; do not
        # leak them. Only the marker and exit code matter.
        ok = completed.returncode == 0 and marker in completed.stdout.splitlines()
        result = f"{stage}-ready" if ok else f"{stage}-failed"
    except subprocess.TimeoutExpired:
        result = f"{stage}-timeout"
    except (OSError, ValueError):
        result = f"{stage}-launch-error"
    return StageResult(stage, result, max(0, round((perf_counter() - start) * 1000)))


def run_server_stage(service, home: Path, deno: Path,
                     stage: str, deadline: float = PROBE_DEADLINE) -> StageResult:
    """Reuse the actual RR-V launcher, not a hand-written approximation."""
    if stage not in ("server", "server-repeat"):
        raise ValueError("unexpected server stage")
    observed = TRACE.run_once(service, home, deno, attempt=1 if stage == "server" else 2,
                              deadline=deadline)
    return StageResult(stage, observed.result, observed.startup_ms,
                       observed.first_output_ms, observed.announced_ms,
                       observed.tcp_ms, observed.ping_ms)


def report(row: StageResult, first: str, log) -> None:
    print(f"{row.stage}: {row.result} | elapsed={row.elapsed_ms} ms", end="")
    if row.stage.startswith("server"):
        print(f" | first-output={row.first_output_ms} ms | "
              f"server-announced={row.announced_ms} ms | "
              f"TCP={row.tcp_ms} ms | valid-ping={row.ping_ms} ms")
    else:
        print()
    log(
        "bgutil.boot-sequence", pid=os.getpid(), order=f"{first}-first",
        phase=row.stage, result=row.result, startup_ms=row.elapsed_ms,
        first_output_ms=row.first_output_ms, announced_ms=row.announced_ms,
        tcp_ms=row.tcp_ms, ping_ms=row.ping_ms,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", choices=tuple(ORDERS), required=True,
                        help="which component runs first after a fresh Windows boot")
    args = parser.parse_args(argv)

    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from app.paths import find_executable
    from services import bgutil_http_service as service

    raw_home = os.environ.get(service.ENV_HOME, "").strip()
    if not raw_home:
        print("BOOT SEQUENCE: NOT RUN (Stage03 development mode disabled)")
        return 2
    home = Path(raw_home).expanduser()
    deno = find_executable("deno.exe")
    if deno is None:
        print("BOOT SEQUENCE: NOT RUN (Deno executable missing)")
        return 2
    try:
        if not service._validate_external_home(home):
            print("BOOT SEQUENCE: NOT RUN (external installation invalid)")
            return 2
    except (OSError, ValueError):
        print("BOOT SEQUENCE: NOT RUN (external validation failed)")
        return 2

    print(f"Boot order experiment: {args.first} first")
    print("No YouTube, WPC, Chrome or downloads. Output is sanitized.")
    print("Max wait is diagnostic-only; RR-V's normal 12s + 6s limit is unchanged.")
    print("Use different first modes on different Windows boots for comparison.")
    results = []
    for i, stage in enumerate(stage_sequence(args.first), 1):
        print(f"Running stage {i}/4 ({stage})...", flush=True)
        if stage.startswith("server"):
            try:
                row = run_server_stage(service, home, deno, stage)
            except Exception:
                row = StageResult(stage, "probe-exception", 0)
        else:
            try:
                row = run_deno_stage(stage, deno, home)
            except Exception:
                row = StageResult(stage, "probe-exception", 0)
        results.append(row)
        report(row, args.first, record_bgutil_diagnostic)

    if any(r.result not in ("runtime-ready", "imports-ready", "ready", "late-ready")
           for r in results):
        print("BOOT SEQUENCE: NEEDS REVIEW (some diagnostic stages failed)")
        return 1
    if any(r.result == "late-ready" for r in results):
        print("BOOT SEQUENCE: LATE-READY (diagnostic succeeded; production would time out)")
        return 0
    print("BOOT SEQUENCE: COMPLETE (cold-start root cause not yet proven)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
