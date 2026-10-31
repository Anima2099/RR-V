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
                  *, worker_pid: int = 0, wall_ms: int = 0) -> IsolatedResult:
    return IsolatedResult(
        order, scenario, trial, worker_pid, status, 0, 0, 0, wall_ms,
        "none", False, False, False,
    )


def parse_worker_report(output: str, expected_scenario: str,
                        expected_trial: int, expected_pid: int) -> dict | None:
    """Fail closed: accept exactly one allowlisted JSON result, no extra text."""
    if not isinstance(output, str) or not output.startswith(_MAGIC):
        return None
    if "\n" in output.rstrip("\r\n"):
        return None
    try:
        payload = json.loads(output[len(_MAGIC):])
    except (ValueError, TypeError):
        return None
    if type(payload) is not dict:
        return None
    required = {"protocol", "worker_pid", *BASE_BENCH.Trial.__dataclass_fields__}
    if set(payload) != required or type(payload["protocol"]) is not int or payload["protocol"] != 1:
        return None
    if type(payload["worker_pid"]) is not int or payload["worker_pid"] != expected_pid or expected_pid <= 0:
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


def _kill_worker_tree(process: subprocess.Popen) -> None:
    """On timeout, terminate our worker and any yt-dlp/Deno descendants."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, capture_output=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
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
    """Launch a new Python interpreter, then discard all unvalidated output."""
    cmd = [
        sys.executable, str(Path(__file__).resolve()), "--_worker",
        "--_scenario", scenario, "--_trial", str(trial), "--video", video,
    ]
    started = perf_counter()
    try:
        process = subprocess.Popen(
            cmd, cwd=str(ROOT), env=os.environ.copy(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **({"start_new_session": True} if os.name != "nt" else {}),
        )
    except OSError:
        return _empty_result(order, scenario, trial, "worker-launch-error")
    try:
        output, _stderr = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_worker_tree(process)
        elapsed = max(0, round((perf_counter() - started) * 1000))
        return _empty_result(order, scenario, trial, "worker-timeout",
                             worker_pid=process.pid, wall_ms=elapsed)
    except OSError:
        _kill_worker_tree(process)
        elapsed = max(0, round((perf_counter() - started) * 1000))
        return _empty_result(order, scenario, trial, "worker-protocol-error",
                             worker_pid=process.pid, wall_ms=elapsed)

    elapsed = max(0, round((perf_counter() - started) * 1000))
    parsed = parse_worker_report(output, scenario, trial, process.pid)
    if parsed is None:
        return _empty_result(order, scenario, trial, "worker-protocol-error",
                             worker_pid=process.pid, wall_ms=elapsed)
    if (process.returncode == 0) != (parsed["status"] == "ok"):
        return _empty_result(order, scenario, trial, "worker-exit-mismatch",
                             worker_pid=process.pid, wall_ms=elapsed)
    return IsolatedResult(
        order=order, scenario=scenario, trial=trial, worker_pid=process.pid,
        status=parsed["status"], setup_ms=parsed["setup_ms"],
        extract_ms=parsed["extract_ms"], total_ms=parsed["total_ms"],
        wall_ms=elapsed, token_source=parsed["token_source"],
        chrome_signal=parsed["chrome_signal"],
        bgutil_registered=parsed["bgutil_registered"],
        wpc_registered=parsed["wpc_registered"],
    )


def _worker_main(scenario: str, trial: int, video: str) -> int:
    """Runs only inside the fresh child; output is exactly one JSON line."""
    from app.paths import find_executable
    from services.bgutil_http_service import shutdown_bgutil_http

    try:
        executable = find_executable("yt-dlp.exe")
        if executable is None:
            result = BASE_BENCH.Trial(scenario, trial, "ytdlp-executable-missing",
                                     0, 0, 0, "none", False, False, False)
        else:
            result = BASE_BENCH.run_trial(
                executable, video, scenario, trial, os.environ.get("RRV_BGUTIL_STAGE03_HOME", ""),
            )
    except Exception:
        # Python tracebacks and exception messages might contain private paths.
        result = BASE_BENCH.Trial(scenario, trial, "worker-exception", 0, 0, 0,
                                  "none", False, False, False)
    finally:
        try:
            shutdown_bgutil_http()
        except Exception:
            pass
    report = {"protocol": 1, "worker_pid": os.getpid(), **asdict(result)}
    print(_MAGIC + json.dumps(report, separators=(",", ":")), flush=True)
    return 0 if result.status == "ok" else 1


def print_summary(results: list[IsolatedResult]) -> None:
    print("\nIndependent-process order comparison (one new Python process per row)")
    print("Order         Provider  Trial  PID     Status                    Setup  Extract  Total  Wall    Token   Chrome")
    for r in results:
        print(f"{r.order:<13} {r.scenario:<9} {r.trial:>2}  {r.worker_pid:>6}  "
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
            "compare.isolated", pid=result.worker_pid, parent_pid=os.getpid(),
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
