"""Developer-only Deno cold/warm startup probe for RR-V Stage03.

This uses the actual RR-V BgUtils server launcher, but extends its deadline
only inside this diagnostic process. No YouTube, WPC, tokens, cookies, or
video downloads are used. Never print/store raw subprocess output or paths.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
from time import perf_counter
from unittest.mock import patch
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DIAGNOSTIC_DEADLINE = 35.0
NORMAL_BUDGET = 18.0


@dataclass(frozen=True)
class TraceResult:
    attempt: int
    result: str
    status: str
    startup_ms: int
    first_output_ms: int
    announced_ms: int
    tcp_ms: int
    ping_ms: int
    ping_attempts: int
    tcp_checks: int
    worst_ping_ms: int
    output_kind: str


class StartupTimeline:
    """Retain numbers and fixed status categories, never Deno output bytes."""

    def __init__(self, clock=perf_counter):
        self._clock = clock
        self._start = clock()
        self._lock = threading.Lock()
        self.first_output_ms = 0
        self.announced_ms = 0
        self.tcp_ms = 0
        self.ping_ms = 0
        self.ping_attempts = 0
        self.tcp_checks = 0
        self.worst_ping_ms = 0
        self.output_kind = "no-output"

    def elapsed_ms(self) -> int:
        return max(0, round((self._clock() - self._start) * 1000))

    def observe_output(self, original_feed, collector, chunk: bytes) -> None:
        # The underlying service handles the raw bytes in bounded memory.
        original_feed(collector, chunk)
        if not chunk:
            return
        kind, _ = collector.snapshot()
        now = self.elapsed_ms()
        with self._lock:
            if not self.first_output_ms:
                self.first_output_ms = now
            if kind == "server-announced" and not self.announced_ms:
                self.announced_ms = now
            self.output_kind = kind

    def observe_ping(self, original_ping, url: str) -> bool:
        with self._lock:
            self.ping_attempts += 1
        started = self._clock()
        valid = original_ping(url)
        with self._lock:
            self.worst_ping_ms = max(
                self.worst_ping_ms, max(0, round((self._clock() - started) * 1000))
            )
        if valid:
            now = self.elapsed_ms()
            with self._lock:
                if not self.tcp_ms:
                    self.tcp_ms = now
                if not self.ping_ms:
                    self.ping_ms = now
            return True

        # Only when the actual /ping failed, check if localhost accepts TCP.
        # This extra probe is diagnostic-only and never contacts public hosts.
        parsed = urlsplit(url)
        if parsed.hostname != "127.0.0.1" or parsed.port is None:
            return False
        with self._lock:
            self.tcp_checks += 1
        try:
            with socket.create_connection(("127.0.0.1", parsed.port), timeout=0.15):
                now = self.elapsed_ms()
                with self._lock:
                    if not self.tcp_ms:
                        self.tcp_ms = now
        except OSError:
            pass
        return False

    def finish(self, attempt: int, status: str, connected: bool) -> TraceResult:
        total = self.elapsed_ms()
        if connected:
            outcome = "late-ready" if total > NORMAL_BUDGET * 1000 else "ready"
        elif status == "server-ping-timeout":
            outcome = "timeout"
        elif status.startswith("deno-exited-before-ready:"):
            outcome = "early-exit"
        else:
            outcome = "start-failed"
        with self._lock:
            return TraceResult(
                attempt, outcome, status, total, self.first_output_ms,
                self.announced_ms, self.tcp_ms, self.ping_ms,
                self.ping_attempts, self.tcp_checks, self.worst_ping_ms,
                self.output_kind,
            )


def run_once(service, home: Path, deno: Path, attempt: int,
             deadline: float = DIAGNOSTIC_DEADLINE,
             clock=perf_counter) -> TraceResult:
    """Use the real launch configuration, without altering production defaults."""
    timeline = StartupTimeline(clock=clock)
    server = service._BgUtilServer()
    original_ping = service._ping_local_provider
    original_feed = service._SafeDenoOutput.feed

    def observed_ping(url: str) -> bool:
        return timeline.observe_ping(original_ping, url)

    def observed_feed(collector, chunk: bytes) -> None:
        timeline.observe_output(original_feed, collector, chunk)

    status = "probe-exception"
    connected = False
    try:
        with (
            patch.object(service, "_START_TIMEOUT", deadline),
            patch.object(service, "_COLD_START_GRACE", 0.0),
            patch.object(service, "_ping_local_provider", observed_ping),
            patch.object(service._SafeDenoOutput, "feed", observed_feed),
        ):
            connection = server.ensure(home, deno)
            connected = connection is not None
            status = server.status()
    except Exception:
        # Never include exception messages, command lines, private paths, etc.
        status = "probe-exception"
    finally:
        try:
            server.close()
        except Exception:
            # Neither cleanup errors nor private paths may escape as tracebacks.
            status = "cleanup-error"
            connected = False
    return timeline.finish(attempt, status, connected)


def report(result: TraceResult, log) -> None:
    print(
        f"Attempt {result.attempt}: {result.result} | "
        f"elapsed={result.startup_ms} ms | first-output={result.first_output_ms} ms | "
        f"server-announced={result.announced_ms} ms | "
        f"TCP={result.tcp_ms} ms | valid-ping={result.ping_ms} ms | "
        f"ping-attempts={result.ping_attempts} | "
        f"output={result.output_kind}"
    )
    log(
        "bgutil.startup-probe", pid=os.getpid(), attempt=result.attempt,
        result=result.result, status=result.status,
        startup_ms=result.startup_ms, first_output_ms=result.first_output_ms,
        announced_ms=result.announced_ms, tcp_ms=result.tcp_ms,
        ping_ms=result.ping_ms, ping_attempts=result.ping_attempts,
        tcp_checks=result.tcp_checks, worst_ping_ms=result.worst_ping_ms,
        output_kind=result.output_kind,
    )


def run_deno_baseline(deno: Path, home: Path, timeout: int = 10) -> tuple[str, int]:
    """Measure basic Deno JavaScript startup AFTER the real server attempts.

    Baseline is intentionally last: launching Deno first might warm caches
    and spoil the cold-start measurement. Ignore all raw process output.
    """
    started = perf_counter()
    environment = os.environ.copy()
    environment.update({
        "DENO_DIR": str(home / "deno-cache"),
        "DENO_NO_PROMPT": "1",
        "DENO_NO_UPDATE_CHECK": "1",
        "FORCE_COLOR": "false",
    })
    try:
        completed = subprocess.run(
            [str(deno), "eval", "console.log('RRV_DENO_BASELINE_OK')"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
            env=environment,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        result = (
            "baseline-ready"
            if completed.returncode == 0 and completed.stdout.strip() == "RRV_DENO_BASELINE_OK"
            else "baseline-failed"
        )
    except subprocess.TimeoutExpired:
        result = "baseline-timeout"
    except OSError:
        result = "baseline-launch-error"
    return result, max(0, round((perf_counter() - started) * 1000))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, choices=(1, 2), default=2,
                        help="one cold attempt or cold + subsequent attempt")
    args = parser.parse_args(argv)

    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from app.paths import find_executable
    from services import bgutil_http_service as service

    raw_home = os.environ.get(service.ENV_HOME, "").strip()
    if not raw_home:
        print("STARTUP TRACE: NOT RUN (BgUtils development mode disabled)")
        return 2
    home = Path(raw_home).expanduser()
    deno = find_executable("deno.exe")
    if deno is None:
        print("STARTUP TRACE: NOT RUN (Deno missing)")
        return 2
    start_preflight = perf_counter()
    is_valid = service._validate_external_home(home)
    preflight_ms = max(0, round((perf_counter() - start_preflight) * 1000))
    if not is_valid:
        print("STARTUP TRACE: NOT RUN (external installation invalid)")
        return 2
    print(f"External installation verified in {preflight_ms} ms.")
    print("Using the actual RR-V Deno launcher with a diagnostic-only 35-second deadline.")
    print("TCP and /ping checked on localhost only. No YouTube, WPC, Chrome or downloads.")
    print("A zero time means that milestone was not observed.")
    results = []
    for index in range(1, args.attempts + 1):
        print(f"Checking Deno server startup {index}/{args.attempts}...", flush=True)
        result = run_once(service, home, deno, index)
        results.append(result)
        report(result, record_bgutil_diagnostic)

    # This deliberately runs after the cold/warm server attempts and therefore
    # cannot contaminate the first Deno process's startup environment.
    baseline_status, baseline_ms = run_deno_baseline(deno, home)
    print(f"Deno basic JS startup (run last): {baseline_status} in {baseline_ms} ms")
    record_bgutil_diagnostic(
        "bgutil.baseline", pid=os.getpid(), status=baseline_status,
        startup_ms=baseline_ms,
    )
    if any(r.result not in ("ready", "late-ready") for r in results):
        print("STARTUP TRACE: NEEDS REVIEW (see milestone times and diagnostic log)")
        return 1
    print("STARTUP TRACE: COMPLETE (this does not clear the production startup issue)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
