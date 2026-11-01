# RR-V 1.6.0 Stage03.9: Windows Deno time-series observation

## Why

BgUtils cold imports took about **30.8 seconds** on a fresh Windows boot,
while the immediate repeat took about **2.7 seconds**. CPU time in the cold
process was only about **5.5 seconds**. These readings raise questions about
CPU scheduling, file I/O, module processing and other environmental waits,
but they do **not** identify a single responsible application or file.

This developer-only tool observes the Deno process **during the first cold
stage**, sampling Windows process CPU, logical I/O, page faults, memory,
thread/handle counts and system-wide CPU activity. It is a safer first pass
than recording a system-wide Windows Performance Recorder/Process Monitor
trace, which can contain private paths and unrelated application activity.

## Run after the next normal boot

1. Update GitHub Desktop's `develop/1.6.0` and leave RR-V closed.
2. After the next usual Windows power-on, open VS Code and run **before**
   any other RR-V tests or Deno commands:

   ```powershell
   $env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_windows_observe.py
   ```

The default `--first graph` observes the same cached-only BgUtils
`session_manager.ts` dependency graph used in earlier measurements. It then
immediately repeats that graph as a warm-session control. A later boot may
instead use `--first server` to observe the real server startup first, also
with an immediate repeat. **Do not run both variants sequentially and treat
both as cold**, because either one may warm file/OS/Deno caches.

No Microsoft utilities need to be installed. Administrator rights are not
requested. No YouTube, Chrome, WPC, login cookies or media files are involved.
The tool does not modify Defender, system settings, external provider source,
or application startup deadlines. It can naturally warm existing Deno/OS
caches by importing modules. The diagnostic timeout is at most 65 seconds
per phase and does not alter the real application's 12+6 second limit.

## Read the output

The process is observed about once per second and summarized in five-second
windows. `CPU(ms)` is aggregate Deno process CPU time (can exceed elapsed
time due to multiple threads); `Read/Write(KiB)` are **logical process I/O
accounting values** which include cached operations, NOT direct physical disk
traffic. `OtherIO` includes operations other than reads/writes. `Faults` is
a count of process page faults, including soft faults, not necessarily disk
fetches. `SysCPU(%)` is an approximate peak sampled CPU utilization across
Windows, not CPU utilization attributed to Deno. `RAM(MiB)` is Deno working
set. `Threads` is a count, **not thread wait reasons**.

The patterns can guide the next choice:

- Long elapsed time, low Deno CPU, little recorded I/O: possible waiting,
  scheduling or external activity; **not proof** of Windows Defender.
- Long elapsed time and large Deno CPU: investigate CPU-intensive module
  initialization/compilation.
- High page faults or read-operations: investigate memory/file access next,
  but cached reads and soft faults alone do not prove slow physical storage.
- High Windows-wide CPU activity alongside low Deno CPU: background
  contention is a candidate, not a confirmed source.
- Slow server `late-ready` means the normal RR-V timeout would have fallen
  back to WPC even if this diagnostic ultimately succeeded.

Unavailable counters display `?`. Process handle access can fail for optional
Windows APIs; missing fields are not zeros. The tool intentionally does not
claim to identify individual blocked file paths, Defender scans or detailed
thread wait causes. Those require a *separate*, explicit and privacy-reviewed
ETW/WPR or Process Monitor capture, not automatically started by this tool.

## Safety and logs

The tool captures raw Deno stdout/stderr only in temporary process memory to
check one fixed completion marker; it never prints or writes those outputs.
It does not persist process file lists, thread IDs, user folder paths,
command lines, proxy URLs, tokens or cookie data. Five-second integer metric
summaries are added to the existing privacy-safe
`%APPDATA%\RR-V\logs\bgutil-stage03.log`, as `bgutil.windows-window` and
`bgutil.windows-phase` events. No new arbitrary raw Windows trace file is
created. You can leave earlier logs intact; the event names and time stamps
separate this test's data.

Please send the PowerShell output and `bgutil-stage03.log` together, noting
whether this was a genuine fresh-boot run or a warm-session run. If the first
stage fails, report that output rather than rerunning repeatedly. The
third-party provider's GPL licensing/distribution question remains separate
from these technical diagnostics.
