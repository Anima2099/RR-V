# Stage03.6 - detailed Deno startup trace (developer-only)

## Background

On November 1, 2026, BgUtils started normally twice (about 3.3 seconds),
then after an overnight Windows shutdown both cold starts timed out after
about 19 seconds. One failed run had `output_kind=server-announced` only
at 18.399 seconds, just before the normal 18-second-plus-polling budget
finished. WPC-only video extraction still worked.

The existing startup log does **not** show whether the local socket began
accepting connections or when `/ping` first returned the pinned version.
This probe supplies those milestones without changing RR-V's production path.

## Run (VS Code PowerShell, `develop/1.6.0`)

First close RR-V, including its tray instance. Do not uninstall, reinstall,
clear Deno caches, or modify the external BgUtils provider. On a new boot,
prefer making this the first Deno-related command, before unit tests or the
four-trial comparison. No reboot is required to use the tool, but a later
boot-first result is most informative for investigating boot-sensitive delays.

```powershell
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
.\.venv\Scripts\python.exe .\tests\manual\bgutil_startup_trace.py
```

This runs **two consecutive new Deno server processes**, each using exactly
the production `_BgUtilServer.ensure()` launcher, `DENO_DIR`, permissions,
loopback address, and preflight validation. Each attempt receives up to **35
seconds** to prepare. The limit is overridden in this diagnostic process only;
RR-V's normal **12-second + first-use 6-second grace** stays unchanged. Each
server is stopped after its attempt. Then the script runs a trivial Deno
JavaScript evaluation as an after-the-fact baseline, so it cannot pre-warm
the first server attempt.

No yt-dlp, PO Token request, WPC, Chrome, cookies, or media download are used.
Only the machine's local `127.0.0.1` socket is inspected. A diagnostic-only
TCP probe follows an unsuccessful standard `/ping` request. The extra TCP
probes can slightly change timing: this is **not** a speed benchmark or an
exact reproduction of the standard production timeout behavior.

If time is limited, `--attempts 1` runs only the first server start and then
the baseline. Do not retry a failed run repeatedly; share its outcome.

## Understand the output

The console prints the same small fixed fields per attempt, e.g.:

```text
Attempt 1: late-ready | elapsed=21000 ms | first-output=20500 ms |
  server-announced=20800 ms | TCP=20900 ms | valid-ping=21000 ms |
  ping-attempts=32 | output=server-announced
```

- `first-output`: first observed Deno stdout/stderr bytes, not their contents
- `server-announced`: first recognized upstream server-start message
- `TCP`: first successful localhost socket connection
- `valid-ping`: first HTTP `/ping` reply with expected provider version
- `ping-attempts`: number of readiness checks within the server launcher
- `elapsed`: overall startup time including validation inside `ensure()`
- `ready`: a valid connection within the normal first-use 18-second budget
- `late-ready`: valid connection after the normal budget but within diagnostic
  35-second limit (supports reconsidering startup policy, not automatically
  increasing production wait)
- `timeout`: no valid connection within the diagnostic limit
- `early-exit`: Deno terminated before readiness
- `start-failed`: another safely classified startup or cleanup failure
- A time value of `0` means **not observed** or less than 1 ms

After both attempts the tool runs a *simple Deno JavaScript startup* and
prints only `baseline-ready`, `baseline-timeout`, `baseline-failed`, or
`baseline-launch-error`, plus elapsed milliseconds. This runs last; it does
**not** reflect a cold OS cache. If Deno's basic runtime is fast but BgUtils
starts slowly, further work should focus on module/dependency initialization,
native modules, or environmental effects, without assigning a cause prematurely.

The existing safe log `%APPDATA%\RR-V\logs\bgutil-stage03.log` also receives
`bgutil.startup` (from the normal service), `bgutil.startup-probe`, and
`bgutil.baseline` entries. It records only fixed categories, timestamps,
process IDs, counts and elapsed milliseconds; **raw process output, URLs,
ports, tokens, cookie data, command lines and filesystem paths are never
printed or saved**. The Deno output is read into bounded in-memory buffers
by the existing sanitized server monitor.

## What to send back

Send the PowerShell result and this diagnostic log, and note whether the run
was performed soon after a Windows reboot or during a warmed-up session.
Never send raw Deno stdout/stderr or user task logs. Wait for interpretation
before changing normal startup timeouts, providers, caching, or public builds.
The GPL-3.0-only upstream provider remains an independently installed,
explicitly enabled **developer experiment**, not a bundled release feature.
