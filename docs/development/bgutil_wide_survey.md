# RR-V 1.6.0 Stage03.8: Broad startup diagnostics

## Why a broad survey?

On November 1, 2026, one Windows boot showed BgUtils dependency loading at
about 31 seconds, while repeating the same import on the same boot took about
2.75 seconds. These observations support a cold-versus-warm effect but **do
not identify the cause**. Investigating only another JavaScript module risks
missing file-system delays, process scheduling, security checks, low resources,
or other less-common contributors.

This is one **developer-only** multi-factor survey. No production downloader
settings, WPC behavior, normal Deno startup budgets, antivirus settings,
installed provider files, or Windows configuration are changed. Normal Deno
module loading may populate its existing cache; the script never clears it.

## Checks included in one run

| Domain | Measurements | Important limitation |
| --- | --- | --- |
| Whole graph | First and immediately repeated `session_manager.ts` import | Only the first costly phase is cold |
| Deno runtime | Small standalone JavaScript evaluation | Warm if run after graph |
| Real server | RR-V's own server launcher, initial + repeat, HTTP readiness | Usually warm after import graph |
| Eight module families | canvas, jsdom, youtubei.js, bgutils-js/botguard, bgutils-js/webpo, express, proxy-agent, axios | Individually tested after warm-up, npm cached-only specifiers can have different resolution behavior |
| Process resource use | Deno child CPU milliseconds and read KiB using Windows process counters, where available | Does not measure all descendants or the entire system |
| Disk/files | Read time for three fixed source files, module/cache directory presence, free disk space | Small, post-warm file samples, not a disk benchmark |
| Windows environment | Boot uptime, memory headroom, drive class, proxy presence, symbolic-link location | Context, not causal proof |
| Security context | Read-only Windows Defender real-time status and Deno executable Mark-of-the-Web presence | Defender enabled is not evidence that it delayed any file |

The tool classifies only fixed statuses and times. It does not print raw
Deno logs, URLs, file paths, login credentials, cookies, tokens, or proxy
values. The diagnostic writer appends the same privacy-safe fields to
`%APPDATA%\RR-V\logs\bgutil-stage03.log`.

## Windows smoke test

In GitHub Desktop, pull the newest `develop/1.6.0` branch **before
shutting down**. The next time Windows is started normally, keep RR-V closed
and run this from VS Code PowerShell **before** other Deno commands:

```powershell
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
.\.venv\Scripts\python.exe .\tests\manual\bgutil_wide_survey.py
```

The default is equivalent to `--first graph`: import the whole graph cold,
repeat it, run the Deno baseline, start and restart the actual server, then
check the eight module families and broader environment. You can run it in
an already-warm Windows session, but label it a **warm-session test**.
Do not repeatedly restart Windows just for repeated diagnostics.

For a **separate future boot** the alternative `--first server` places real
server startup first. Do not run both orderings back-to-back and interpret
both as cold. The actual RR-V normal server deadline remains **12 seconds,
plus up to 6 seconds of first-use grace**. The diagnostic's full-server limit
is 50 seconds; the cold dependency graph also has a 50-second limit.
Other individual stages have shorter limits, and the optional Windows
Defender status check is limited to 8 seconds.

No YouTube, WPC, Chrome, or media files are involved. The importer relies
on the installed third-party provider's normal module graph. `--cached-only`
is used for import checks, but imported upstream code has its own behavior.
No external requests are intentionally initiated by the diagnostic.

## How to read the outcome

- `cold-graph-penalty-observed`: initial graph import is at least 10 seconds
  and three times slower than immediate repeat. This identifies an effect,
  **not** its mechanism.
- `cold-process-low-cpu-time`: substantial waiting outside the measured
  process's CPU. Disk, security, background contention, native dependencies
  or process scheduling may merit investigation. **Not** a Defender verdict.
- `cold-process-high-cpu-time`: large CPU cost in measured Deno process;
  CPU-heavy module processing might matter.
- `warm-module-outlier:NAME`: one individual library is slow even after
  the graph warmed. This is an **auxiliary** signal; npm resolution differs
  from the source module's static imports.
- `server-exceeds-production-budget`: diagnostic server reports
  `late-ready`; the real RR-V would have fallen back to WPC earlier.
- `low-memory-at-start`, `low-disk-space`, or
  `nonlocal-or-removable-installation`: broader environmental signals.
- `WIDE SURVEY: NEEDS REVIEW` may occur because an optional npm cached-only
  import is unavailable. This does **not** automatically imply actual RR-V
  or the BgUtils server is broken. Look at each row separately.
- `CPU=unknown` or `process-read=unknown` means Windows did not expose the
  optional counter. Do not interpret it as zero.

A first run may identify multiple candidate factors, but cannot rule out
all rare causes or separate Windows file cache effects from antivirus and
module compilation by itself. Keep unusual results intact rather than
disabling Defender, adding exclusions, deleting caches, reinstalling BgUtils,
or increasing production timeouts.

## What to send

Share the PowerShell output and
`%APPDATA%\RR-V\logs\bgutil-stage03.log`, noting whether it was a
boot-first test or a warmed session. **One broad run is sufficient to
choose the next investigation.** The separately installed GPL-3.0-only
third-party provider remains a development experiment and is not bundled.
