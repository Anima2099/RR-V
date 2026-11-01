"""Developer-only, privacy-minimal time-series of Windows Deno startup.

No administrator rights, ETW session, antivirus changes, new dependencies, or
raw file-access traces. The first Deno stage is observed before other probes.
Win32 process I/O counters include cached operations: NOT physical-disk reads.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from dataclasses import dataclass
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import threading
from time import perf_counter
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

INTERVAL = 1.0
DEADLINE = 65.0
_MARKER = "RRV_WINDOWS_OBSERVE_OK"


@dataclass(frozen=True)
class Snap:
    elapsed_ms: int
    cpu_ms: int = -1
    read_kb: int = -1
    write_kb: int = -1
    other_ops: int = -1
    faults: int = -1
    memory_mb: int = -1
    handles: int = -1
    threads: int = -1
    system_busy: int = -1


@dataclass(frozen=True)
class Phase:
    name: str
    result: str
    elapsed_ms: int
    snapshots: tuple[Snap, ...]


def _helper(filename: str, name: str):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    if spec is None or spec.loader is None:
        raise RuntimeError("diagnostic-helper-unavailable")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class WindowsCounters:
    """Read fixed Win32 counters only, never process filenames or thread IDs."""

    def __init__(self):
        self.available = os.name == "nt"
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True) if self.available else None
        self.psapi = ctypes.WinDLL("psapi", use_last_error=True) if self.available else None
        self._last_system = None

    @staticmethod
    def _tick(value) -> int:
        return (value.high << 32) | value.low

    def read(self, process, elapsed_ms: int) -> Snap:
        if not self.available or process is None or not hasattr(process, "_handle"):
            return Snap(elapsed_ms)
        try:
            class FileTime(ctypes.Structure):
                _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
            class IoCounters(ctypes.Structure):
                _fields_ = [(key, ctypes.c_ulonglong) for key in (
                    "read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]
            class MemoryCounters(ctypes.Structure):
                _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                    (name, ctypes.c_size_t) for name in (
                        "peak_working", "working", "quota_peak_paged", "quota_paged",
                        "quota_peak_nonpaged", "quota_nonpaged", "pagefile", "peak_pagefile")]
            k = self.kernel
            handle = wintypes.HANDLE(int(process._handle))
            ft = [FileTime() for _ in range(4)]
            k.GetProcessTimes.argtypes = [wintypes.HANDLE] + [ctypes.POINTER(FileTime)] * 4
            k.GetProcessTimes.restype = wintypes.BOOL
            cpu = -1
            if k.GetProcessTimes(handle, *(ctypes.byref(item) for item in ft)):
                cpu = round((self._tick(ft[2]) + self._tick(ft[3])) / 10000)
            io = IoCounters()
            k.GetProcessIoCounters.argtypes = [wintypes.HANDLE, ctypes.POINTER(IoCounters)]
            k.GetProcessIoCounters.restype = wintypes.BOOL
            reads = writes = others = -1
            if k.GetProcessIoCounters(handle, ctypes.byref(io)):
                reads, writes = round(io.read_bytes / 1024), round(io.write_bytes / 1024)
                others = int(io.other_ops)
            mem = MemoryCounters()
            mem.cb = ctypes.sizeof(MemoryCounters)
            self.psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(MemoryCounters), wintypes.DWORD]
            self.psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
            rss = faults = -1
            if self.psapi.GetProcessMemoryInfo(handle, ctypes.byref(mem), mem.cb):
                rss = round(mem.working / (1024 * 1024))
                faults = int(mem.faults)
            count = wintypes.DWORD()
            k.GetProcessHandleCount.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
            k.GetProcessHandleCount.restype = wintypes.BOOL
            handles = count.value if k.GetProcessHandleCount(handle, ctypes.byref(count)) else -1
            threads = self._thread_count(process.pid)
            busy = self._system_busy()
            return Snap(elapsed_ms, cpu, reads, writes, others, faults, rss, handles, threads, busy)
        except (OSError, ValueError, TypeError, AttributeError):
            return Snap(elapsed_ms)

    def _thread_count(self, pid: int) -> int:
        """Toolhelp thread enumeration; no IDs are retained or logged."""
        try:
            class ThreadEntry(ctypes.Structure):
                _fields_ = [("size", wintypes.DWORD), ("usage", wintypes.DWORD),
                            ("thread_id", wintypes.DWORD), ("owner_pid", wintypes.DWORD),
                            ("base_prio", wintypes.LONG), ("delta_prio", wintypes.LONG),
                            ("flags", wintypes.DWORD)]
            k = self.kernel
            k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
            k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
            k.Thread32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
            k.Thread32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(ThreadEntry)]
            k.CloseHandle.argtypes = [wintypes.HANDLE]
            handle = k.CreateToolhelp32Snapshot(0x4, 0)
            if handle in (None, ctypes.c_void_p(-1).value):
                return -1
            count = 0
            try:
                entry = ThreadEntry()
                entry.size = ctypes.sizeof(ThreadEntry)
                success = k.Thread32First(handle, ctypes.byref(entry))
                while success:
                    if entry.owner_pid == pid:
                        count += 1
                    success = k.Thread32Next(handle, ctypes.byref(entry))
            finally:
                k.CloseHandle(handle)
            return count
        except (OSError, ValueError, AttributeError):
            return -1

    def _system_busy(self) -> int:
        try:
            class FileTime(ctypes.Structure):
                _fields_ = [("low", wintypes.DWORD), ("high", wintypes.DWORD)]
            k = self.kernel
            k.GetSystemTimes.argtypes = [ctypes.POINTER(FileTime)] * 3
            k.GetSystemTimes.restype = wintypes.BOOL
            idle, kernel, user = FileTime(), FileTime(), FileTime()
            if not k.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user)):
                return -1
            now = (self._tick(idle), self._tick(kernel), self._tick(user))
            previous, self._last_system = self._last_system, now
            if previous is None:
                return -1
            idle_delta, kernel_delta, user_delta = (max(0, a-b) for a, b in zip(now, previous))
            total = kernel_delta + user_delta
            return min(100, max(0, round((total-idle_delta) * 100 / total))) if total else -1
        except (OSError, ValueError, AttributeError):
            return -1


def sample_task(name: str, spawn, timeout: float = DEADLINE,
                sampler_factory=WindowsCounters, interval: float = INTERVAL) -> Phase:
    """Measure just the new child while another thread drains its output.

    spawn returns (Popen, optional stdin string). Deno output remains local to
    the worker thread and is reduced to a fixed result status only.
    """
    started = perf_counter()
    try:
        process, code = spawn()
    except (OSError, ValueError):
        return Phase(name, "launch-error", 0, ())
    state = {"result": "failed"}
    complete = threading.Event()

    def drain():
        try:
            stdout, _stderr = process.communicate(input=code, timeout=timeout)
            state["result"] = ("ok" if process.returncode == 0
                               and _MARKER in stdout.splitlines() else "failed")
        except subprocess.TimeoutExpired:
            state["result"] = "timeout"
            try:
                process.kill()
                process.communicate(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                pass
        except (OSError, ValueError):
            state["result"] = "process-error"
            try:
                process.kill()
            except OSError:
                pass
        finally:
            complete.set()

    worker = threading.Thread(target=drain, name="RRV-Deno-private-drain", daemon=True)
    worker.start()
    sampler = sampler_factory()
    samples = [sampler.read(process, 0)]
    try:
        while not complete.wait(timeout=interval):
            elapsed = round((perf_counter()-started)*1000)
            samples.append(sampler.read(process, elapsed))
            # Outer bound avoids indefinite waits if the subprocess API stalls.
            if elapsed > (timeout + 6) * 1000:
                try:
                    process.kill()
                except OSError:
                    pass
                state["result"] = "timeout"
                break
    except BaseException:
        # Ctrl+C should not strand a diagnostic Deno child process.
        try:
            process.kill()
        except OSError:
            pass
        worker.join(timeout=3)
        raise
    worker.join(timeout=4)
    elapsed = max(0, round((perf_counter()-started)*1000))
    if worker.is_alive():
        return Phase(name, "timeout", elapsed, tuple(samples))
    samples.append(sampler.read(process, elapsed))
    return Phase(name, state["result"], elapsed, tuple(samples))


def buckets(phase: Phase, width_ms: int = 5000) -> list[dict[str, int]]:
    """Five-second bins: child process deltas and peak system pressure.

    First/last measurement of each bin is used; unknown counters are -1.
    Process I/O includes cached bytes and is not physical disk throughput.
    """
    samples = phase.snapshots
    if not samples:
        return []
    rows = []
    for index in range((phase.elapsed_ms // width_ms) + 1):
        low = index * width_ms
        high = min((index+1)*width_ms, phase.elapsed_ms)
        # Include nearest earlier baseline to avoid hiding boundary activity.
        earlier = [x for x in samples if x.elapsed_ms <= low]
        later = [x for x in samples if low < x.elapsed_ms <= high]
        if not later and not (index == 0 and phase.elapsed_ms == 0):
            continue
        start = earlier[-1] if earlier else samples[0]
        end = later[-1] if later else samples[-1]
        def diff(name):
            a, b = getattr(start, name), getattr(end, name)
            return max(0, b-a) if a >= 0 and b >= 0 else -1
        system = max((x.system_busy for x in later if x.system_busy >= 0), default=-1)
        rows.append({"start_s": low//1000, "end_s": (high+999)//1000,
                     "cpu_ms": diff("cpu_ms"), "read_kb": diff("read_kb"),
                     "write_kb": diff("write_kb"), "other_ops": diff("other_ops"),
                     "faults": diff("faults"), "peak_system_busy": system,
                     "memory_mb": end.memory_mb, "threads": end.threads,
                     "handles": end.handles})
    return rows


def classification(phase: Phase) -> list[str]:
    """No causal claims: only measured patterns for follow-up investigation."""
    if phase.result not in ("ok", "late-ready"):
        return ["cold-probe-not-successful"]
    base = ["would-fallback-in-production"] if phase.result == "late-ready" else []
    if phase.elapsed_ms < 10000:
        return base + ["no-long-delay-observed"]
    samples = phase.snapshots
    first, last = samples[0], samples[-1]
    result = base + ["long-startup-observed"]
    if first.cpu_ms >= 0 and last.cpu_ms >= 0:
        share = (last.cpu_ms-first.cpu_ms) / max(1, phase.elapsed_ms)
        if share < .20:
            result.append("low-cpu-relative-to-wall")
        elif share > .7:
            result.append("high-cpu-relative-to-wall")
    if first.faults >= 0 and last.faults >= 0 and last.faults-first.faults >= 10000:
        result.append("many-process-page-faults")
    if any(s.system_busy >= 80 for s in samples):
        result.append("high-system-cpu-sample")
    idle_windows = sum(1 for r in buckets(phase)
                       if r["end_s"]-r["start_s"] >= 4
                       and 0 <= r["cpu_ms"] <= 250
                       and 0 <= r["read_kb"] <= 256
                       and 0 <= r["write_kb"] <= 256)
    if idle_windows >= 2:
        result.append("multiple-low-activity-windows")
    return result


def report(phase: Phase, log=None):
    print(f"{phase.name}: {phase.result} | elapsed={phase.elapsed_ms} ms")
    print("  Window(s)   CPU(ms)  Read(KiB)  Write(KiB)  OtherIO  Faults  SysCPU(%)  RAM(MiB)  Threads")
    for row in buckets(phase):
        def val(key):
            return "?" if row[key] < 0 else str(row[key])
        print(f"  {row['start_s']:>2}-{row['end_s']:<3}       "
              f"{val('cpu_ms'):>6}    {val('read_kb'):>8}   "
              f"{val('write_kb'):>8}  {val('other_ops'):>7}  "
              f"{val('faults'):>6}  {val('peak_system_busy'):>9}  "
              f"{val('memory_mb'):>8}  {val('threads'):>7}")
        if log is not None:
            log("bgutil.windows-window", pid=os.getpid(), phase=phase.name,
                status=phase.result, window_start_s=row['start_s'], window_end_s=row['end_s'],
                cpu_ms=row['cpu_ms'] if row['cpu_ms'] >= 0 else "unavailable",
                read_kb=row['read_kb'] if row['read_kb'] >= 0 else "unavailable",
                write_kb=row['write_kb'] if row['write_kb'] >= 0 else "unavailable",
                other_ops=row['other_ops'] if row['other_ops'] >= 0 else "unavailable",
                page_faults=row['faults'] if row['faults'] >= 0 else "unavailable",
                system_cpu_pct=row['peak_system_busy'] if row['peak_system_busy'] >= 0 else "unavailable",
                memory_mb=row['memory_mb'] if row['memory_mb'] >= 0 else "unavailable",
                thread_count=row['threads'] if row['threads'] >= 0 else "unavailable")
    flags = classification(phase)
    print("  Signals: " + ", ".join(flags))
    if log is not None:
        log("bgutil.windows-phase", pid=os.getpid(), phase=phase.name,
            result=phase.result, startup_ms=phase.elapsed_ms)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--first", choices=("graph", "server"), default="graph",
                        help="what to observe BEFORE anything else starts Deno")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("WINDOWS OBSERVE: NOT RUN (Windows only)")
        return 2
    from app.paths import find_executable
    from app.bgutil_diagnostics import record_bgutil_diagnostic
    from services import bgutil_http_service as service

    raw_home = os.environ.get(service.ENV_HOME, "").strip()
    if not raw_home:
        print("WINDOWS OBSERVE: NOT RUN (developer opt-in missing)")
        return 2
    home = Path(raw_home).expanduser()
    deno = find_executable("deno.exe")
    if deno is None or not service._validate_external_home(home):
        print("WINDOWS OBSERVE: NOT RUN (Deno or external installation unavailable)")
        return 2
    boot = _helper("bgutil_boot_sequence_probe.py", "rrv_win_observe_boot")
    trace = _helper("bgutil_startup_trace.py", "rrv_win_observe_trace")
    cwd = home / "server" / "node_modules"
    env = boot._deno_env(home)

    def run_graph(name):
        command = [str(deno), "run", "--cached-only", "--allow-env", "--allow-net",
                   "--allow-ffi=.", "--allow-read=.", "-"]
        script = boot._module_stdin(home) + f'console.log("{_MARKER}");\n'
        return sample_task(name, lambda: (subprocess.Popen(
            command, cwd=str(cwd), env=env, stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)), script))

    def run_server(name):
        """Intercept only the real server process; do not replace its launcher."""
        process_ready = threading.Event()
        registered = {}
        origin_popen = subprocess.Popen
        final = {}

        def intercept(*a, **kw):
            process = origin_popen(*a, **kw)
            registered["process"] = process
            process_ready.set()
            return process

        def task():
            try:
                with patch.object(subprocess, "Popen", intercept):
                    final["trace"] = trace.run_once(service, home, deno, 1, deadline=DEADLINE)
            except Exception:
                final["status"] = "probe-error"
            finally:
                process_ready.set()

        start = perf_counter()
        thread = threading.Thread(target=task, daemon=True)
        thread.start()
        try:
            # Cold preflight may take time before Deno is actually spawned.
            # Never mistake slow validation for a failed process launch.
            while not process_ready.wait(timeout=.2):
                if not thread.is_alive() or perf_counter()-start > DEADLINE+10:
                    break
            process = registered.get("process")
            if process is None:
                thread.join(timeout=5)
                return Phase(name, "prelaunch-unavailable", round((perf_counter()-start)*1000), ())
            sampler = WindowsCounters()
            data = [sampler.read(process, round((perf_counter()-start)*1000))]
            while thread.is_alive() and (perf_counter()-start) <= DEADLINE+12:
                thread.join(timeout=INTERVAL)
                data.append(sampler.read(process, round((perf_counter()-start)*1000)))
            if thread.is_alive():
                try:
                    process.kill()
                except OSError:
                    pass
                thread.join(timeout=4)
            outcome = final.get("trace")
            status = ("late-ready" if outcome and outcome.result == "late-ready"
                      else "ok" if outcome and outcome.result == "ready"
                      else "timeout" if thread.is_alive() else "failed")
            return Phase(name, status, round((perf_counter()-start)*1000), tuple(data))
        except BaseException:
            process = registered.get("process")
            if process is not None:
                try:
                    process.kill()
                except OSError:
                    pass
            thread.join(timeout=4)
            raise

    print("RR-V Windows Deno time-series (read-only, no raw Windows trace)")
    print("First stage is cold; all later steps may be warmed. No YouTube or Chrome.")
    print("No raw stdout/stderr, filenames, URL or token data is logged.")
    first = run_graph("graph-cold") if args.first == "graph" else run_server("server-cold")
    report(first, record_bgutil_diagnostic)
    # An immediate repeat provides an intra-boot control; same observer method.
    again = run_graph("graph-warm") if args.first == "graph" else run_server("server-warm")
    report(again, record_bgutil_diagnostic)
    print("Physical disk I/O, exact blocking files, Defender scan timing and wait reasons")
    print("require separate privileged ETW/Process Monitor evidence; not inferred here.")
    if first.result != "ok" or again.result != "ok":
        print("WINDOWS OBSERVE: NEEDS REVIEW (late-ready still exceeds production budget)")
        return 1
    print("WINDOWS OBSERVE: COMPLETE (root cause still requires interpretation)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
