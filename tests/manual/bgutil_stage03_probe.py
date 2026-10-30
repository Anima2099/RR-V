"""Stage03 BgUtils-only smoke, with WPC/Chrome explicitly disabled.

No RR-V cookies are loaded. The server status is reported without revealing
raw provider logs, which can otherwise contain live PO Tokens.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.paths import find_executable  # noqa: E402
from services import ytdlp_service  # noqa: E402
from services.bgutil_http_service import (
    ENV_HOME, bgutil_http_status, connect_bgutil_http, shutdown_bgutil_http,
)  # noqa: E402


TEST_VIDEO = "https://www.youtube.com/watch?v=jNQXAC9IVRw"


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else TEST_VIDEO
    if not ytdlp_service.YtDlpService.is_youtube_url(url):
        print("Provide a public YouTube URL only.")
        return 2
    if not os.environ.get(ENV_HOME):
        print(f"Stage03 mode is disabled. Set {ENV_HOME} before running this test.")
        return 2
    executable = find_executable("yt-dlp.exe")
    if executable is None:
        print("RR-V yt-dlp.exe is unavailable.")
        return 2

    # Refuse to launch yt-dlp until the external HTTP server is ready.
    # This keeps WPC/Chrome entirely out of the diagnostic path.
    try:
        deno = find_executable("deno.exe")
        if deno is None:
            print("BgUtils server status: deno-executable-missing")
            print("STAGE 03 PROBE: NEEDS REVIEW (Deno unavailable; no browser launched)")
            return 1
        connection = connect_bgutil_http(deno)
        print("BgUtils server status:", bgutil_http_status())
        if connection is None:
            print("STAGE 03 PROBE: NEEDS REVIEW (local HTTP provider unavailable; no browser launched)")
            return 1

        # Never use RR-V's saved cookies or the Chrome-based WPC in this
        # anonymous registration test. Real fallback testing is a later step.
        command = [
            str(executable), "--ignore-config", "--verbose", "--simulate",
            "--no-playlist", "--no-color", "--socket-timeout", "20",
            "--retries", "0", "--extractor-retries", "0",
            "--extractor-args", "youtube:player-client=mweb,tv,web_safari",
        ]
        with (
            patch.object(ytdlp_service, "RRV_YOUTUBE_AUTH_COOKIE_PATH", ROOT / "__stage03_missing_cookie__"),
            patch.object(ytdlp_service.YtDlpService, "_find_cookie_file", return_value=None),
            patch.object(ytdlp_service, "wpc_provider_runtime_ready", return_value=False),
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(command, url)

        dirs = [command[i + 1] for i, arg in enumerate(command[:-1]) if arg == "--plugin-dirs"]
        if dirs != [str(connection.plugin_dir)] or "--no-plugin-dirs" not in command:
            print("STAGE 03 PROBE: NEEDS REVIEW (isolated plugin directory not configured)")
            return 1
        command.append(url)
        print("Launching BgUtils-only YouTube simulation (WPC/Chrome disabled)...")
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=120, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print("Could not finish simulated YouTube request:", type(error).__name__)
            return 1

        output = result.stdout + "\n" + result.stderr
        providers = next(
            (line.strip() for line in output.splitlines() if "PO Token Providers:" in line),
            "(no PO Token provider registration line)",
        )
        print(providers[:250])
        bgutil_registered = "bgutil:http-2.0.2" in providers
        wpc_registered = "wpc-1.1.2" in providers
        token_attempted = any(
            "[pot:bgutil:http]" in line and "Generating a " in line and " PO Token" in line
            for line in output.splitlines()
        )
        import_error = "Error while importing module" in output
        print("BgUtils HTTP registered:", bgutil_registered)
        print("WPC registered (must be False):", wpc_registered)
        print("BgUtils token request attempted:", token_attempted)
        print("Plugin import error:", import_error)
        print("yt-dlp simulated video exit code:", result.returncode)
        if import_error or wpc_registered or not bgutil_registered:
            print("STAGE 03 PROBE: NEEDS REVIEW (plugin loading/isolation issue)")
            return 1
        print("STAGE 03 PROBE: BGUTIL-ONLY REGISTRATION PASS")
        if not token_attempted:
            print("This video did not trigger a BgUtils token request; token minting not verified here.")
        if result.returncode != 0:
            print("Video processing failed; registration passed but download success is NOT confirmed.")
        return 0
    finally:
        shutdown_bgutil_http()


if __name__ == "__main__":
    raise SystemExit(main())
