"""Compare production-style WPC-only and BgUtils-preferred YouTube extraction.

This does NOT download files, change persistent RR-V configuration, or print
raw yt-dlp logs. PO Token tracing can expose credentials and token values.
All raw child-process output is held only in memory and is never written.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import statistics
import subprocess
import sys
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"
_ENV_HOME = "RRV_BGUTIL_STAGE03_HOME"


@dataclass(frozen=True)
class Trial:
    scenario: str
    trial: int
    status: str
    setup_ms: int
    extract_ms: int
    total_ms: int
    token_source: str
    chrome_signal: bool
    bgutil_registered: bool
    wpc_registered: bool


def read_signals(output: str) -> tuple[bool, bool, str, bool, bool]:
    """Discard all source text; only return fixed enums and booleans."""
    registration = next(
        (line for line in output.splitlines() if "PO Token Providers:" in line),
        "",
    )
    bgutil_registered = "bgutil:http-2.0.2" in registration
    wpc_registered = "wpc-1.1.2" in registration
    bgutil_response = 'PO Token response from "bgutil:http" provider: PoTokenResponse(' in output
    wpc_response = 'PO Token response from "wpc" provider: PoTokenResponse(' in output
    if bgutil_response and wpc_response:
        token_source = "both"
    elif bgutil_response:
        token_source = "bgutil"
    elif wpc_response:
        token_source = "wpc"
    else:
        token_source = "none"
    chrome_signal = "Launching youtube.com in browser to retrieve PO Token(s)" in output
    plugin_error = "Error while importing module" in output
    return bgutil_registered, wpc_registered, token_source, chrome_signal, plugin_error


def sequence(trials: int) -> list[tuple[str, int]]:
    """Run A B B A for two repetitions; alternate to limit order bias."""
    output = []
    counts = {"wpc": 0, "bgutil": 0}
    for index in range(trials):
        order = ("wpc", "bgutil") if index % 2 == 0 else ("bgutil", "wpc")
        for scenario in order:
            counts[scenario] += 1
            output.append((scenario, counts[scenario]))
    return output


def _command(executable: Path, video: str, scenario: str, external_home: str) -> list[str]:
    """Use RR-V's actual runtime/provider builder, not a second approximation."""
    from services import ytdlp_service

    command = [
        str(executable), "--ignore-config", "--no-cache-dir", "--verbose",
        "--simulate", "--no-playlist", "--no-color", "--socket-timeout", "20",
        "--retries", "0", "--extractor-retries", "0",
        "--extractor-args", "youtube:pot_trace=true",
    ]
    # The ordinary RR-V login file and optional manually supplied cookies are
    # both excluded. Both cases are thus strictly anonymous and comparable.
    with (
        patch.dict(os.environ, {_ENV_HOME: external_home if scenario == "bgutil" else ""}),
        patch.object(
            ytdlp_service, "RRV_YOUTUBE_AUTH_COOKIE_PATH",
            ROOT / "__rrv_ab_compare_no_saved_youtube_cookies__",
        ),
        patch.object(ytdlp_service.YtDlpService, "_find_cookie_file", return_value=None),
    ):
        ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(command, video)
    command.append(video)
    return command


