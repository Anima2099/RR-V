# RR-V Stage03 P2-1: isolated lean BgUtils preparation experiment

## Purpose and safety

This is a **developer-only test**, not a replacement provider installer. The
pinned upstream BgUtils POT Provider 2.0.2 (GPL-3.0-only) must already be
installed and verified by Stage03. RR-V still uses WPC by default unless the
existing explicit development opt-in is set. Nothing in the normal RR-V launch,
download flow, timeouts, settings, main branch, or deployed installer changes.

Hypothesis: a production-only, entrypoint-focused installation may reduce
unnecessary modules and cold file-access overhead. It does not prove Defender
caused any delay, nor guarantee that first server startup becomes faster.

The test copies the existing verified upstream source, license and plugins
but **not** its node_modules or Deno cache. It then installs a separate
candidate using the existing Deno executable:

    deno install --frozen --prod --node-modules-dir=auto --allow-scripts=npm:canvas --entrypoint src/main.ts

Original source:

    %LOCALAPPDATA%\RR-V\bgutil-stage03-external

Independent test candidate:

    %LOCALAPPDATA%\RR-V\diagnostics\bgutil-stage03-lean-experiment

The candidate is installed at its final path so Windows native module
links do not point at a temporary folder. It has its own DENO_DIR. The
installation may download dependencies and run upstream's approved canvas
installation script. It never edits the original provider, clears caches,
modifies antivirus settings, runs YouTube, or stores raw Deno output.
Failures return a fixed status; no existing candidate is overwritten.
If a cleanup fails, stop and report the status rather than forcibly deleting
the original provider or candidate.

## Windows smoke: VS Code PowerShell

1. In GitHub Desktop select develop/1.6.0, Fetch/Pull. Close RR-V
   completely, including its tray instance. Keep Defender and AppCheck on.
   No reboot is needed for the initial functional check.

2. Prepare the isolated candidate once:

       .\.venv\Scripts\python.exe .\tests\manual\bgutil_lean_prepare.py

   Expected: BGUTIL LEAN: prepared
   A subsequent run may say: BGUTIL LEAN: already-prepared
   Any other status means stop and share the status, without retry loops.

3. Verify the candidate without changing anything:

       .\.venv\Scripts\python.exe .\tests\manual\bgutil_lean_prepare.py --verify

   Expected: BGUTIL LEAN: verified

4. Check that the candidate HTTP server starts, using the **existing**
   sanitized startup diagnostic (no YouTube or token requests):

       $env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\diagnostics\bgutil-stage03-lean-experiment"
       .\.venv\Scripts\python.exe .\tests\manual\bgutil_startup_trace.py --attempts 1

   Report the one-line status and elapsed/first-output/ping values.
   A diagnostic late-ready is NOT ready under the unchanged production
   first-use limit of 12 + 6 seconds. Do not repeatedly retry failures.

5. Restore the normal Stage03 external directory **in this terminal**:

       $env:RRV_BGUTIL_STAGE03_HOME = "$env:LOCALAPPDATA\RR-V\bgutil-stage03-external"

## Interpretation and next gate

- A successful install and startup only verifies server initialization.
  Actual PO Token issuance, WPC fallback, and downloads remain separate gates.
- The first same-session run is **warm-session validation**, not an
  apples-to-apples cold-boot benchmark. Installation itself warms caches.
- If the candidate works, decide whether to measure the existing provider
  and the candidate **first after separate Windows boots** with identical
  trace settings. Never call two sequential launches on one boot both cold.
- Share only the console's safe status fields or the existing
  %APPDATA%\RR-V\logs\bgutil-stage03.log. Never share private ETL traces.
- Native canvas compatibility and GPL-3.0-only distribution compliance
  must be verified before any integration, shipping, or auto-install.
