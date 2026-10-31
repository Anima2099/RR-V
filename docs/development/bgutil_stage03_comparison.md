# RR-V 1.6.0 - Stage 03.5 WPC vs BgUtils comparison

## Why this comparison exists

Stage03 verified both BgUtils HTTP PO Token issuance and the WPC fallback.
It did not establish that BgUtils improves everyday YouTube analysis speed or
reduces browser launches compared with RR-V 1.5.0. A browser-free result with
WPC alone is normal when no PO Token needs to be issued.

Code inspection confirms that RR-V `main` (1.5.0 Stable) attaches WPC but does
not force a YouTube player client. The `develop/1.6.0` builder with
`RRV_BGUTIL_STAGE03_HOME` disabled follows the same provider behavior. This
allows a controlled comparison without switching installed applications.

## What this test does

- WPC-only (1.5.0-style) versus BgUtils-preferred with WPC fallback (1.6.0).
- Uses one and the same local `yt-dlp.exe`, Deno runtime, video URL, and
  yt-dlp extraction flags for both cases.
- Keeps the default YouTube client selection. Does not force `mweb`, `tv`, or
  `web_safari`, unlike the previous stress/fallback verification.
- Runs a non-downloading simulation, not an actual file download.
- Uses `--ignore-config`, `--no-cache-dir` and **no login cookies** for both
  modes. Consequently, it does not represent every authenticated user case.
- The **new recommended runner** launches one fresh Python worker per trial.
  Group A is BgUtils → WPC; Group B is WPC → BgUtils. Four independent
  interpreters are launched sequentially, so the server manager state is
  never reused across different trials.
- The previous shared-process tool (`bgutil_ab_compare.py`) is retained
  for diagnostics, but is no longer the recommended smoke test.
- Captures PO Token trace **in memory only**, classifies actual provider
  responses, and does not print or save raw tokens, credentials, stdout,
  stderr, video URLs, or user filesystem paths.
- Measures provider setup (including cold Deno startup), simulated video
  extraction and total time inside each worker, plus wall-clock time that
  includes launching and closing the worker Python process. Both BgUtils
  rows are cold-server cases, rather than one cold and one warm use.
  This is a diagnostic of order/initialization sensitivity, not an
  apples-to-apples production throughput benchmark.
- Records safe outcome codes, group order, child process PID and
  millisecond values in `%APPDATA%\RR-V\logs\bgutil-stage03.log`.
  `compare.isolated` PID matches `bgutil.startup` PID if the worker
  actually attempted Deno startup.
- WPC **may open Chrome** if the video actually triggers a PO Token request;
  browser-window appearance must still be observed by the Windows tester.

## Windows smoke steps

1. GitHub Desktop: select `develop/1.6.0`, Fetch/Pull origin. Close RR-V,
   including the system tray. Open VS Code PowerShell in the repo.
2. Run Python unit tests:

   ```powershell
   .\.venv\Scripts\python.exe -m unittest discover -s tests
   ```

3. Activate the existing external developer-only installation:

   ```powershell
   $env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
   ```

4. Run the **isolated opposite-order comparison** once. The command
   starts four worker Python processes automatically:

   ```powershell
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_ab_isolated.py
   ```

5. Copy/paste the comparison summary and attach only `bgutil-stage03.log`.
   Mention whether a Chrome window appeared. All four trials run even if
   an earlier one fails so both orders can be compared. If the output
   reports `ISOLATED COMPARISON: NEEDS REVIEW`, do not keep retrying;
   share the status and log for root-cause diagnosis.

Optional: pass `--video "https://www.youtube.com/watch?v=..."` for another
public, unauthenticated video. Use the SAME URL for both modes by running one
script invocation, not separate manual commands.

## Interpreting the independent-process experiment

In the normal four-worker run:

| Group | Worker order | What it isolates |
| --- | --- | --- |
| A (`bgutil-first`) | BgUtils 1, WPC 1 | Can a fresh BgUtils process start before any WPC trial? |
| B (`wpc-first`) | WPC 2, BgUtils 2 | Does an immediately prior WPC *process* affect the next fresh BgUtils process? |

The script runs both groups **sequentially**, not concurrently. Each worker
uses the same video, yt-dlp executable and default YouTube client selection,
and closes its own Deno server before the next worker runs. The child reports
only a validated fixed-status JSON message, never raw yt-dlp output. The
parent discards the child's unvalidated stdout/stderr and reports
`worker-protocol-error` if the message cannot be authenticated by PID
and the expected scenario/trial metadata.

If both orders work but the old shared-process test still fails, shared
Python state becomes a stronger hypothesis. This would not establish a
root cause by itself. If BgUtils fails in both orders, investigate its
cold-start/environment path. If only one order fails, inspect the safe
startup phase records for the specific child PID. Remember that these are
only two observations per provider.

The earlier `bgutil_ab_compare.py` still exists as an optional
shared-process control for further diagnosis; do not run it repeatedly
unless the new isolated test establishes a reason.

## Deno cold-start diagnostics and bounded recovery

The new `bgutil.startup` events in
`%APPDATA%\\RR-V\\logs\\bgutil-stage03.log` distinguish:

- `phase=spawned`: the Deno process was launched. The log includes a process
  identifier and an elapsed time, never the command line.
- `phase=cold-grace`: the **first** launch in a Python process remained alive
  after the ordinary 12-second limit. It receives a single additional
  6-second grace period. Subsequent attempts retain the original 12-second
  budget, and a failed start still triggers the 60-second retry cooldown.
- `phase=ready`: HTTP `/ping` returned the pinned provider version.
- `phase=failed`: Deno exited or failed to return a valid `/ping`
  response by the bounded deadline. The connection falls back to WPC.
- `phase=launch-failed`: Deno could not be launched.

Each startup event includes the **safe** fields `startup_ms`, `ping_attempts`,
`output_kind` and `first_output_ms`. The output category is restricted to
`no-output`, `other-output`, `dependency-loading`, `server-announced`,
`listen-error`, `module-error`, `permission-error`, or
`dependency-fetch-error`. This is evidence to guide diagnosis, not a
guarantee of the root cause. Deno stdout/stderr are drained in memory and
converted to those allowlisted categories. **Raw Deno output, paths and PO
Tokens are never written or printed**. The capture thread continues draining
after startup without retaining text.

If a comparison stops at `bgutil-startup-timeout` (or another
`provider-setup-mismatch`), inspect the latest `bgutil.startup` event before
changing the timeout or reinstalling any components. Do not repeat a failing
comparison without examining the log.

## How to interpret results

- `status=ok` means yt-dlp simulated extraction succeeded and the expected
  provider(s) registered. It does not prove a PO Token was requested.
- `token_source=none` means no provider *response* appeared in the trace;
  this is not an error if the requested video did not require a token.
- `token_source=bgutil` means BgUtils returned a token during a traceable
  request; `token_source=wpc` means WPC did so.
- `chrome_signal=yes` detects WPC's log message for initiating its browser,
  not a definitive observation of an actual visible Chrome window.
- Compare **startup/setup**, **per-video extraction**, and **overall total**
  separately. Four measurements are indicative and are not statistically
  reliable throughput benchmarks.
- Do not change 1.6.0's default provider or publicly bundle the GPL-only
  provider solely on these results. Licensing and distribution review remain
  separate release gates.
