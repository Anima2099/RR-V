# Stage03.7: Cross-boot Deno / BgUtils dependency initialization experiment

## Why this exists

In the 2026-11-01 Windows smoke tests, the first RR-V BgUtils server start
sometimes took approximately 34.9 seconds after a Windows shutdown, then
approximately 3.3 seconds immediately afterward. The first output and server
announcement occurred at about 34.7 seconds; the HTTP endpoint became ready
roughly 0.2 seconds later. This implicates startup *before* the first server
announcement, but does **not** establish whether the slowdown is Deno runtime
startup, loading a large JavaScript/TypeScript module graph, or other startup
work such as Windows security/file-system activity.

This new tool compares three deliberately different stages, selecting which
one runs **first after boot**, without modifying the normal RR-V runtime.

| Stage | What runs | What it can tell us |
| --- | --- | --- |
| `runtime` | Deno launches trivial `eval` JavaScript | Basic process/runtime startup; no BgUtils imports |
| `imports` | Deno loads `server/src/session_manager.ts` and its dependency graph, without constructing a session or starting an HTTP server | Deno plus a major part of the BgUtils dependency load, including static imports; does **not** cover all of `main.ts` |
| `server` | The actual RR-V `_BgUtilServer.ensure()` with the real entrypoint | Full server startup, port binding and readiness check |
| `server-repeat` | A second full server launch in the same boot session | How much another launch speeds up after earlier stages |

The module-only stage uses `deno run --cached-only ... -` with a small
TypeScript snippet piped through stdin. The module's file URI is constructed
from the validated external installation, passed only through **stdin** and
never logged or included in the process command line. `--cached-only` prevents
Deno from downloading uncached dependencies during that probe, so a missing
cache may produce `imports-failed` even if the normal server could attempt
another resolution path. This stage does not instantiate `SessionManager`,
which means it cannot time construction side effects such as setting up the
DOM; it is a **partial** dependency-graph diagnostic, not a substitute for
full server startup.

## Windows smoke steps

1. GitHub Desktop: select `develop/1.6.0` and Fetch/Pull. Close RR-V, including
   tray instance. Do not reinstall BgUtils, delete caches or disable antivirus.
2. During the **next normal Windows shutdown and power-on**, start VS Code and
   run this command *before* opening RR-V or running any other Deno tests:

   ```powershell
   $env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_boot_sequence_probe.py --first runtime
   ```

3. Paste the console summary and attach `%APPDATA%\RR-V\logs\bgutil-stage03.log`.
   This is the next highest-value test because we already have an earlier
   **server-first** cold-start trace (~34.9 seconds).
4. If warranted after the results are interpreted, on a **different** Windows
   startup run `--first imports` instead of `--first runtime` to measure whether
   the first load of the import graph is slow. An optional `--first server`
   repeats the original control experiment. Use the *same* shutdown/start
   procedure when comparing across boots; `Restart` and `Shut down` can have
   different Windows initialization behavior, including Fast Startup effects.

**Do not run the three modes consecutively and call them all “cold”.** Once
one mode has started Deno, the OS and Deno may already have warmed caches for
the subsequent modes. The script prints all stages in one controlled order,
but only the first stage is comparable across cold boots.

If you want to inspect the script immediately without a reboot, it can still
run; just label it a **warm-session experiment**. Avoid unnecessary repeated
runs after a failure. No boot automation is scheduled by this tool.

## Exact stage order

- `--first server`: `server` -> `server-repeat` -> `imports` -> `runtime`
- `--first runtime`: `runtime` -> `imports` -> `server` -> `server-repeat`
- `--first imports`: `imports` -> `runtime` -> `server` -> `server-repeat`

The real server startup stage has a diagnostic-only ceiling of **60 seconds**.
The Deno runtime/import stages also have individual 60-second ceilings. The
actual RR-V application remains at **12 seconds + up to 6 seconds one-time
cold-start grace**; this tool **does not** change that behavior. Each server
is shut down before the next stage. No YouTube calls, PO Tokens, WPC, Chrome,
login cookies, video analyses, or downloads are involved.

## Output interpretation

- `runtime-ready`: bare Deno eval completed; `runtime-timeout`/`runtime-failed`
  are safe fixed codes without child process output.
- `imports-ready`: `session_manager.ts` and its transitive import graph loaded;
  **not** proof the whole server is ready. `imports-failed` may mean import
  resolution, missing cache, native module load or another error. Its stderr
  is intentionally never shown or stored.
- `ready`: the full server was ready within the normal 18-second first-use
  comparison budget.
- `late-ready`: the full server only became ready after the normal budget,
  within the diagnostic 60-second window. It would not be accepted by the
  current RR-V normal startup policy.
- `timeout`, `early-exit`, `start-failed`, `probe-exception`: full server
  couldn't start; don't infer a root cause from the category alone.

Each stage logs `event=bgutil.boot-sequence`, `order`, `phase`, `result`,
`startup_ms`, and (for server stages) safe timestamps for first output,
server announcement, TCP connection and valid `/ping`. The previous
`bgutil.startup` events are retained. **Raw Deno stdout/stderr, private paths,
file URLs, network ports and authentication data are never printed or saved.**
Only the minimal protocol marker is checked in memory before output is
discarded. The external third-party GPL provider remains installed separately
for development only, not bundled with the RR-V installer.

## Interpreting the cross-boot difference

If `runtime` itself is slow **when run first**, Deno/runtime or OS process
startup becomes a stronger hypothesis. If `runtime` is fast but `imports`
is slow, examine dependency/module loading, while remembering that imports
comes *second* in runtime-first mode. If both are fast but the full `server`
still starts slowly, focus on later server-side startup operations. An
`imports-first` boot is especially useful if module loading is suspect.

These measurements are observational and involve different system states
across boots. Windows Defender, file-system caching, power-on vs Restart,
Deno cache contents, or other background tasks could matter, but **none are
proven causes** by the current logs. Do not enlarge production timeouts or
change provider priority based only on these diagnostic timings.
