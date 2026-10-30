# RR-V 1.6.0 / Stage 03 - experimental external BgUtils HTTP bridge

## Boundary and licensing

- Development-only opt-in. The RR-V repository and installer do **not** bundle
  Brainicism's GPL-3.0-only BgUtils POT Provider source, plugin, or native modules.
- The original BgUtils library is MIT, but the POT Provider server and plugin
  are GPL-3.0-only, **not** automatically licensed for use in RR-V's proprietary
  source-available distribution. Merely communicating via a socket does not
  conclusively resolve the legal combined-work question.
- Do not enable automatic installation, make this the default, or release it
  publicly until distribution and compliance receive a separate review.
- Official upstream provider 2.0.2 (2026-10-07), pinned commit
  `26475e9d3665b972c4aeb83b4dbaafcf64b88438`.
- Developer-only setup uses official plugin ZIP SHA-256
  `a26b980bf6d8e8400d8f21445daa4d8381bf6183d20f0be309391f86b31e27ef`.

## Architecture

- Default, no environment variable: existing WPC-only behavior, unchanged.
- With `RRV_BGUTIL_STAGE03_HOME` explicitly set to the prepared external dir:
  start Deno HTTP server **lazily on the first YouTube job**, not on RR-V startup.
- Deno server binds **only** 127.0.0.1, on an ephemeral port, and is reused
  during the same RR-V process. It is terminated on app shutdown or Python exit.
- Both plugins are supplied to yt-dlp using `--plugin-dirs`: external BgUtils
  first, existing WPC second. Official provider preference values are
  BgUtils HTTP 130 and WPC -100. No separate download retry is added.
- If the external files are absent or server initialization fails, attach only
  WPC. A 60-second cooldown prevents rapid retry loops on server failures.
- If the server fails **during an active download**, yt-dlp's provider selection
  may fall back to WPC. That specific behavior must be verified in a real
  Windows smoke test and must not be represented as guaranteed yet.
- No existing RR-V login file is written by the bridge. Normal RR-V login/cookie
  behavior is unchanged; the optional diagnostic probe intentionally uses no
  saved RR-V cookies.

## Setup and tests on Windows

In GitHub Desktop, select `develop/1.6.0`, Fetch and Pull origin. Open VS Code.

1. Verify the existing Python unit tests first:

~~~powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
~~~

2. Prepare the separate external GPL provider in LocalAppData:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\tests\manual\prepare_bgutil_stage03.ps1
~~~

This prepares the pinned upstream source, checks official plugin SHA-256 and
installs Deno dependencies into `%LOCALAPPDATA%\RR-V\bgutil-stage03-external`.
It does not modify RR-V's WPC installation. To deliberately replace an existing
external stage03 folder, close RR-V and rerun with `-Force`.

3. Enable only in this VS Code terminal session:

~~~powershell
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
~~~

4. Verify yt-dlp detects the HTTP provider and WPC using a public video. This
   is a **simulation**, not a full download, and never uses saved RR-V cookies:

~~~powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_stage03_probe.py
~~~

If the video is unavailable, supply a known-working public YouTube URL as the
first argument, e.g. `...\bgutil_stage03_probe.py "https://youtube.com/watch?v=..."`.
Look for `BgUtils HTTP registered: True` and `WPC registered: True`.
Provider **registration** is not equivalent to token **minting**. If the
simulation never requests a PO Token, use an appropriate accessible video for
additional smoke tests. Never share raw verbose logs without checking for
account/session/token content.

5. Run the actual developer build in the **same terminal**:

~~~powershell
.\.venv\Scripts\python.exe .\main.py
~~~

Test a normal YouTube video from the RR-V UI. Verify analysis, download,
subtitles and cancellation still work and that unrelated sites behave as before.
An actual token request may not be triggered by every video. Inspect RR-V's
redacted task log for `pot:bgutil:http`, `pot:wpc`, and warnings, without sharing
raw cookie data. Test a second video to check that the server is reused.

6. To return to WPC-only behavior, **close RR-V** and in the terminal run:

~~~powershell
Remove-Item Env:RRV_BGUTIL_STAGE03_HOME -ErrorAction SilentlyContinue
~~~

Then run the developer build again. No source code change or cleanup is needed.

## Stage04 / release gate

- The experimental setup script is NOT a public automatic component installer.
- Formal license compliance/distribution decision, secure installer, download
  integrity, native dependency handling, version upgrades, clean uninstall and
  orphan process recovery remain separate release blockers.
- The program startup timer must remain unaffected when the feature is disabled;
  compare Windows cold-start measurements if integration is later enabled by
  default after legal review.
