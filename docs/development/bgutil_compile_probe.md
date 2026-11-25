# RR-V 1.6.0 Stage03-P3: isolated Deno compile/bundle experiment

## Goal and scope

The Stage03-P2 Windows cold-boot comparison did **not** establish a meaningful
first-launch improvement from reducing installed development dependencies.
Measured first starts were 36.681 seconds (original A) and 34.750 seconds
(lean B), on different boots. The lean B second start unexpectedly took
23.138 seconds versus 3.335 seconds for original A; the cause is unknown.

This P3 experiment asks two narrower questions:

1. Can Deno 2.9.x **compile the pinned BgUtils 2.0.2 HTTP server** using
   experimental `deno compile --bundle`?
2. Can that executable actually start and answer the pinned version at
   `127.0.0.1:<ephemeral-port>/ping`, without a node_modules working directory?

**A successful compilation is not evidence of native `canvas` compatibility,
PO Token generation or a cold-start improvement.** A successful HTTP `/ping`
is a necessary but incomplete functional gate. Full token issuance requires a
separate, explicitly approved follow-up test.

## Safety and boundary

- Only a **developer experiment**. GPL-3.0-only upstream provider files and
  compiled executables must not be added to the repository, installer, or
  public release. Distribution/compliance remains a separate decision.
- Uses the already separately installed, verified **Stage03-P2 lean provider**:
  `%LOCALAPPDATA%\RR-V\diagnostics\bgutil-stage03-lean-experiment`.
- New compiled output is written only to:
  `%LOCALAPPDATA%\RR-V\diagnostics\bgutil-stage03-compiled-bundled`.
- The existing `%LOCALAPPDATA%\RR-V\bgutil-stage03-external` installation and
  production RR-V launcher are not changed. No Stage03 home environment
  variable is changed by this script.
- `--prepare-bundler` copies the lean Deno cache to
  `%LOCALAPPDATA%\RR-V\diagnostics\bgutil-stage03-p3-cache` and bundles a
  dependency-free TypeScript file so Deno can obtain its esbuild helper there.
  This is the opt-in network step. The original P2 cache is read only.
- `--build` uses the prepared P3 cache and the lean manual node_modules
  layout with `--cached-only` and `--frozen-lockfile`.
- Compilation may be CPU-, disk- and memory-intensive and may fail because
  native addons are not compatible with bundling. Compilation failures are
  expected experimental outcomes, not grounds to change antivirus settings.
- No YouTube access, PO Tokens, WPC, Chrome, video downloads, stored cookies, or
  global Windows startup settings are used.
- On a nonzero compile exit, the build reports Deno's exit code and a fixed
  error category derived from stderr. A dependency cache error also reports
  `cache_ref` with a recognized public package name or public host when known.
  If the compiled server exits before responding, `--probe` reports its exit
  code and a fixed startup error category in `reason`.
  The standard console output contains no raw child output. The explicit
  verbose option below adds a private local report.
- An unknown existing target folder is **never overwritten**. After a failed
  compile, only a new folder created by that attempt is cleaned up.

## Windows first smoke: VS Code terminal

1. In GitHub Desktop, switch to `develop/1.6.0`, `Fetch origin` then
   `Pull origin` if offered. Close RR-V completely, including the system tray.
   Keep Defender and AppCheck enabled. **Do not reboot for this first test.**

2. From the RR-V repository in the VS Code terminal, run:

   ```powershell
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --prepare-bundler
   ```

   Continue when `BGUTIL P3 PREPARE` reports `prepared` or `already-prepared`.
   If preparation fails, send that status line and stop.

3. Build the candidate:

   ```powershell
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --build
   ```

   Expect `BGUTIL P3 BUILD: built | variant=bundled`. If it says
   `already-built`, the existing candidate was hash-verified and reused.
   Any other status means **stop** and send the single safe status line.
   Do not delete the lean or original provider, retry with different flags,
   or disable security software.

4. If the build succeeds, run:

   ```powershell
   .\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --probe
   ```

   Expect a `BGUTIL P3 PROBE: ... | variant=bundled | elapsed_ms=... |
   ping_attempts=...` line. `ready` means the compiled HTTP server responded
   within 18 seconds; `late-ready` means it answered after 18 seconds but
   within the diagnostic's 70-second limit. `compiled-exited-before-ready:code=N`,
   `compiled-timeout`, or `compiled-launch-error` indicate a failed probe.

5. Send the status lines or a screenshot of the whole terminal result.
   No extra log files or ETL trace are required initially.

For an unclassified startup failure, rerun only the probe against the existing
executable:

```powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --probe --verbose
```

`BGUTIL P3 LOG` identifies a new local file under
`%LOCALAPPDATA%\RR-V\diagnostics`. It records launch, first output, HTTP results,
process exit and cleanup, with stdout and stderr in separate sections. Each
stream retains the first 256 KiB and up to 32 KiB of later output, reporting
how many bytes were read and whether intermediate output was omitted.
The report contains raw process output and is not uploaded. Review and redact
private paths, URLs, or credentials before sharing excerpts.

## Unbundled Windows comparison

Once the P3 cache is prepared, run from the RR-V repository:

```powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --compare
```

This compiles a separate `bgutil-stage03-compiled-unbundled` candidate with
the same flags as the bundled build except `--bundle`. After a successful
build it automatically checks loopback `/ping`. An existing verified comparison
binary is reused. The bundled candidate is left in its separate directory.

The `BGUTIL P3 LOG` path identifies a single report containing environment and
version metadata, build output and, when reached, the probe timeline and
startup output. The report masks recognizable credentials and user-home
paths while preserving error messages and module-relative stack frames.

Optional file hash validation (not for timing):

```powershell
.\.venv\Scripts\python.exe .\tests\manual\bgutil_compile_probe.py --verify
```

## Interpreting the result

- This **first smoke is a warm-session compatibility test**, not a direct
  comparison against the earlier Windows cold starts. Building the binary
  will read dependencies and warm caches.
- A compiled executable that answers `/ping` might still depend on files
  outside the executable, or fail when `/get_pot` needs native `canvas`.
  Do **not** remove the source installation or integrate the executable yet.
- If `bundled` fails for native-module reasons, `--variant extracted` exists
  as a *separate, later diagnostic choice*. Its `--self-extracting` mode
  writes dependencies to disk on first run, possibly worsening cold-start
  behavior. **Do not run it until the first result has been reviewed.**
- Only if the compiled server is functionally viable should we consider a
  dedicated cold-boot trial and native/token compatibility gate.
- Even with an excellent result, no public RR-V integration is approved until
  license and distribution questions are resolved.

Deno reference: https://docs.deno.com/runtime/reference/cli/compile/