def run_trial(executable: Path, video: str, scenario: str, trial: int,
              external_home: str, timeout: int = 120) -> Trial:
    started = perf_counter()
    try:
        command = _command(executable, video, scenario, external_home)
    except Exception:
        # Never print exception messages: they can contain filesystem paths.
        elapsed = round((perf_counter() - started) * 1000)
        return Trial(scenario, trial, "setup-error", elapsed, 0, elapsed,
                     "none", False, False, False)

    setup_ms = round((perf_counter() - started) * 1000)
    plugin_dirs = [
        command[i + 1] for i, arg in enumerate(command[:-1])
        if arg == "--plugin-dirs"
    ]
    has_bgutil = any("youtubepot-bgutilhttp:base_url=" in part for part in command)
    expected_dir_count = 2 if scenario == "bgutil" else 1
    if len(plugin_dirs) != expected_dir_count or has_bgutil != (scenario == "bgutil"):
        status = "provider-setup-mismatch"
        if scenario == "bgutil" and not has_bgutil:
            # Distinguish the observed Deno timeout from an unrelated plugin
            # argument error without ever exposing process output or paths.
            try:
                from services.bgutil_http_service import bgutil_http_status
                if bgutil_http_status() == "server-ping-timeout":
                    status = "bgutil-startup-timeout"
            except (ImportError, OSError):
                pass
        return Trial(scenario, trial, status, setup_ms, 0, setup_ms,
                     "none", False, False, False)
    if any(item == "--cookies" for item in command):
        return Trial(scenario, trial, "unexpected-cookies", setup_ms, 0, setup_ms,
                     "none", False, False, False)

    run_started = perf_counter()
    try:
        completed = subprocess.run(
            command, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        elapsed = round((perf_counter() - run_started) * 1000)
        return Trial(scenario, trial, "timeout", setup_ms, elapsed,
                     setup_ms + elapsed, "none", False, False, False)
    except OSError:
        elapsed = round((perf_counter() - run_started) * 1000)
        return Trial(scenario, trial, "launch-error", setup_ms, elapsed,
                     setup_ms + elapsed, "none", False, False, False)

    extract_ms = round((perf_counter() - run_started) * 1000)
    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    bg_registered, wpc_registered, token_source, chrome_signal, plugin_error = read_signals(output)
    if plugin_error:
        status = "plugin-error"
    elif not wpc_registered or (scenario == "bgutil") != bg_registered:
        status = "registration-mismatch"
    elif completed.returncode:
        status = "extract-failed"
    else:
        status = "ok"
    return Trial(scenario, trial, status, setup_ms, extract_ms,
                 setup_ms + extract_ms, token_source, chrome_signal,
                 bg_registered, wpc_registered)


def print_summary(results: list[Trial]) -> None:
    print("\nFair comparison: anonymous video simulation, same yt-dlp executable")
    print("No forced player-client; no disk token cache; no video files downloaded")
    print("Scenario     Trial  Status                   Setup(ms)  Extract(ms)  Total(ms)  Token  WPC browser request")
    for item in results:
        print(
            f"{item.scenario:<12} {item.trial:>2}     {item.status:<24} "
            f"{item.setup_ms:>7}  {item.extract_ms:>11}  "
            f"{item.total_ms:>9}  {item.token_source:<6} "
            f"{'yes' if item.chrome_signal else 'no'}"
        )
    for scenario in ("wpc", "bgutil"):
        completed = [row for row in results if row.scenario == scenario and row.status == "ok"]
        if completed:
            median_ms = round(statistics.median(row.total_ms for row in completed))
            print(f"{scenario} successful trials: {len(completed)}; median total: {median_ms} ms")
    print("Token=none means no token response was observed, NOT a provider failure.")
    print("Raw traces, PO Tokens, video URLs and cookie contents were not saved.")
    print("Observed times are diagnostic, not statistically reliable speed rankings.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", default=DEFAULT_VIDEO,
                        help="URL of a public YouTube video, no login required")
    parser.add_argument("--trials", type=int, default=2,
                        help="runs per scenario, default 2 (4 total)")
    args = parser.parse_args(argv)
    if not 1 <= args.trials <= 3:
        parser.error("trials must be between 1 and 3")

    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from app.paths import find_executable, wpc_provider_runtime_ready
    from services.bgutil_http_service import ENV_HOME, _validate_external_home, shutdown_bgutil_http
    from services.ytdlp_service import YtDlpService

    if not YtDlpService.is_youtube_url(args.video):
        print("Cannot compare: a public YouTube video URL is required.")
        return 2
    external_home = os.environ.get(ENV_HOME, "").strip()
    if not external_home or not _validate_external_home(Path(external_home).expanduser()):
        print("Cannot compare: Stage03 external provider was not enabled/prepared.")
        return 2
    executable = find_executable("yt-dlp.exe")
    if executable is None or find_executable("deno.exe") is None or not wpc_provider_runtime_ready():
        print("Cannot compare: yt-dlp, Deno or WPC runtime is not ready.")
        return 2

    print("WPC-only vs BgUtils-preferred, same yt-dlp and YouTube video.")
    print("Chrome MAY open if WPC is actually asked for a PO Token.")
    print("All yt-dlp verbose/PO Token trace output stays in memory.")
    results = []
    try:
        for scenario, trial_index in sequence(args.trials):
            print(f"Running {scenario} trial {trial_index} of {args.trials}...", flush=True)
            result = run_trial(executable, args.video, scenario, trial_index, external_home)
            results.append(result)
            record_bgutil_diagnostic(
                "compare.run", pid=os.getpid(), scenario=result.scenario,
                trial=result.trial, status=result.status,
                setup_ms=result.setup_ms, extract_ms=result.extract_ms,
                total_ms=result.total_ms, token_source=result.token_source,
                chrome_signal=result.chrome_signal,
            )
            if result.status != "ok":
                print("One run needs review; remaining comparisons are skipped.")
                break
    finally:
        shutdown_bgutil_http()
    print_summary(results)
    if len(results) != 2 * args.trials or any(row.status != "ok" for row in results):
        print("COMPARISON: NEEDS REVIEW")
        return 1
    print("COMPARISON: COMPLETE (performance decision requires interpretation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
