# RR-V 1.6.0 | Stage03.10: one-boot Windows startup and ETW investigation

## Objective

One expensive Windows boot should answer many questions. Unlike repeated
module-only probes, this experiment **starts the actual RR-V BgUtils HTTP
server first**, while Windows Performance Recorder (WPR) simultaneously
records CPU scheduling, disk and file operations. Optional Registry, Network
and Minifilter profiles are included only if the installed WPR supports them.
The same boot then checks a second full server launch, Deno basic runtime,
BgUtils module graph, eight individual library families, memory/disk
availability, network-proxy presence and Defender real-time status.

This is **investigation**, not a default production feature. RR-V's existing
12-second startup budget plus first-use 6-second grace is unchanged. The
experiment uses a diagnostic-only **70-second** server limit.

## Critical privacy boundary

WPR captures **system-wide events**, not just RR-V. Its ETL may contain
filenames, user directory paths, network addresses, process activity and
other private information, even when the WPR marker is `RRV_COLD_BEGIN`.
The ETL is **not automatically anonymized** and MUST NOT be attached to
ChatGPT, GitHub, public bug reports or shared support chats. No source files
are copied to remote services by the Python diagnostic tool. The tool uses
WPR's default **memory mode**, not unbounded file mode, and stops immediately
after the first server launch. Some events may be overwritten if its memory
buffer is overloaded. Deno stdout/stderr remains in process memory only
and is not added to the shared report.

The one-boot tool writes two safe summaries and one **private** ETL into:

