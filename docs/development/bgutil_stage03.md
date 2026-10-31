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
- `--plugin-dirs` points at the **external installation root**, which contains
  `plugin.zip` and the unpacked `plugins/yt_dlp_plugins/` package. yt-dlp scans
  immediate children of the given directory; pointing at `plugins/` itself
  prevents the provider from being discovered.
- In the normal opted-in RR-V application, both providers are registered:
  BgUtils HTTP first and WPC second. Official provider preference values are
  BgUtils HTTP 130 and WPC -100. No separate download retry is added.
- If the external files are absent or server initialization fails, attach only
  WPC. A 60-second cooldown prevents rapid retry loops on server failures.
  The first Deno launch allows a bounded 12-second wait plus up to 6 seconds
  of one-time cold-start grace while the child stays alive; later attempts
  remain limited to 12 seconds. The safe `bgutil.startup` diagnostic records
  phases, durations, ping counts and output *categories* without raw Deno logs.
  The separate diagnostic probe reports sanitized server states such as
  `invalid-external-installation`, `deno-executable-missing`,
  `deno-exited-before-ready:code=1`, or `server-ping-timeout`, without printing
  raw server output that might contain token values.
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

2. Prepare the separate external GPL provider in LocalAppData **only if the
   Stage03 setup has not already passed on this PC**:

~~~powershell
powershell -ExecutionPolicy Bypass -File .\tests\manual\prepare_bgutil_stage03.ps1
~~~

If `STAGE 03 SETUP RESULT: PASS` already appeared earlier, **do not rerun the
installer**. This fix reuses the existing pinned files in
`%LOCALAPPDATA%\RR-V\bgutil-stage03-external` without any redownload or
reinstallation. WPC remains unchanged.

3. Enable only in this VS Code terminal session:

~~~powershell
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
~~~

4. **BgUtils-only** registration probe, with WPC/Chrome and RR-V cookies
   explicitly disabled. This is a simulation, not a full download:

~~~powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_stage03_probe.py
~~~

If the video is unavailable, supply a known-working public YouTube URL as the
first argument. Expect the following output:

~~~text
BgUtils server status: ready
BgUtils HTTP registered: True
WPC registered (must be False): False
Plugin import error: False
STAGE 03 PROBE: BGUTIL-ONLY REGISTRATION PASS
~~~

The probe does not include any WPC plugin directory and fails rather than
starting yt-dlp if the standalone server is unavailable. **No Chrome window
should open during this test.** If it does, stop and report the anomaly.
`BgUtils token request attempted: False` means no request was observed, not
that the token provider was incapable of minting. Earlier Stage02 successfully
generated a token directly; YouTube demand and yt-dlp integration still need
validation separately.

The real RR-V application will still register WPC as a fallback when enabled;
WPC can launch Chrome when it is genuinely selected. Do not conflate the
BgUtils-only isolated test with the subsequent WPC fallback smoke.

Never share raw verbose logs without redacting tokens or session content.

### Safe Stage03 diagnostic log (when real RR-V only registers WPC)

The developer build now writes a dedicated **privacy-minimal** log:

```text
%APPDATA%\\RR-V\\logs\\bgutil-stage03.log
```

The file contains short status codes, process IDs and timestamps only, without
video URLs, titles, cookie files, raw exceptions, command lines or PO Tokens.
Upload **this file first**, rather than the downloads' verbose task logs.
It also records successful **analysis** and **download** provider selections,
so users need not paste complex PowerShell log-parsing commands.

Relevant event names:

| Event | What it shows |
| --- | --- |
| `app.launched` | Whether the newly launched Python/EXE process inherited the opt-in setting |
| `app.primary` | Which process actually became RR-V's main instance |
| `app.forwarded` | A second launch forwarded to an already running primary |
| `bgutil.connection` | Whether the standalone Deno server became ready, or a safe failure status |
| `youtube.providers` | Provider selection per **analysis** or **download**, including WPC-only fallback |
| `bgutil.stopped` / `app.closed` | Normal server / application shutdown |

Example of a successful integration:

