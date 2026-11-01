"""Developer-only broad, read-only RR-V BgUtils startup survey.

The first costly Deno probe runs before all optional measurements. Remaining
checks are WARM observations and cannot establish a cold-start root cause.
No tokens, YouTube, provider updates, cache deletion, or Defender changes.
"""
from __future__ import annotations

import argparse
import ctypes
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
from time import perf_counter

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Separate subprocesses; costs here are diagnostic only, never application defaults.
MODULES = (
    ("canvas", "canvas@3.2.3"),
    ("jsdom", "jsdom@29.1.1"),
    ("youtubei", "youtubei.js@18.1.0"),
    ("bgutils-botguard", "bgutils-js@4.0.3/botguard"),
    ("bgutils-webpo", "bgutils-js@4.0.3/webpo"),
    ("express", "express@5.2.1"),
    ("proxy-agent", "proxy-agent@8.0.2"),
    ("axios", "axios@1.20.0"),
)
_ALLOWED = {"graph", "graph-repeat", "runtime", "server", "server-repeat"} | {x[0] for x in MODULES}
_MARKER = "RRV_WIDE_SURVEY_READY_2026"

@dataclass(frozen=True)
class Result:
    stage: str
    status: str
    elapsed_ms: int
    cpu_ms: int = -1
    read_kb: int = -1
    announced_ms: int = 0
    ping_ms: int = 0


def _load_boot():
    script = Path(__file__).with_name("bgutil_boot_sequence_probe.py")
    spec = importlib.util.spec_from_file_location("rrv_wide_boot", script)
    if spec is None or spec.loader is None:
        raise RuntimeError("Boot helper unavailable")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def windows_process_metrics(process) -> tuple[int, int]:
    """Only process CPU and I/O counters, never file names or command lines."""
    if os.name != "nt" or not hasattr(process, "_handle"):
        return -1, -1
    try:
        from ctypes import wintypes
        class FileTime(ctypes.Structure):
            _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
        class IoCounters(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in (
                "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FileTime)] * 4
        k32.GetProcessTimes.restype = wintypes.BOOL
        k32.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoCounters)]
        k32.GetProcessIoCounters.restype = wintypes.BOOL
        created, exited, kernel, user = FileTime(), FileTime(), FileTime(), FileTime()
        io = IoCounters()
        handle = int(process._handle)
        cpu = -1
        reads = -1
        if k32.GetProcessTimes(handle, *(ctypes.byref(x) for x in (created, exited, kernel, user))):
            to_ticks = lambda t: (t.high << 32) | t.low
            cpu = round((to_ticks(kernel) + to_ticks(user)) / 10000)
        if k32.GetProcessIoCounters(handle, ctypes.byref(io)):
            reads = round(io.read_bytes / 1024)
        return cpu, reads
    except (OSError, ValueError, AttributeError, TypeError):
        return -1, -1


