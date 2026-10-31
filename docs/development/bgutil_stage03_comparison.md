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
- Runs each mode twice, in alternating WPC/BgUtils/BgUtils/WPC order.
- Captures PO Token trace **in memory only**, classifies actual provider
  responses, and does not print or save raw tokens, credentials, stdout,
  stderr, video URLs, or user filesystem paths.
- Measures provider setup (including first BgUtils server start), extraction,
  and total elapsed times. Server startup on the first BgUtils request can
  reasonably be slower than subsequent requests. The last WPC-only run may
  occur while the BgUtils server is still alive; this is a diagnostic, not
  a controlled benchmark of per-process resource consumption.
- Records safe outcome codes and millisecond values in the already-existing
  `%APPDATA%\RR-V\logs\bgutil-stage03.log`.
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

4. Run ONE automated comparison:

   ```powershell
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_ab_compare.py
   ```

5. Copy/paste the comparison summary and attach only `bgutil-stage03.log`.
   Mention whether a Chrome window appeared. If a run reports
   `COMPARISON: NEEDS REVIEW`, do not retry repeatedly; share the safe status
   and log so the actual failure can be diagnosed.

Optional: pass `--video "https://www.youtube.com/watch?v=..."` for another
public, unauthenticated video. Use the SAME URL for both modes by running one
script invocation, not separate manual commands.

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