```text
event=app.launched | pid=123 | mode=enabled | runtime=source
event=app.primary | pid=123 | mode=enabled
event=bgutil.connection | pid=123 | result=ready | status=ready | server_pid=456
event=youtube.providers | pid=123 | stage=analysis | mode=enabled | deno=found | bgutil=ready | wpc=available | route=bgutil-and-wpc
event=youtube.providers | pid=123 | stage=download | mode=enabled | deno=found | bgutil=ready | wpc=available | route=bgutil-and-wpc
```

Example of an unsuccessful integration:

```text
event=bgutil.connection | pid=123 | result=fallback | status=server-ping-timeout | server_pid=0
event=youtube.providers | pid=123 | stage=analysis | mode=enabled | deno=found | bgutil=server-ping-timeout | wpc=available | route=wpc-only
```

This diagnostic log records which providers **were attached to yt-dlp**.
It does not by itself prove which provider minted an actual token or that a
particular download succeeded. Output is rotated to `bgutil-stage03.log.1`
when the active file grows beyond 512 KiB.

To collect a clean test: fully exit RR-V (including tray), launch the developer
build from the terminal with `RRV_BGUTIL_STAGE03_HOME` set, analyze and download
one public YouTube video, then attach `bgutil-stage03.log`. There is no need to
reinstall BgUtils, repeat the anonymous standalone probe or run a separate
process-list command. If the log is missing after this, report that result
rather than attaching unrelated unredacted logs.

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

## Token issuance and controlled fallback verification

The previous diagnostic log confirms *provider registration* and Deno server
reuse, not successful token minting. Run this separate, opt-in validation from a
VS Code PowerShell terminal. **Fully exit RR-V** first so this independent
diagnostic doesn't conflict with its local server or an old instance.

1. Enable the existing, independently prepared provider (no installation needed):

~~~powershell
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
~~~

2. Confirm BgUtils can issue a PO Token to yt-dlp, with **WPC excluded**:

~~~powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_token_fallback_probe.py
~~~

Expected on a successful public test video:

~~~text
Stage03 mode: bgutil
Token issuance: CONFIRMED
Status: bgutil-token-confirmed
BgUtils registered: True
WPC registered: False
BgUtils response observed: True
WPC response observed: False
Video simulation exit code: 0
~~~

A request attempt or normal video simulation exit alone is not treated as
proof. The verifier requires yt-dlp's **provider-returned token response**
marker with PO Token tracing explicitly enabled, WPC not registered, and a
successful simulated video request. The trace **can contain sensitive raw PO
Tokens**, so the entire yt-dlp stdout/stderr is captured in memory, scanned for
known markers, and **never printed or saved**. The verifier writes *only
categorical status codes* to the existing privacy-minimal
`%APPDATA%\RR-V\logs\bgutil-stage03.log`. If the video requires login or does
not request tokens, provide another accessible public video using the
`--video "https://www.youtube.com/watch?v=..."` option.

3. **Only after BgUtils succeeds**, explicitly test HTTP failure handling and
   the WPC fallback using a dedicated, guaranteed-unlistening localhost port:

~~~powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_token_fallback_probe.py --mode fallback
~~~

This runs a *separate simulation*, never rewrites the installed provider and
does not intentionally corrupt or stop the real Deno server. It registers both
providers, but directs BgUtils HTTP at an unavailable loopback port so yt-dlp
can attempt the lower-priority WPC provider. **Chrome may open as part of this
intentional fallback test**. Do not run this step in routine browser-free
verification.

Successful fallback proof requires a returned WPC token-response marker, not
merely the appearance of Chrome. Expected result:
`Status: wpc-token-confirmed`. If token generation is not required or WPC
fails, the script reports `NOT CONFIRMED` instead of a false PASS.

Record both results separately. This verifies token provider integration in
yt-dlp simulated extraction, not an actual file download or the user-facing
application's handling of every possible YouTube error.

## Stage04 / release gate

- The experimental setup script is NOT a public automatic component installer.
- Formal license compliance/distribution decision, secure installer, download
  integrity, native dependency handling, version upgrades, clean uninstall and
  orphan process recovery remain separate release blockers.
- The program startup timer must remain unaffected when the feature is disabled;
  compare Windows cold-start measurements if integration is later enabled by
  default after legal review.
