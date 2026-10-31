"""Compare order effects with one fresh Python process for each provider trial.

Four independent workers run BgUtils -> WPC, then WPC -> BgUtils. Each worker
uses the existing production-style comparison builder, catches yt-dlp output
in memory, and cleans up its own Deno server before exiting. Only fixed-status
structured results are sent to the parent; never print raw worker output.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import importlib.util
import json
import os
import re
import secrets
from pathlib import Path
import signal
import statistics
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = Path(__file__).with_name("bgutil_ab_compare.py")
_SPEC = importlib.util.spec_from_file_location("rrv_bgutil_ab_base", BASE)
assert _SPEC is not None and _SPEC.loader is not None
BASE_BENCH = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = BASE_BENCH
_SPEC.loader.exec_module(BASE_BENCH)

_MAGIC = "RRV_AB_ISOLATED_V1:"
_HELLO = "RRV_AB_WORKER_HELLO_V1:"
_RUN_ID_ENV = "RRV_BGUTIL_AB_RUN_ID"
_PARENT_TIMEOUT_SECONDS = 180
_STATUSES = frozenset({
    "ok", "setup-error", "provider-setup-mismatch", "bgutil-startup-timeout",
    "unexpected-cookies", "timeout", "launch-error", "plugin-error",
    "registration-mismatch", "extract-failed", "worker-exception",
    "ytdlp-executable-missing",
})
_TOKEN_SOURCES = frozenset({"none", "bgutil", "wpc", "both"})


@dataclass(frozen=True)
class IsolatedResult:
    order: str
    scenario: str
    trial: int
    worker_pid: int
    status: str
    setup_ms: int
    extract_ms: int
    total_ms: int
    wall_ms: int
    token_source: str
    chrome_signal: bool
    bgutil_registered: bool
    wpc_registered: bool
    launcher_pid: int = 0


def plan(trials: int = 2) -> list[tuple[str, str, int]]:
    """Default: A=[BgUtils,WPC], B=[WPC,BgUtils], four new processes."""
    if trials not in (2, 4):
        raise ValueError("trials must be 2 or 4 to cover both orders")
    counts = {"bgutil": 0, "wpc": 0}
    result = []
    for round_index in range(trials):
        order = "bgutil-first" if round_index % 2 == 0 else "wpc-first"
        for scenario in (("bgutil", "wpc") if round_index % 2 == 0 else ("wpc", "bgutil")):
            counts[scenario] += 1
            result.append((order, scenario, counts[scenario]))
    return result


def _empty_result(order: str, scenario: str, trial: int, status: str,
                  *, worker_pid: int = 0, launcher_pid: int = 0,
                  wall_ms: int = 0) -> IsolatedResult:
    return IsolatedResult(
        order, scenario, trial, worker_pid, status, 0, 0, 0, wall_ms,
        "none", False, False, False, launcher_pid,
    )


def _decode_output(output: str | bytes | None) -> str:
    if isinstance(output, bytes):
        return output.decode("utf-8", errors="replace")
    return output if isinstance(output, str) else ""


def _protocol_payload(output: str | bytes | None, marker: str) -> dict | None:
    """Never show untrusted child output; select exactly one marked JSON line."""
    matches = [line[len(marker):] for line in _decode_output(output).splitlines()
               if line.startswith(marker)]
    if len(matches) != 1:
        return None
    try:
        payload = json.loads(matches[0])
    except (ValueError, TypeError):
        return None
    return payload if type(payload) is dict else None


def parse_worker_hello(output: str | bytes | None, expected_run_id: str) -> int:
    """A correlated child PID is useful for Windows venv launchers and cleanup."""
    payload = _protocol_payload(output, _HELLO)
    if payload is None or set(payload) != {"protocol", "run_id", "worker_pid"}:
        return 0
    if type(payload["protocol"]) is not int or payload["protocol"] != 1:
        return 0
    if payload["run_id"] != expected_run_id:
        return 0
    pid = payload["worker_pid"]
    return pid if type(pid) is int and 0 < pid <= 2147483647 else 0


def parse_worker_report(output: str | bytes | None, expected_scenario: str,
                        expected_trial: int, expected_run_id: str) -> dict | None:
    """Validate correlation and fixed fields, not launcher PID equality.

    On Windows the virtualenv python.exe may be a redirector whose process
    identifier differs from the actual interpreter that runs the worker.
    """
    pid = parse_worker_hello(output, expected_run_id)
    if not pid:
        return None
    payload = _protocol_payload(output, _MAGIC)
    if payload is None:
        return None
    required = {"protocol", "run_id", "worker_pid", *BASE_BENCH.Trial.__dataclass_fields__}
    if set(payload) != required or type(payload["protocol"]) is not int or payload["protocol"] != 1:
        return None
    if payload["run_id"] != expected_run_id or type(payload["worker_pid"]) is not int:
        return None
    if payload["worker_pid"] != pid:
        return None
    if payload["scenario"] != expected_scenario or payload["scenario"] not in ("wpc", "bgutil"):
        return None
    if type(payload["trial"]) is not int or payload["trial"] != expected_trial:
        return None
    if type(payload["status"]) is not str or payload["status"] not in _STATUSES:
        return None
    if type(payload["token_source"]) is not str or payload["token_source"] not in _TOKEN_SOURCES:
        return None
    if any(type(payload[name]) is not bool for name in
           ("chrome_signal", "bgutil_registered", "wpc_registered")):
        return None
    if any(type(payload[name]) is not int or not 0 <= payload[name] <= 600000
           for name in ("setup_ms", "extract_ms", "total_ms")):
        return None
    if payload["total_ms"] != payload["setup_ms"] + payload["extract_ms"]:
        return None
    return payload

def _kill_worker_tree(process: subprocess.Popen, worker_pid: int = 0) -> None:
    """On timeout, terminate the real worker even if the venv shim exited."""
    if os.name == "nt":
        targets = []
        if worker_pid > 0:
            targets.append(worker_pid)
        if process.poll() is None and process.pid not in targets:
            targets.append(process.pid)
        for pid in targets:
            try:
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL, capture_output=True, timeout=8,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.TimeoutExpired):
                pass
    elif process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    elif worker_pid > 0 and worker_pid != process.pid:
        try:
            os.kill(worker_pid, signal.SIGKILL)
        except (OSError, ProcessLookupError):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.communicate(timeout=3)
    except (OSError, subprocess.TimeoutExpired):
        pass

def run_isolated(order: str, scenario: str, trial: int, video: str,
                 timeout: int = _PARENT_TIMEOUT_SECONDS) -> IsolatedResult:
    """A fresh interpreter for each run; only correlated fixed fields escape."""
    run_id = secrets.token_hex(16)  # Ephemeral correlation ID, not a PO Token.
    cmd = [
        sys.executable, str(Path(__file__).resolve()), "--_worker",
        "--_scenario", scenario, "--_trial", str(trial), "--video", video,
    ]
    environment = os.environ.copy()
    environment[_RUN_ID_ENV] = run_id
    started = perf_counter()
    try:
        process = subprocess.Popen(
            cmd, cwd=str(ROOT), env=environment, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **({"start_new_session": True} if os.name != "nt" else {}),
        )
    except OSError:
        return _empty_result(order, scenario, trial, "worker-launch-error")
    try:
        output, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired as error:
        # TimeoutExpired.output can be bytes even when text=True. The first
        # worker line was flushed before any yt-dlp or Deno operation.
        actual_pid = parse_worker_hello(error.output, run_id)
        _kill_worker_tree(process, actual_pid)
        elapsed = max(0, round((perf_counter() - started) * 1000))
        return _empty_result(order, scenario, trial, "worker-timeout",
                             worker_pid=actual_pid, launcher_pid=process.pid,
                             wall_ms=elapsed)
    except OSError:
        _kill_worker_tree(process)
        elapsed = max(0, round((perf_counter() - started) * 1000))
        return _empty_result(order, scenario, trial, "worker-protocol-error",
                             launcher_pid=process.pid, wall_ms=elapsed)

    elapsed = max(0, round((perf_counter() - started) * 1000))
    parsed = parse_worker_report(output, scenario, trial, run_id)
    if parsed is None:
        return _empty_result(order, scenario, trial, "worker-protocol-error",
                             launcher_pid=process.pid, wall_ms=elapsed)
    # The Windows virtualenv launcher may exit with 0 regardless of the real
    # worker's status. Never turn a negative worker result into success.
    if parsed["status"] == "ok" and process.returncode != 0:
        return _empty_result(order, scenario, trial, "worker-exit-mismatch",
                             worker_pid=parsed["worker_pid"],
                             launcher_pid=process.pid, wall_ms=elapsed)
    return IsolatedResult(
        order=order, scenario=scenario, trial=trial,
        worker_pid=parsed["worker_pid"], launcher_pid=process.pid,
        status=parsed["status"], setup_ms=parsed["setup_ms"],
        extract_ms=parsed["extract_ms"], total_ms=parsed["total_ms"],
        wall_ms=elapsed, token_source=parsed["token_source"],
        chrome_signal=parsed["chrome_signal"],
        bgutil_registered=parsed["bgutil_registered"],
        wpc_registered=parsed["wpc_registered"],
    )

def _worker_main(scenario: str, trial: int, video: str) -> int:
    """Child reports its actual PID before startup, then one final result."""
    run_id = os.environ.get(_RUN_ID_ENV, "")
    if re.fullmatch(r"[0-9a-f]{32}", run_id) is None:
        return 2
    actual_pid = os.getpid()
    hello = {"protocol": 1, "run_id": run_id, "worker_pid": actual_pid}
    print(_HELLO + json.dumps(hello, separators=(",", ":")), flush=True)

    try:
        from app.paths import find_executable
        executable = find_executable("yt-dlp.exe")
        if executable is None:
            result = BASE_BENCH.Trial(scenario, trial, "ytdlp-executable-missing",
                                     0, 0, 0, "none", False, False, False)
        else:
            result = BASE_BENCH.run_trial(
                executable, video, scenario, trial,
                os.environ.get("RRV_BGUTIL_STAGE03_HOME", ""),
            )
    except Exception:
        # Python tracebacks and exception messages might contain private paths.
        result = BASE_BENCH.Trial(scenario, trial, "worker-exception", 0, 0, 0,
                                  "none", False, False, False)
    finally:
        try:
            from services.bgutil_http_service import shutdown_bgutil_http
            shutdown_bgutil_http()
        except Exception:
            pass

    report = {"protocol": 1, "run_id": run_id,
              "worker_pid": actual_pid, **asdict(result)}
    print(_MAGIC + json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if result.status == "ok" else 1

def print_summary(results: list[IsolatedResult]) -> None:
    print("\nIndependent-process order comparison (one new Python process per row)")
    print("Order         Provider  Trial  Worker  Launcher  Status                    Setup  Extract  Total  Wall    Token   Chrome")
    for r in results:
        print(f"{r.order:<13} {r.scenario:<9} {r.trial:>2}  {r.worker_pid:>6}  {r.launcher_pid:>8}  "
              f"{r.status:<25} {r.setup_ms:>6}  {r.extract_ms:>7}  "
              f"{r.total_ms:>5}  {r.wall_ms:>6}  {r.token_source:<6}  "
              f"{'yes' if r.chrome_signal else 'no'}")
    for scenario in ("wpc", "bgutil"):
        successes = [r for r in results if r.scenario == scenario and r.status == "ok"]
        if successes:
            print(f"{scenario}: {len(successes)} successful; "
                  f"median elapsed incl. Python startup: "
                  f"{round(statistics.median(r.wall_ms for r in successes))} ms")
    print("Token=none means no token response was observed, not provider failure.")
    print("All source logs, tokens, video URLs and private paths remain unprinted.")
    print("Results are diagnostic, not a statistically rigorous benchmark.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default=BASE_BENCH.DEFAULT_VIDEO,
                        help="Public YouTube video URL for identical trials")
    parser.add_argument("--trials", type=int, choices=(2, 4), default=2,
                        help="complete two order groups by default (4 worker processes)")
    parser.add_argument("--_worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--_scenario", choices=("wpc", "bgutil"), help=argparse.SUPPRESS)
    parser.add_argument("--_trial", type=int, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args._worker:
        if args._scenario is None or args._trial is None or args._trial < 1:
            return 2
        return _worker_main(args._scenario, args._trial, args.video)

    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from app.paths import find_executable, wpc_provider_runtime_ready
    from services.bgutil_http_service import ENV_HOME, _validate_external_home
    from services.ytdlp_service import YtDlpService

    if not YtDlpService.is_youtube_url(args.video):
        print("Cannot compare: public YouTube video URL required")
        return 2
    home = os.environ.get(ENV_HOME, "").strip()
    if not home or not _validate_external_home(Path(home).expanduser()):
        print("Cannot compare: BgUtils external provider is not enabled/prepared")
        return 2
    if (find_executable("yt-dlp.exe") is None or find_executable("deno.exe") is None
            or not wpc_provider_runtime_ready()):
        print("Cannot compare: yt-dlp, Deno or WPC not ready")
        return 2

    print(f"{2 * args.trials} isolated trials, opposite orders, same video/yt-dlp settings.")
    print("WPC can open Chrome when a token is actually required.")
    print("No video download; child stdout/stderr never shown or saved.")
    results = []
    for order, scenario, trial in plan(args.trials):
        print(f"Running {order}: {scenario} {trial}...", flush=True)
        result = run_isolated(order, scenario, trial, args.video)
        results.append(result)
        record_bgutil_diagnostic(
            "compare.isolated", pid=result.worker_pid, launcher_pid=result.launcher_pid,
            parent_pid=os.getpid(),
            order=result.order, scenario=result.scenario, trial=result.trial,
            status=result.status, setup_ms=result.setup_ms,
            extract_ms=result.extract_ms, total_ms=result.total_ms,
            wall_ms=result.wall_ms, token_source=result.token_source,
            chrome_signal=result.chrome_signal,
        )
    print_summary(results)
    if any(r.status != "ok" for r in results):
        print("ISOLATED COMPARISON: NEEDS REVIEW")
        return 1
    print("ISOLATED COMPARISON: COMPLETE (cause still requires interpretation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
