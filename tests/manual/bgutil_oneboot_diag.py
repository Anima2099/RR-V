"""Opt-in, developer-only one-boot BgUtils/Windows performance investigation.

Two phases: --preflight (BEFORE reboot), then --capture (AFTER reboot).
WPR ETL can contain private data: stays only in a local diagnostic folder.
No changes to RR-V's production server or Windows security settings.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import ctypes
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Do not add other subprocess-heavy work before the first BgUtils start.
COLD_DEADLINE = 70.0
POLL = 1.0
MIN_FREE_BYTES = 3 * (1024 ** 3)
PREFLIGHT_VALID_DAYS = 7
PREFLIGHT_MANIFEST_VERSION = 2
PREFLIGHT_OVERALL_TIMEOUT = 175.0
PREFLIGHT_PROFILE_TIMEOUT = 20.0
PREFLIGHT_STATUS_TIMEOUT = 10.0
PREFLIGHT_START_TIMEOUT = 25.0
PREFLIGHT_STOP_TIMEOUT = 90.0
PREFLIGHT_CANCEL_TIMEOUT = 25.0
WPR_POLL_INTERVAL = 5.0
PROFILES_CORE = ("CPU", "DiskIO", "FileIO")
PROFILES_OPTIONAL = ("Registry", "Network", "Minifilter")
ALLOWED_PROFILES = frozenset(PROFILES_CORE + PROFILES_OPTIONAL)
SUMMARY_VERSION = 1
_SESSION = "bgutil-oneboot"


def load_module(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    if not spec or not spec.loader:
        raise RuntimeError("diagnostic helper unavailable")
    result = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = result
    spec.loader.exec_module(result)
    return result


def diagnostic_home() -> Path:
    parent = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
    return parent / "RR-V" / "diagnostics" / _SESSION


def elevated() -> bool:
    if os.name != "nt":
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (OSError, AttributeError, ValueError):
        return False


def _progress(stage: str, message: str) -> None:
    """Only fixed WPR phase names and safe timings, never command output."""
    print(f"[WPR {stage}] {message}", flush=True)


def _kill_private_child(process) -> None:
    """Terminate only the subprocess we launched and its descendants.

    WPR recording sessions are NOT the same as wpr.exe process trees.
    Never run `wpr -cancel` here: recording ownership is handled separately.
    """
    if process.poll() is None and os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=5,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        pass


def run_private(command: list[str], timeout: float = 30.0,
                *, stage: str | None = None, **options):
    """Run WPR with visible bounded progress and temporary file-backed output.

    A descendant can inherit PIPE handles and make subprocess.run/communicate
    wait after wpr.exe exits. An unnamed temporary file avoids that specific
    deadlock and is closed/deleted immediately. Its contents are NEVER logged.
    A stuck direct child and its descendants are terminated at the deadline.
    """
    started = perf_counter()
    with tempfile.TemporaryFile(mode="w+b") as capture:
        process = subprocess.Popen(
            command, stdin=subprocess.DEVNULL, stdout=capture,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            **options,
        )
        try:
            while True:
                elapsed = perf_counter() - started
                remaining = timeout - elapsed
                if remaining <= 0:
                    raise subprocess.TimeoutExpired("private-WPR-step", timeout)
                try:
                    returncode = process.wait(timeout=min(WPR_POLL_INTERVAL, remaining))
                    break
                except subprocess.TimeoutExpired:
                    if stage:
                        _progress(stage, f"still running ({round(perf_counter()-started,1)}s / {max(1,round(timeout))}s limit)")
        except BaseException:
            _kill_private_child(process)
            raise
        capture.seek(0)
        raw = capture.read(256 * 1024)
        # Profile names and status phrases are ASCII. Never print raw output.
        if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
            decoded = raw.decode("utf-16", errors="replace")
        else:
            decoded = raw.decode("utf-8", errors="replace")
        return subprocess.CompletedProcess(command, returncode, decoded, "")


def _wpr_status_category(output: str) -> str:
    """Be strict: unknown/localized WPR output must never imply ownership."""
    if re.search(r"\b(?:not recording|no trace profiles running|no recording in progress)\b", output, re.I):
        return "idle"
    if re.search(r"\brecording(?: is)? in progress\b", output, re.I):
        return "active"
    return "unknown"


def fixed_profile_names(raw: str) -> tuple[str, ...]:
    # The WPR command has localized descriptions but invariant profile names.
    # Dry-run start/cancel, not this parsing alone, establishes availability.
    found = []
    for name in PROFILES_CORE + PROFILES_OPTIONAL:
        if re.search(r"(?<![A-Za-z0-9])" + re.escape(name) + r"(?![A-Za-z0-9])", raw, re.I):
            found.append(name)
    return tuple(found)


def wpr_command(profiles: tuple[str, ...]) -> list[str]:
    if not profiles or any(profile not in ALLOWED_PROFILES for profile in profiles):
        raise ValueError("invalid WPR profile")
    return [part for profile in profiles for part in ("-start", profile)]


@dataclass(frozen=True)
class Preflight:
    ok: bool
    reason: str
    profiles: tuple[str, ...] = ()
    admin: bool = False
    disk_gb: int = -1
    wpa_available: bool = False


def preflight(probe_wpr: str | None, *, admin: bool, free_bytes: int,
              wpa_available: bool, check_tools=True) -> Preflight:
    """Bounded, visible WPR preflight with strict recording ownership rules."""
    free_gb = max(0, int(free_bytes // (1024 ** 3)))
    if os.name != "nt" and check_tools:
        return Preflight(False, "windows-required")
    if not admin:
        return Preflight(False, "administrator-rights-required", admin=False, disk_gb=free_gb)
    if free_bytes < MIN_FREE_BYTES:
        return Preflight(False, "insufficient-disk-space", admin=True, disk_gb=free_gb)
    if not probe_wpr:
        return Preflight(False, "wpr-unavailable", admin=True, disk_gb=free_gb)

    begun = perf_counter()
    def failure(reason: str) -> Preflight:
        _progress("RESULT", "not ready: " + reason)
        return Preflight(False, reason, admin=True, disk_gb=free_gb)

    def step(stage: str, args: list[str], ceiling: float):
        remaining = PREFLIGHT_OVERALL_TIMEOUT - (perf_counter() - begun)
        if remaining <= 0:
            raise subprocess.TimeoutExpired("preflight-overall-budget", PREFLIGHT_OVERALL_TIMEOUT)
        limit = min(ceiling, remaining)
        _progress(stage, f"starting (max {round(limit)}s)")
        started = perf_counter()
        try:
            result = run_private([probe_wpr, *args], timeout=limit, stage=stage)
        except subprocess.TimeoutExpired:
            _progress(stage, "TIMEOUT; launched WPR command terminated; recording state not assumed")
            raise
        except OSError:
            _progress(stage, "WPR command could not run")
            raise
        _progress(stage, f"finished in {round(perf_counter()-started,1)}s (exit={result.returncode})")
        return result

    def check_status(stage: str) -> str:
        result = step(stage, ["-status"], PREFLIGHT_STATUS_TIMEOUT)
        return _wpr_status_category(result.stdout)

    try:
        # Do NOT disrupt a WPR recording that was started by someone else.
        if check_status("1/5 status-before") != "idle":
            return failure("wpr-existing-or-unverified-session-do-not-cancel")

        discovered = step("2/5 profile-list", ["-profiles"], PREFLIGHT_PROFILE_TIMEOUT)
        if discovered.returncode != 0:
            return failure("wpr-profiles-unavailable")
        available = fixed_profile_names(discovered.stdout)
        if not all(name in available for name in PROFILES_CORE):
            return failure("wpr-required-profiles-missing")
        picked = tuple(name for name in PROFILES_CORE + PROFILES_OPTIONAL if name in available)
        _progress("profiles", "candidate profiles: " + ", ".join(picked))

        try:
            started = step("3/5 test-start", wpr_command(picked), PREFLIGHT_START_TIMEOUT)
        except subprocess.TimeoutExpired:
            # A timed-out start may nevertheless have created an active trace.
            # We cannot safely establish ownership, so NEVER auto-cancel here.
            return failure("wpr-start-timeout-ownership-uncertain-check-status")
        if started.returncode != 0:
            # Some profile combinations are incompatible. Only try the core
            # profiles if the failed start left WPR demonstrably IDLE.
            if picked != PROFILES_CORE and check_status("3/5 fallback-status") == "idle":
                _progress("profiles", "optional combination failed; trying core profiles only")
                picked = PROFILES_CORE
                try:
                    started = step("3/5 core-retry", wpr_command(picked), PREFLIGHT_START_TIMEOUT)
                except subprocess.TimeoutExpired:
                    return failure("wpr-core-start-timeout-ownership-uncertain-check-status")
            if started.returncode != 0:
                return failure("wpr-start-failed-check-existing-session")

        # This successful -start return is the sole basis for trace ownership.
        # If STOP fails, only cancel the trace started by THIS preflight.
        saved_ok = False
        try:
            with tempfile.TemporaryDirectory(prefix="rrv-wpr-preflight-") as temp:
                target = Path(temp) / "temporary-private.etl"
                try:
                    saved = step("4/5 test-stop-save", ["-stop", str(target), "-skipPdbGen"],
                                 PREFLIGHT_STOP_TIMEOUT)
                    saved_ok = saved.returncode == 0 and target.is_file() and target.stat().st_size > 0
                except (OSError, subprocess.TimeoutExpired):
                    _progress("4/5 test-stop-save", "save did not complete; investigating owned trace state")
        except OSError:
            _progress("4/5 test-stop-save", "temporary trace storage failed")

        if not saved_ok:
            # Only cancel if status still says it is recording AND our -start
            # was confirmed successful. Otherwise fail closed without cancel.
            try:
                if check_status("4/5 cleanup-status") == "active":
                    cancelled = step("4/5 cancel-owned", ["-cancel"], PREFLIGHT_CANCEL_TIMEOUT)
                    if cancelled.returncode != 0 or check_status("4/5 post-cancel-status") != "idle":
                        return failure("wpr-owned-trace-cleanup-unconfirmed")
                else:
                    _progress("4/5 cleanup", "no verified active owned trace; not cancelling")
            except (OSError, subprocess.TimeoutExpired):
                return failure("wpr-owned-trace-cleanup-unconfirmed-check-status")
            return failure("wpr-stop-save-not-verified")

        if check_status("5/5 status-after") != "idle":
            return failure("wpr-stop-status-unverified-check-status")
        _progress("RESULT", "all checks passed")
        return Preflight(True, "ready", picked, True, free_gb, wpa_available)
    except subprocess.TimeoutExpired:
        return failure("wpr-command-timeout-or-global-budget-check-status")
    except KeyboardInterrupt:
        # Ctrl+C stops this preflight without touching sessions we cannot
        # prove we own. A prior successful start may need manual inspection.
        return failure("interrupted-check-wpr-status-do-not-reboot")
    except OSError:
        return failure("wpr-command-failed-check-status")


def save_preflight(result: Preflight, folder: Path) -> None:
    if not result.ok:
        return
    folder.mkdir(parents=True, exist_ok=True)
    payload = {"version": PREFLIGHT_MANIFEST_VERSION, "created_utc": datetime.now(timezone.utc).timestamp(),
               "profiles": list(result.profiles), "ready": True}
    (folder / "preflight.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")


def read_preflight(folder: Path, now: float | None = None) -> tuple[str, ...]:
    try:
        payload = json.loads((folder / "preflight.json").read_text(encoding="utf-8"))
        timestamp = payload["created_utc"]
        profiles = payload["profiles"]
        current = datetime.now(timezone.utc).timestamp() if now is None else now
        if (payload.get("version") != PREFLIGHT_MANIFEST_VERSION or payload.get("ready") is not True
                or type(timestamp) not in (int, float) or not 0 <= current-timestamp <= PREFLIGHT_VALID_DAYS*86400
                or not isinstance(profiles, list) or not all(type(p) is str for p in profiles)
                or not all(p in profiles for p in PROFILES_CORE)
                or len(set(profiles)) != len(profiles)
                or any(p not in ALLOWED_PROFILES for p in profiles)):
            return ()
        return tuple(profiles)
    except (OSError, ValueError, TypeError, KeyError):
        return ()


class WprRecording:
    """Own only sessions whose -start command returned success."""
    def __init__(self, executable: str, profiles: tuple[str, ...]):
        self.executable, self.profiles = executable, profiles
        self.owned = False
        self.status = "not-started"

    def start(self) -> str:
        try:
            result = run_private([self.executable, *wpr_command(self.profiles)], timeout=30,
                                 stage="capture-start")
            self.owned = result.returncode == 0
            self.status = "recording" if self.owned else "start-failed"
        except (OSError, subprocess.TimeoutExpired):
            self.status = "start-unconfirmed"
        return self.status

    def marker(self, marker: str):
        if self.owned and marker in ("RRV_COLD_BEGIN", "RRV_COLD_END"):
            try:
                run_private([self.executable, "-marker", marker], timeout=12,
                            stage="capture-marker")
            except (OSError, subprocess.TimeoutExpired):
                pass

    def stop(self, etl_path: Path) -> str:
        if not self.owned:
            return self.status
        try:
            result = run_private([self.executable, "-stop", str(etl_path), "-skipPdbGen"],
                                 timeout=240, stage="capture-stop-save")
            self.status = "saved" if result.returncode == 0 and etl_path.is_file() else "stop-failed"
        except (OSError, subprocess.TimeoutExpired):
            self.status = "stop-unconfirmed"
        if self.status != "saved":
            self.cancel()
        self.owned = False
        return self.status

    def cancel(self):
        if not self.owned:
            return
        try:
            run_private([self.executable, "-cancel"], timeout=40,
                            stage="capture-cancel-owned")
        except (OSError, subprocess.TimeoutExpired):
            self.status = "cancel-unconfirmed"
        finally:
            self.owned = False


def record_server(service, home: Path, deno: Path, trace, observe,
                  name: str, deadline: float = COLD_DEADLINE, interval: float = POLL):
    """Use exact production launcher through trace.run_once, sample its child.

    Only the background *diagnostic* thread patches Popen; no other process
    starts while this scoped patch is active. Tracing can add some overhead.
    """
    thread_ready = threading.Event()
    state = {}
    original = subprocess.Popen
    started = perf_counter()

    def intercept(*args, **kwargs):
        process = original(*args, **kwargs)
        state["process"] = process
        thread_ready.set()
        return process

    def worker():
        try:
            with patch.object(service.subprocess, "Popen", intercept):
                state["trace"] = trace.run_once(service, home, deno, attempt=1 if name.endswith("cold") else 2,
                                                deadline=deadline)
        except Exception:
            state["error"] = True
        finally:
            thread_ready.set()

    thread = threading.Thread(target=worker, name="RRV-Oneboot-server-worker", daemon=True)
    thread.start()
    while not thread_ready.wait(timeout=.15):
        if not thread.is_alive() or perf_counter()-started > deadline + 10:
            break
    process = state.get("process")
    samples = []
    if process is not None:
        counters = observe.WindowsCounters()
        samples.append(counters.read(process, round((perf_counter()-started)*1000)))
        while thread.is_alive() and perf_counter()-started <= deadline+10:
            thread.join(timeout=interval)
            samples.append(counters.read(process, round((perf_counter()-started)*1000)))
    else:
        thread.join(timeout=3)
    if thread.is_alive():
        if process is not None:
            try:
                process.kill()
            except OSError:
                pass
        thread.join(timeout=5)
    elapsed = max(0, round((perf_counter()-started)*1000))
    outcome = state.get("trace")
    if thread.is_alive():
        status = "timeout"
    elif outcome is None:
        status = "probe-error"
    else:
        status = "ok" if outcome.result == "ready" else outcome.result
    phase = observe.Phase(name, status, elapsed, tuple(samples))
    milestones = {"startup_ms": outcome.startup_ms if outcome else 0,
                  "first_output_ms": outcome.first_output_ms if outcome else 0,
                  "announced_ms": outcome.announced_ms if outcome else 0,
                  "tcp_ms": outcome.tcp_ms if outcome else 0,
                  "ping_ms": outcome.ping_ms if outcome else 0,
                  "ping_attempts": outcome.ping_attempts if outcome else 0}
    return phase, milestones


def to_safe_phase(phase, observe, milestones=None) -> dict:
    d = {"status": phase.result, "elapsed_ms": phase.elapsed_ms,
         "signals": observe.classification(phase),
         "windows": observe.buckets(phase)}
    if milestones is not None:
        d["milestones"] = milestones
    return d


def evidence(cold: dict, warm: dict, extra: dict) -> list[str]:
    """Prioritize findings without pretending to assign an unproven culprit."""
    flags = list(cold.get("signals", ()))
    a, b = cold.get("elapsed_ms", 0), warm.get("elapsed_ms", 0)
    if a > 12000 and b > 0 and a >= 3*b:
        flags.append("reproducible-cold-vs-warm-gap-in-this-boot")
    if a > 18000:
        flags.append("would-exceed-production-first-use-budget")
    if cold.get("milestones", {}).get("ping_ms", 0) and cold.get("milestones", {}).get("announced_ms", 0):
        if cold["milestones"]["ping_ms"] - cold["milestones"]["announced_ms"] < 1500:
            flags.append("server-responds-quickly-after-announcement")
    if extra.get("defender_status") == "enabled":
        flags.append("defender-enabled-not-proof-of-scan-delay")
    if any(x.get("status") not in ("ok", "ready", "late-ready") for x in extra.get("modules", [])):
        flags.append("optional-module-check-failed-not-proof-of-server-failure")
    return sorted(set(flags))


def run_followup(home: Path, deno: Path, observe, boot, wide, service) -> dict:
    # All of these deliberately run AFTER WPR's cold-first capture.
    tests = []
    for stage in ("imports", "runtime"):
        try:
            r = boot.run_deno_stage(stage, deno, home)
            tests.append({"stage": stage, "status": r.result, "elapsed_ms": r.elapsed_ms})
        except Exception:
            tests.append({"stage": stage, "status": "probe-error", "elapsed_ms": 0})
    modules = []
    for stage, _spec in wide.MODULES:
        try:
            r = wide.deno_probe(stage, deno, home, boot, timeout=18)
            modules.append({"stage": stage, "status": r.status, "elapsed_ms": r.elapsed_ms})
        except Exception:
            modules.append({"stage": stage, "status": "probe-error", "elapsed_ms": 0})
    try:
        sysinfo = wide.passive_system()
        storage = wide.storage_snapshot(home)
        defender = wide.defender_snapshot(timeout=8)
        motw = wide.mark_of_web(deno)
    except Exception:
        sysinfo, storage, defender, motw = {}, {}, "unavailable", "unknown"
    # Whitelist ONLY already privacy-safe coarse values.
    keep_sys = ("uptime_min", "free_memory_pct", "proxy")
    keep_storage = ("drive", "free_disk_gb", "sample_read_ms", "node_modules", "deno_cache", "reparse_path")
    return {"baseline": tests, "modules": modules,
            "system": {k: sysinfo.get(k, "unknown") for k in keep_sys},
            "storage": {k: storage.get(k, "unknown") for k in keep_storage},
            "defender_status": defender, "deno_motw": motw}


def validate_home_and_deno():
    from app.paths import find_executable
    from services import bgutil_http_service as service
    raw = os.environ.get(service.ENV_HOME, "").strip()
    if not raw:
        return None, None, None, "dev-mode-not-enabled"
    home = Path(raw).expanduser()
    deno = find_executable("deno.exe")
    if deno is None:
        return None, None, None, "deno-not-found"
    try:
        if not service._validate_external_home(home):
            return None, None, None, "external-provider-invalid"
    except Exception:
        return None, None, None, "external-provider-check-failed"
    return service, home, deno, "ready"


def run_preflight():
    _progress("START", "preflight begins; all stages will report progress")
    _progress("START", "maximum combined WPR wait budget: " + str(round(PREFLIGHT_OVERALL_TIMEOUT)) + "s")
    service, home, deno, valid = validate_home_and_deno()
    if valid != "ready":
        print("PREFLIGHT: BLOCKED (" + valid + ")")
        return 2
    folder = diagnostic_home()
    try:
        free = shutil.disk_usage(folder.parent if folder.parent.exists() else home).free
    except OSError:
        free = 0
    wpr = shutil.which("wpr.exe") or shutil.which("wpr")
    report = preflight(wpr, admin=elevated(), free_bytes=free,
                       wpa_available=bool(shutil.which("wpa.exe")))
    print("One-boot WPR preflight (no Deno server or BgUtils token requests)")
    print("Administrator:", "yes" if report.admin else "NO")
    print("Free disk space:", report.disk_gb, "GiB")
    print("WPA analyzer installed:", "yes" if report.wpa_available else "no")
    print("WPR recording profiles:", ", ".join(report.profiles) if report.profiles else "unavailable")
    print("Preflight result:", report.reason)
    if not report.ok:
        # An older preflight marker must not allow capture after a failed check.
        try:
            (folder / "preflight.json").unlink(missing_ok=True)
        except OSError:
            _progress("RESULT", "could not invalidate old marker; do NOT capture")
    if report.ok:
        save_preflight(report, folder)
        print("PREFLIGHT: READY. Next normal power-on may run --capture once.")
        return 0
    print("PREFLIGHT: NOT READY. Do NOT reboot just for this experiment.")
    print("If WPR failed, check `wpr -status`; never cancel another recording.")
    return 2


def run_capture():
    # All blocking checks happen BEFORE the first Deno server launch.
    if os.name != "nt":
        print("ONEBOOT: NOT RUN (Windows-only capture)")
        return 2
    profiles = read_preflight(diagnostic_home())
    if not profiles:
        print("ONEBOOT: NOT RUN. Run --preflight successfully BEFORE reboot.")
        return 2
    if not elevated():
        print("ONEBOOT: NOT RUN. Administrator PowerShell is required.")
        return 2
    service, home, deno, valid = validate_home_and_deno()
    if valid != "ready":
        print("ONEBOOT: NOT RUN (" + valid + ")")
        return 2
    wpr = shutil.which("wpr.exe") or shutil.which("wpr")
    if not wpr:
        print("ONEBOOT: NOT RUN (WPR missing)")
        return 2
    try:
        if shutil.disk_usage(home).free < MIN_FREE_BYTES:
            print("ONEBOOT: NOT RUN (not enough local disk space)")
            return 2
    except OSError:
        print("ONEBOOT: NOT RUN (disk-space check failed)")
        return 2

    folder = diagnostic_home() / ("oneboot-" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    folder.mkdir(parents=True, exist_ok=False)
    etl = folder / "PRIVATE-Windows-trace-DO-NOT-SHARE.etl"
    recording = WprRecording(wpr, profiles)
    print("RR-V one-boot diagnostic | Windows trace is PRIVATE and stays on this PC")
    print("ETL includes filenames, processes, and possibly sensitive system activity.")
    print("WPR is memory-buffered and stopped immediately after first server launch.")
    print("First: real BgUtils server startup; then warm controls and module checks.")
    status = recording.start()
    if status != "recording":
        print("ONEBOOT: WPR NOT STARTED (" + status + "). No Deno tests executed.")
        print("Do not cancel WPR sessions owned by another application.")
        return 2
    observe = load_module("rrv_oneboot_observe", "bgutil_windows_observe.py")
    trace = load_module("rrv_oneboot_trace", "bgutil_startup_trace.py")
    boot = load_module("rrv_oneboot_boot", "bgutil_boot_sequence_probe.py")
    wide = load_module("rrv_oneboot_wide", "bgutil_wide_survey.py")
    cold = None
    wpr_status = "recording"
    try:
        recording.marker("RRV_COLD_BEGIN")
        print("Running COLD real-server diagnostic...", flush=True)
        try:
            cold = record_server(service, home, deno, trace, observe, "server-cold")
        except Exception:
            cold = (observe.Phase("server-cold", "probe-error", 0, ()), {})
        recording.marker("RRV_COLD_END")
    finally:
        # Absolutely stop the sensitive system trace before optional checks.
        wpr_status = recording.stop(etl)
    print("WPR trace status:", wpr_status)
    if cold is None:
        print("ONEBOOT: Cold phase failed before metrics were recorded.")
        return 1
    print("Running WARM real-server control...", flush=True)
    warm = record_server(service, home, deno, trace, observe, "server-warm")
    print("Running additional dependency + Windows environment checks...", flush=True)
    followup = run_followup(home, deno, observe, boot, wide, service)
    safe_cold = to_safe_phase(cold[0], observe, cold[1])
    safe_warm = to_safe_phase(warm[0], observe, warm[1])
    flags = evidence(safe_cold, safe_warm, followup)
    try:
        raw_bytes = etl.stat().st_size if wpr_status == "saved" else 0
    except OSError:
        raw_bytes = 0
    summary = {"schema": SUMMARY_VERSION, "privacy": "safe-summary-only-raw-etl-private",
               "wpr": {"status": wpr_status, "profiles": list(profiles),
                       "raw_etl_local_only": True, "etl_megabytes": round(raw_bytes/(1024**2), 1)},
               "cold": safe_cold, "warm": safe_warm, "followup": followup,
               "signals": flags}
    summary_path = folder / "SAFE-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    summary_lines = ["RR-V 1.6.0 one-boot summary (safe to share)",
                     "WPR: " + wpr_status + " | profiles: " + ", ".join(profiles),
                     "WPR ETL contains private activity: DO NOT UPLOAD THE ETL FILE",
                     "Cold real server: " + safe_cold["status"] + " | " + str(safe_cold["elapsed_ms"]) + " ms",
                     "Cold milestones: " + str(safe_cold["milestones"]),
                     "Warm real server: " + safe_warm["status"] + " | " + str(safe_warm["elapsed_ms"]) + " ms",
                     "Cold 5-second Windows counters:"]
    for row in safe_cold["windows"]:
        summary_lines.append("  " + str(row))
    summary_lines.append("Follow-up checks:")
    for row in followup["baseline"] + followup["modules"]:
        summary_lines.append("  " + row["stage"] + ": " + row["status"] + " | " + str(row["elapsed_ms"]) + " ms")
    summary_lines.append("System context: " + str(followup["system"]))
    summary_lines.append("Disk/security context: " + str(followup["storage"]) + ", defender=" + followup["defender_status"])
    summary_lines.append("Evidence signals: " + ", ".join(flags))
    summary_path.with_suffix(".txt").write_text("\n".join(summary_lines) + "\n", encoding="utf-8")
    from app.bgutil_diagnostics import record_bgutil_diagnostic
    record_bgutil_diagnostic("bgutil.oneboot", pid=os.getpid(),
                             status=safe_cold["status"], startup_ms=safe_cold["elapsed_ms"],
                             result=wpr_status, phase="server-cold")
    for line in summary_lines:
        print(line)
    print("SAFE files: under %LOCALAPPDATA%\\RR-V\\diagnostics\\bgutil-oneboot\\oneboot-<timestamp>")
    print("Share SAFE-summary.json and bgutil-stage03.log only; retain ETL locally.")
    if wpr_status != "saved":
        print("ONEBOOT: NEEDS REVIEW (Windows trace was not saved)")
        return 1
    if cold[0].result not in ("ok", "late-ready"):
        print("ONEBOOT: NEEDS REVIEW (cold BgUtils did not become ready)")
        return 1
    print("ONEBOOT: COMPLETE (evidence captured, root cause not yet proven)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preflight", action="store_true", help="check WPR/permissions BEFORE reboot")
    mode.add_argument("--capture", action="store_true", help="consent to local sensitive ETL, then record once")
    args = parser.parse_args(argv)
    return run_preflight() if args.preflight else run_capture()


if __name__ == "__main__":
    raise SystemExit(main())
