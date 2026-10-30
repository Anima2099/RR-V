"""Privacy-safe Stage03 PO Token issuance and explicit WPC fallback verification.

The --verbose / pot_trace output can contain live tokens. Capture it in memory,
never echo it, and write only allowlisted outcome codes to RR-V's diagnostic log.
The default test isolates BgUtils and cannot load Chrome-based WPC. Fallback
mode is separate and opt-in because it may intentionally open Chrome.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


@dataclass(frozen=True)
class TokenSignals:
    bgutil_registered: bool
    wpc_registered: bool
    bgutil_requested: bool
    wpc_requested: bool
    bgutil_response: bool
    wpc_response: bool
    import_error: bool
    invalid_response: bool
    exit_code: int


def inspect_trace(output: str, exit_code: int) -> TokenSignals:
    """Look for upstream provider success *markers* without returning tokens."""
    registration = next(
        (line for line in output.splitlines() if "PO Token Providers:" in line), ""
    )
    return TokenSignals(
        bgutil_registered="bgutil:http-2.0.2" in registration,
        wpc_registered="wpc-1.1.2" in registration,
        bgutil_requested=any(
            "[pot:bgutil:http]" in line
            and "Generating a " in line
            and " PO Token" in line
            for line in output.splitlines()
        ),
        wpc_requested="using WebPoClient in browser" in output,
        bgutil_response=('PO Token response from "bgutil:http" provider: PoTokenResponse(' in output),
        wpc_response=('PO Token response from "wpc" provider: PoTokenResponse(' in output),
        import_error="Error while importing module" in output,
        invalid_response="Invalid PO Token response received from" in output,
        exit_code=exit_code,
    )


def classify(mode: str, result: TokenSignals) -> str:
    """Never call a request attempt, registration, or cache hit token success."""
    if result.import_error:
        return "plugin-import-error"
    if result.invalid_response:
        return "invalid-provider-response"
    if not result.bgutil_registered:
        return "bgutil-not-registered"
    if mode == "bgutil":
        if result.wpc_registered:
            return "unexpected-wpc-registration"
        if not result.bgutil_response:
            return "token-request-without-response" if result.bgutil_requested else "no-token-request"
        if result.exit_code:
            return "token-response-but-video-failed"
        return "bgutil-token-confirmed"
    if mode == "fallback":
        if not result.wpc_registered:
            return "wpc-not-registered"
        if result.bgutil_response:
            return "unexpected-bgutil-response"
        if not result.wpc_response:
            return "wpc-request-without-response" if result.wpc_requested else "no-token-request"
        if result.exit_code:
            return "wpc-response-but-video-failed"
        return "wpc-token-confirmed"
    raise ValueError("unknown verification mode")


def _build_command(executable: Path, deno: Path | None, bgutil_home: Path,
                   base_url: str, include_wpc: bool, video: str,
                   wpc_dir: Path | None = None) -> list[str]:
    command = [
        str(executable), "--ignore-config", "--no-cache-dir", "--verbose", "--simulate",
        "--no-playlist", "--no-color", "--socket-timeout", "20", "--retries", "0",
        "--extractor-retries", "0", "--extractor-args",
        "youtube:player-client=mweb,tv,web_safari;pot_trace=true",
    ]
    if deno is not None:
        command.extend(("--js-runtimes", f"deno:{deno}"))
    command.extend(("--no-plugin-dirs", "--plugin-dirs", str(bgutil_home)))
    if include_wpc:
        assert wpc_dir is not None
        command.extend(("--plugin-dirs", str(wpc_dir)))
    command.extend((
        "--extractor-args", f"youtubepot-bgutilhttp:base_url={base_url}", video,
    ))
    return command


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("bgutil", "fallback"), default="bgutil")
    parser.add_argument("--video", default=DEFAULT_VIDEO,
                        help="URL of a public YouTube video accessible without login")
    args = parser.parse_args(argv)

    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from app.paths import RRV_WPC_PROVIDER_DIR, find_executable, wpc_provider_runtime_ready
    from services.bgutil_http_service import (
        ENV_HOME, _validate_external_home, connect_bgutil_http, shutdown_bgutil_http,
    )
    from services.ytdlp_service import YtDlpService

    def report(status: str, signals: TokenSignals | None = None) -> int:
        confirmed = status in ("bgutil-token-confirmed", "wpc-token-confirmed")
        record_bgutil_diagnostic(
            "pot.verification", pid=os.getpid(), stage=args.mode,
            result="confirmed" if confirmed else "needs-review", status=status,
            bgutil="registered" if signals and signals.bgutil_registered else "missing",
            wpc="registered" if signals and signals.wpc_registered else "missing",
        )
        print("Stage03 mode:", args.mode)
        print("Token issuance:", "CONFIRMED" if confirmed else "NOT CONFIRMED")
        print("Status:", status)
        if signals:
            print("BgUtils registered:", signals.bgutil_registered)
            print("WPC registered:", signals.wpc_registered)
            print("BgUtils request observed:", signals.bgutil_requested)
            print("BgUtils response observed:", signals.bgutil_response)
            print("WPC response observed:", signals.wpc_response)
            print("Video simulation exit code:", signals.exit_code)
        print("Raw trace and token values have NOT been printed or saved.")
        return 0 if confirmed else 1

    if not YtDlpService.is_youtube_url(args.video):
        return report("invalid-video-url")
    raw_home = os.environ.get(ENV_HOME, "").strip()
    if not raw_home:
        return report("stage03-not-enabled")
    home = Path(raw_home).expanduser().resolve()
    if not _validate_external_home(home):
        return report("invalid-external-installation")
    executable = find_executable("yt-dlp.exe")
    if executable is None:
        return report("ytdlp-executable-missing")
    deno = find_executable("deno.exe")
    if deno is None:
        return report("deno-executable-missing")

    connection = None
    reserve_port = None
    try:
        if args.mode == "fallback":
            if not wpc_provider_runtime_ready():
                return report("wpc-not-installed")
            # Keep an unlistening socket bound, ensuring that the HTTP port is
            # unavailable throughout this *specific* yt-dlp simulation.
            reserve_port = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            reserve_port.bind(("127.0.0.1", 0))
            base_url = f"http://127.0.0.1:{reserve_port.getsockname()[1]}"
            print("Explicit WPC fallback test: Chrome MAY open during this step.")
        else:
            connection = connect_bgutil_http(deno)
            if connection is None:
                return report("bgutil-server-unavailable")
            base_url = connection.base_url
        command = _build_command(
            executable, deno, home, base_url, args.mode == "fallback", args.video,
            RRV_WPC_PROVIDER_DIR if args.mode == "fallback" else None,
        )
        print("Running a video simulation with token tracing captured privately...")
        try:
            # The PO Token trace can include live token strings. Keep ALL
            # original yt-dlp output in process memory, never in a log/file.
            completed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=150,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except subprocess.TimeoutExpired:
            return report("simulation-timeout")
        except OSError:
            return report("simulation-launch-failed")
        combined = (completed.stdout or "") + "\n" + (completed.stderr or "")
        signals = inspect_trace(combined, completed.returncode)
        return report(classify(args.mode, signals), signals)
    finally:
        if reserve_port is not None:
            reserve_port.close()
        if connection is not None:
            shutdown_bgutil_http()


if __name__ == "__main__":
    raise SystemExit(main())
