"""Stage03 provider registration smoke without RR-V cookies or saved tokens.

Run only after preparing and explicitly enabling the external provider.
This diagnostic does not write raw logs containing sensitive YouTube data.
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
from services.bgutil_http_service import ENV_HOME, shutdown_bgutil_http  # noqa: E402


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

    # Prevent reading the RR-V login cookie file during this anonymous test.
    command = [str(executable), "--ignore-config", "--verbose", "--simulate", "--no-playlist",
               "--no-color", "--socket-timeout", "20", "--retries", "0", "--extractor-retries", "0",
               "--extractor-args", "youtube:player-client=mweb,tv,web_safari"]
    try:
        with (
            patch.object(ytdlp_service, "RRV_YOUTUBE_AUTH_COOKIE_PATH", ROOT / "__stage03_missing_cookie__"),
            patch.object(ytdlp_service.YtDlpService, "_find_cookie_file", return_value=None),
        ):
            ytdlp_service.YtDlpService.extend_runtime_and_auth_arguments(command, url)
        if "--plugin-dirs" not in command:
            print("No PO Token provider plugin was registered in the command.")
            return 1
        command.append(url)
        print("Launching a simulated YouTube request without RR-V cookies...")
        try:
            result = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            print("Could not finish the simulated YouTube request:", type(error).__name__)
            return 1
        text = result.stdout + "\n" + result.stderr
        markers = [line.strip() for line in text.splitlines() if
                   "PO Token Providers:" in line or
                   ("Generating a " in line and "PO Token" in line) or
                   "Error while importing module" in line]
        for marker in markers[:8]:
            print(marker[:250])
        bgutil_registered = "bgutil:http-2.0.2" in text
        wpc_registered = "wpc-1.1.2" in text
        requested = any("Generating a " in line and "PO Token" in line for line in markers)
        print("BgUtils HTTP registered:", bgutil_registered)
        print("WPC registered:", wpc_registered)
        print("Token request seen:", requested)
        print("yt-dlp simulated video exit code:", result.returncode)
        if not bgutil_registered:
            print("STAGE 03 PROBE: NEEDS REVIEW (BgUtils HTTP plugin not registered)")
            return 1
        print("STAGE 03 PROBE: PROVIDER REGISTRATION PASS")
        if not requested:
            print("The video did not trigger a PO Token request; fallback behavior remains unverified.")
        if result.returncode != 0:
            print("Video processing failed; registration passed but download success is NOT confirmed.")
        return 0
    finally:
        shutdown_bgutil_http()


if __name__ == "__main__":
    raise SystemExit(main())