`%LOCALAPPDATA%\RR-V\diagnostics\bgutil-oneboot\oneboot-<date-time>\`

- `SAFE-summary.txt` : can be shared with the developer
- `SAFE-summary.json` : can be shared with the developer
- `PRIVATE-Windows-trace-DO-NOT-SHARE.etl` : stay **only** on user's PC

The separate sanitized RR-V diagnostic log remains at:

`%APPDATA%\RR-V\logs\bgutil-stage03.log`

The saved safe summary **does not analyze the raw ETL automatically**:
Windows Performance Analyzer (WPA) is necessary for detailed file,
thread-wait and minifilter attribution. The goal is to preserve the decisive
cold-start evidence **once**, then analyze it later **without further boots**.

## Step 1: PRE-FLIGHT while Windows is already running (no reboot yet)

Update GitHub Desktop to `develop/1.6.0`. Close RR-V including its tray
instance. For preflight and capture, start **Windows PowerShell as
Administrator** (Start menu -> Windows PowerShell -> Run as administrator).
You can still use VS Code for editing and GitHub Desktop, but the actual
ETW capture needs an elevated PowerShell session.

In the elevated PowerShell window:

```powershell
cd "C:\Users\Administrator\Documents\GitHub\RR-V"
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
.\.venv\Scripts\python.exe .\tests\manual\bgutil_oneboot_diag.py --preflight
```

Preflight checks the pinned external BgUtils installation, availability of
Deno and WPR, elevation, at least **3 GiB** available local storage and
whether WPR can actually **start, save and stop** its selected recording
profiles. A short private test ETL is stored in a temporary folder, then
deleted automatically. Preflight itself does **not** start Deno or analyze
YouTube. It records its verified profile choice in a local allowlisted
manifest, valid for seven days.

Only when the screen says exactly:

`PREFLIGHT: READY. Next normal power-on may run --capture once.`

is the valuable reboot test ready. If it says `NOT READY`, **do not reboot**
for this experiment. Preserve that result; do not disable security software,
restart services or blindly use `wpr -cancel` (a different program may own
a session). If stop or cancellation is unconfirmed, inspect `wpr -status`
and report that, not the raw system trace.

Windows ships with the `wpr.exe` command-line binary. WPA (`wpa.exe`) is a
separate viewer supplied as part of the Microsoft Windows Performance
Toolkit; it is useful later but **not required to capture the ETL**.

## Step 2: CAPTURE at the next normal Windows startup

Shut down and power on as usual. Use the **same** shutdown/power-on pattern
as earlier comparisons. Before starting RR-V or other Deno-related tests,
open an **Administrator** PowerShell, and run:

```powershell
cd "C:\Users\Administrator\Documents\GitHub\RR-V"
$env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
.\.venv\Scripts\python.exe .\tests\manual\bgutil_oneboot_diag.py --capture
```

**Running `--capture` is consent to a local, sensitive system-wide WPR
recording**. WPR begins before the first Deno server process, marks the
start and end of the cold phase, stops and saves the ETL, then performs the
warm tests. It tries CPU, DiskIO, FileIO, plus any verified Registry,
Network and Minifilter profiles. The WPR capture should encompass only
roughly 3-70 seconds of cold server launch; saving the ETL can add time.

The script then automatically:

1. starts the same BgUtils HTTP server again as a warm control;
2. measures the `session_manager.ts` import graph and a basic Deno runtime;
3. measures eight individual module imports (already warm);
4. collects safe system storage, memory, Defender and proxy presence;
5. creates `SAFE-summary.json` and `SAFE-summary.txt` and prints the main
   results. No YouTube download, token request or Chrome run is required.

**Do not reboot again for follow-up measurements** unless analysis of the
WPR file identifies a specific missing experiment. If Windows ETW fails,
the tool does not claim that the missing trace was captured. If WPR cannot
start at all it intentionally does **not** run the cold phase, preserving
that first-run opportunity for the next decision.

## Step 3: What to send back

Send **only** `SAFE-summary.txt` (or `.json`), your PowerShell result, and
`%APPDATA%\RR-V\logs\bgutil-stage03.log`. In File Explorer, press Win+R,
enter `%LOCALAPPDATA%\RR-V\diagnostics\bgutil-oneboot`, and open the newest
`oneboot-...` folder.

Do **NOT** attach any `.etl`, ETL archive, Windows full event log or raw WPA
export. Those can contain activity from unrelated programs and user paths.
The safe summary provides a cold/warm comparison and the exact markers and
process timing for later WPA examination.

## Step 4: Follow-up on the SAME ETL (no new reboot)

If safe metrics suggest a file/scheduler bottleneck but cannot identify it,
install **Windows Performance Toolkit only** from Microsoft's Windows ADK,
then locally open the private ETL in Windows Performance Analyzer. The
specific helpful panels are:

- **CPU Usage (Precise)**: ready vs waiting time and context switches; filter
  to the Deno process and `RRV_COLD_BEGIN` / `RRV_COLD_END` timeframe.
- **CPU Usage (Sampled)**: CPU work within Deno during the cold interval.
- **Disk Usage** and **File I/O**: actual disk duration/queue and expensive
  file operations; filter to Deno and the cold interval.
- **Minifilter I/O**: filter driver behavior if that profile was captured.
- **Networking**: only if the corresponding WPR profile was available.

Before sharing a screenshot, **hide file paths, user names, full command
lines, addresses, unrelated process names and other private columns**.
A local ETL stays useful for many further hypotheses without restarting
Windows again. Defender enabled alone does NOT prove Defender caused a
slowdown. A separate `New-MpPerformanceRecording -Seconds` capture uses
Windows tracing and is NOT silently started concurrently with WPR; such a
capture would be a separate, explicit test only if the first ETL demands it.

## Interpretation and decision ladder

- **Cold server slow and file/disk/minifilter trace shows latency**:
  investigate installation layout, cache location, filesystem filtering
  and I/O stack; do not turn off Defender or suggest exclusions prematurely.
- **Cold server slow but disk low, Deno CPU low, high waiting time**:
  investigate thread wait stacks, loader/native-library initialization,
  scheduling and possible synchronization bottlenecks.
- **Cold server slow and Deno CPU high**:
  investigate expensive module compilation/initialization and packaging.
- **Network or registry delays align with wait intervals**:
  inspect the relevant initializers before modifying user-facing behavior.
- **Cold server fast, graph probe slow**: revisit the synthetic probe's
  fidelity to the real RR-V startup; don't misdiagnose the product.
- **ETL unavailable yet passive metrics successful**: information is
  incomplete, not a solved root cause. Decide whether a single targeted
  recapture is worth it after reviewing preflight and errors.

The project's objective remains **BgUtils-first, with Chrome-free normal
operation**. WPC remains a safety fallback in development; do not silently
make it the primary strategy due to one observed cold-start slowdown. Actual
packaging/distribution of the separately-installed GPL-licensed provider
requires its own legal/compliance review before release.

## Safety and recovery

The script never changes antivirus settings, deletes Deno cache, installs
anything, starts WPC/Chrome, or changes production server timeouts. The
recording is started and stopped inside `try/finally`, including after
ordinary Python exceptions. If a WPR command hangs or the process crashes,
`wpr -status` can be used to inspect residual traces. Only run `wpr -cancel`
when you are sure this experiment owns the active session, because `-cancel`
discards its record. Do not share WPR console output if it contains paths.