def subprocess_probe(stage: str, command: list[str], cwd: Path, env: dict,
                     code: str | None = None, timeout: float = 45,
                     marker: str = _MARKER) -> Result:
    """Run boundedly; capture all untrusted output privately and discard it."""
    start = perf_counter()
    process = None
    try:
        process = subprocess.Popen(
            command, cwd=str(cwd), env=env,
            stdin=subprocess.PIPE if code is not None else subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        stdout, _stderr = process.communicate(input=code, timeout=timeout)
        status = "ok" if process.returncode == 0 and marker in stdout.splitlines() else "failed"
    except subprocess.TimeoutExpired:
        status = "timeout"
        if process is not None:
            process.kill()
            try:
                process.communicate(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
    except (OSError, ValueError):
        status = "launch-error"
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate()
    elapsed = max(0, round((perf_counter() - start) * 1000))
    cpu, read_kb = windows_process_metrics(process) if process is not None else (-1, -1)
    return Result(stage, status, elapsed, cpu, read_kb)


def deno_probe(stage: str, deno: Path, home: Path, boot, timeout=45) -> Result:
    env = boot._deno_env(home)
    cwd = home / "server" / "node_modules"
    if stage == "runtime":
        return subprocess_probe(stage, [str(deno), "eval", f'console.log("{_MARKER}")'],
                                cwd, env, timeout=8)
    flags = [str(deno), "run", "--cached-only", "--allow-env", "--allow-ffi=.",
             "--allow-read=.", "--allow-net", "-"]
    if stage in ("graph", "graph-repeat"):
        # Same cached-only import graph and permissions used by the proven probe.
        code = boot._module_stdin(home) + f'console.log("{_MARKER}");\n'
    else:
        match = dict(MODULES).get(stage)
        if match is None:
            raise ValueError("invalid dependency stage")
        # npm specifiers are strictly hardcoded and do not contain user paths.
        code = f'await import("npm:{match}"); console.log("{_MARKER}");\n'
    return subprocess_probe(stage, flags, cwd, env, code, timeout)


def passive_system() -> dict[str, str | int]:
    """Only coarse health indicators; no machine ID, user paths, or filenames."""
    data: dict[str, str | int] = {
        "os": "windows" if os.name == "nt" else "other",
        "uptime_min": -1, "free_memory_pct": -1, "drive": "unknown",
        "free_disk_gb": -1, "proxy": "present" if any(
            os.environ.get(x) for x in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy")) else "absent",
    }
    if os.name == "nt":
        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetTickCount64.restype = ctypes.c_ulonglong
            data["uptime_min"] = round(kernel.GetTickCount64() / 60000)
            class MemoryStatus(ctypes.Structure):
                _fields_ = [("length", ctypes.c_ulong), ("memory_load", ctypes.c_ulong),
                            ("total_phys", ctypes.c_ulonglong), ("avail_phys", ctypes.c_ulonglong),
                            ("total_page", ctypes.c_ulonglong), ("avail_page", ctypes.c_ulonglong),
                            ("total_virtual", ctypes.c_ulonglong), ("avail_virtual", ctypes.c_ulonglong),
                            ("avail_extended", ctypes.c_ulonglong)]
            memory = MemoryStatus()
            memory.length = ctypes.sizeof(MemoryStatus)
            if kernel.GlobalMemoryStatusEx(ctypes.byref(memory)):
                data["free_memory_pct"] = 100 - int(memory.memory_load)
        except (OSError, AttributeError):
            pass
    return data


def storage_snapshot(home: Path) -> dict[str, str | int]:
    """Measure small reads only, AFTER cold Deno stage has completed."""
    entries = (
        home / "server" / "src" / "main.ts",
        home / "server" / "src" / "session_manager.ts",
        home / "server" / "package.json",
    )
    opened = 0
    started = perf_counter()
    for path in entries:
        try:
            with path.open("rb") as handle:
                handle.read(512 * 1024)
            opened += 1
        except OSError:
            pass
    elapsed = max(0, round((perf_counter() - started) * 1000))
    data: dict[str, str | int] = {"sample_read_ms": elapsed, "sampled_files": opened,
                                   "node_modules": "present" if (home / "server" / "node_modules").is_dir() else "missing",
                                   "deno_cache": "present" if (home / "deno-cache").is_dir() else "missing"}
    try:
        import shutil
        data["free_disk_gb"] = round(shutil.disk_usage(home).free / (1024 ** 3))
    except (OSError, AttributeError):
        data["free_disk_gb"] = -1
    data["reparse_path"] = "present" if home.is_symlink() or (home / "server").is_symlink() else "absent"
    if os.name == "nt":
        try:
            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.GetDriveTypeW.argtypes = [ctypes.c_wchar_p]
            kernel.GetDriveTypeW.restype = ctypes.c_uint
            kind = kernel.GetDriveTypeW(str(home.anchor))
            data["drive"] = {2: "removable", 3: "fixed", 4: "network", 5: "optical", 6: "ram"}.get(kind, "unknown")
        except (OSError, AttributeError):
            data["drive"] = "unknown"
    return data


def mark_of_web(deno: Path) -> str:
    """Read only Windows MOTW stream presence, never record stream contents."""
    if os.name != "nt":
        return "not-windows"
    try:
        with open(str(deno) + ":Zone.Identifier", "rb") as stream:
            return "present" if stream.read(1) else "empty"
    except FileNotFoundError:
        return "absent"
    except OSError:
        return "unknown"


def defender_snapshot(timeout=8) -> str:
    """Read-only Windows Defender status, strictly one of four safe labels."""
    if os.name != "nt":
        return "not-windows"
    cmd = ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
           "try { $s = Get-MpComputerStatus -ErrorAction Stop; "
           "if ($s.RealTimeProtectionEnabled) {'enabled'} else {'disabled'} } "
           "catch {'unavailable'}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace",
                           timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        value = r.stdout.strip().lower()
        return value if value in ("enabled", "disabled", "unavailable") else "unavailable"
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable"


def summarize(rows: list[Result], sysinfo: dict, storage: dict, defender: str) -> list[str]:
    """Evidence flags only, never causal diagnoses."""
    by_name = {r.stage: r for r in rows}
    signals = []
    a, b = by_name.get("graph"), by_name.get("graph-repeat")
    if a and b and a.status == b.status == "ok" and a.elapsed_ms >= 10000 and a.elapsed_ms >= 3 * max(1, b.elapsed_ms):
        signals.append("cold-graph-penalty-observed")
    if a and a.cpu_ms >= 0 and a.elapsed_ms >= 10000:
        share = a.cpu_ms / max(1, a.elapsed_ms)
        if share < .15:
            signals.append("cold-process-low-cpu-time")
        elif share > .60:
            signals.append("cold-process-high-cpu-time")
    for item in rows:
        if item.stage in dict(MODULES) and item.elapsed_ms > 10000:
            signals.append("warm-module-outlier:" + item.stage)
    for item in rows:
        if item.stage in ("server", "server-repeat") and item.status == "late-ready":
            signals.append("server-exceeds-production-budget")
    if storage.get("drive") in ("network", "removable"):
        signals.append("nonlocal-or-removable-installation")
    if isinstance(sysinfo.get("free_memory_pct"), int) and 0 <= sysinfo["free_memory_pct"] < 10:
        signals.append("low-memory-at-start")
    if isinstance(storage.get("free_disk_gb"), int) and 0 <= storage["free_disk_gb"] < 2:
        signals.append("low-disk-space")
    if any(r.status not in ("ok", "ready", "late-ready") for r in rows):
        signals.append("one-or-more-diagnostic-stages-failed")
    return signals or ["no-specific-signal-in-this-run"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", choices=("graph", "server"), default="graph",
                        help="first costly probe before the machine's cache gets warmed")
    args = parser.parse_args(argv)
    from app.paths import find_executable
    from services import bgutil_http_service as service

    raw_home = os.environ.get(service.ENV_HOME, "").strip()
    if not raw_home:
        print("WIDE SURVEY: NOT RUN (developer opt-in missing)")
        return 2
    home = Path(raw_home).expanduser()
    deno = find_executable("deno.exe")
    if deno is None or not service._validate_external_home(home):
        print("WIDE SURVEY: NOT RUN (Deno or external installation unavailable)")
        return 2
    boot = _load_boot()
    initial = passive_system()
    print("RR-V 1.6.0 wide startup survey (no downloads or system changes)")
    print(f"Boot uptime before cold probe: {initial['uptime_min']} min; mode={args.first}")
    print("The FIRST costly stage is cold; all subsequent checks may be warm.")
    order = (("server", "graph", "graph-repeat", "runtime")
             if args.first == "server" else ("graph", "graph-repeat", "runtime", "server"))
    order += ("server-repeat",) + tuple(k for k, _ in MODULES)
    rows = []
    for stage in order:
        print(f"Checking {stage}...", flush=True)
        try:
            if stage.startswith("server"):
                output = boot.run_server_stage(service, home, deno, stage, deadline=50)
                row = Result(stage, output.result, output.elapsed_ms,
                             announced_ms=output.announced_ms, ping_ms=output.ping_ms)
            else:
                row = deno_probe(stage, deno, home, boot,
                                 timeout=50 if stage == "graph" else 18)
        except Exception:
            row = Result(stage, "probe-error", 0)
        rows.append(row)
        cpu = "unknown" if row.cpu_ms < 0 else str(row.cpu_ms)
        read = "unknown" if row.read_kb < 0 else str(row.read_kb)
        print(f"  {row.status}: {row.elapsed_ms} ms (CPU={cpu} ms, process-read={read} KiB)")
    storage = storage_snapshot(home)
    av = defender_snapshot()
    motw = mark_of_web(deno)
    print(f"System: drive={storage['drive']}, cache={storage['deno_cache']}, "
          f"modules={storage['node_modules']}, file-sample={storage['sample_read_ms']} ms, "
          f"free-disk={storage['free_disk_gb']} GB, free-memory={initial['free_memory_pct']}%, "
          f"proxy={initial['proxy']}, defender={av}, deno-motw={motw}")
    signals = summarize(rows, initial, storage, av)
    print("Evidence flags: " + ", ".join(signals))
    print("Results are observations, not proof of the underlying cause.")
    # Persist fixed, allowlisted fields only through RR-V's established writer.
    from app.bgutil_diagnostics import record_bgutil_diagnostic
    for row in rows:
        record_bgutil_diagnostic("bgutil.wide-survey", pid=os.getpid(),
            phase=row.stage, result=row.status, startup_ms=row.elapsed_ms,
            cpu_ms=row.cpu_ms if row.cpu_ms >= 0 else "unavailable",
            read_kb=row.read_kb if row.read_kb >= 0 else "unavailable",
            announced_ms=row.announced_ms, ping_ms=row.ping_ms)
    record_bgutil_diagnostic("bgutil.wide-context", pid=os.getpid(),
        uptime_min=initial["uptime_min"] if initial["uptime_min"] >= 0 else "unavailable",
        free_memory_pct=initial["free_memory_pct"] if initial["free_memory_pct"] >= 0 else "unavailable",
        free_disk_gb=storage["free_disk_gb"] if storage["free_disk_gb"] >= 0 else "unavailable",
        drive_type=storage["drive"], proxy_flag=initial["proxy"],
        defender_flag=av, motw_flag=motw,
        cache_state=storage["deno_cache"], modules_state=storage["node_modules"],
        reparse_flag=storage["reparse_path"], sample_read_ms=storage["sample_read_ms"])
    if any("failed" in s or "error" in s or "timeout" in s for s in (r.status for r in rows)):
        print("WIDE SURVEY: NEEDS REVIEW")
        return 1
    print("WIDE SURVEY: COMPLETE (no production configuration changed)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
