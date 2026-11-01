"""Portable, offline tests of Windows time-series diagnostic and redaction."""
from __future__ import annotations

from contextlib import redirect_stdout
from io import StringIO
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parent / 'manual' / 'bgutil_windows_observe.py'
SPEC = importlib.util.spec_from_file_location('rrv_windows_observe', SCRIPT)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class FakeProcess:
    pid = 9876
    returncode = 0
    def __init__(self, output=PROBE._MARKER + '\n'):
        self.output = output
        self.killed = False
    def communicate(self, input=None, timeout=None):
        return self.output, 'PRIVATE USER FILE PATH'
    def kill(self):
        self.killed = True


class Counter:
    calls = 0
    def read(self, process, elapsed_ms):
        self.calls += 1
        return PROBE.Snap(elapsed_ms, self.calls * 100, 200 + self.calls,
                          300 + self.calls, 500+self.calls, 900+self.calls,
                          20+self.calls, 15, 8, 40)


class WindowsObserveTests(unittest.TestCase):
    def test_no_os_api_used_on_nonwindows(self):
        if os.name != 'nt':
            snapshot = PROBE.WindowsCounters().read(FakeProcess(), 100)
            self.assertEqual(snapshot.cpu_ms, -1)
            self.assertEqual(snapshot.elapsed_ms, 100)

    def test_private_subprocess_output_never_printed(self):
        output = StringIO()
        with redirect_stdout(output):
            phase = PROBE.sample_task('graph-cold', lambda: (
                FakeProcess('PRIVATE_TOKEN\n' + PROBE._MARKER + '\n'), None),
                sampler_factory=Counter)
        self.assertEqual(phase.result, 'ok')
        self.assertEqual(output.getvalue(), '')
        self.assertNotIn('PRIVATE_TOKEN', repr(phase))

    def test_nonzero_or_missing_marker_returns_failure(self):
        phase = PROBE.sample_task('graph-cold', lambda: (FakeProcess('bad'), None),
                                  sampler_factory=Counter)
        self.assertEqual(phase.result, 'failed')

    def test_launch_error_does_not_print_exception(self):
        def fail():
            raise OSError('PRIVATE_PATH')
        with redirect_stdout(StringIO()) as out:
            phase = PROBE.sample_task('graph-cold', fail)
        self.assertEqual(phase.result, 'launch-error')
        self.assertEqual(out.getvalue(), '')

    def test_timeout_kills_process_without_untrusted_output(self):
        class Timeout(FakeProcess):
            def communicate(self, input=None, timeout=None):
                if not self.killed:
                    raise subprocess.TimeoutExpired('SECRET URL', timeout, output=b'PRIVATE DATA')
                return '', ''
        p = Timeout()
        phase = PROBE.sample_task('graph-cold', lambda: (p, None), sampler_factory=Counter,
                                  timeout=1)
        self.assertTrue(p.killed)
        self.assertEqual(phase.result, 'timeout')
        self.assertNotIn('PRIVATE', repr(phase))

    def test_counter_delta_bins_handle_unknown_metrics(self):
        phase = PROBE.Phase('graph-cold', 'ok', 10002, (
            PROBE.Snap(0, 100, 10, 5, 2, 0, 10, 1, 3, -1),
            PROBE.Snap(4900, 500, 200, 10, 20, 200, 22, 1, 4, 70),
            PROBE.Snap(5600, 520, 210, 11, 21, 201, 22, 1, 4, 85),
            PROBE.Snap(10002, 600, 400, 12, 25, 250, 25, 1, 4, 20),
        ))
        buckets = PROBE.buckets(phase)
        self.assertEqual(len(buckets), 3)
        self.assertEqual(buckets[0]['cpu_ms'], 400)
        self.assertEqual(buckets[1]['cpu_ms'], 20)
        self.assertEqual(buckets[1]['peak_system_busy'], 85)
        self.assertEqual(buckets[2]['cpu_ms'], 80)

    def test_classification_low_cpu_does_not_accuse_defender(self):
        phase = PROBE.Phase('graph-cold', 'ok', 30000, (
            PROBE.Snap(0, 100, 0, 0, 0, 0, 0, 0, 1, -1),
            PROBE.Snap(30000, 5600, 1000, 100, 300, 11000, 400, 50, 6, 92)
        ))
        labels = PROBE.classification(phase)
        self.assertIn('low-cpu-relative-to-wall', labels)
        self.assertIn('many-process-page-faults', labels)
        self.assertIn('high-system-cpu-sample', labels)
        self.assertFalse(any('defender' in x for x in labels))

    def test_late_ready_is_not_mistaken_for_normal_production_success(self):
        phase = PROBE.Phase('server-cold', 'late-ready', 34863, (
            PROBE.Snap(0,100), PROBE.Snap(34863,3000)))
        self.assertIn('would-fallback-in-production', PROBE.classification(phase))

    def test_unknown_counters_do_not_claim_low_cpu(self):
        phase = PROBE.Phase('graph-cold', 'ok', 31000, (PROBE.Snap(0), PROBE.Snap(31000)))
        self.assertEqual(PROBE.classification(phase), ['long-startup-observed'])

    def test_short_start_only_reports_no_long_delay(self):
        phase = PROBE.Phase('graph-warm', 'ok', 2700, (PROBE.Snap(0), PROBE.Snap(2700)))
        self.assertEqual(PROBE.classification(phase), ['no-long-delay-observed'])

    def test_report_safe_and_structured(self):
        phase = PROBE.Phase('graph-cold', 'ok', 3000, (
            PROBE.Snap(0, 0, 0, 0, 0, 0, 20, 3, 1, -1),
            PROBE.Snap(3000, 200, 100, 0, 100, 100, 30, 5, 2, 50)))
        recorder = MagicMock()
        with redirect_stdout(StringIO()) as out:
            PROBE.report(phase, recorder)
        self.assertIn('graph-cold', out.getvalue())
        self.assertNotIn('private', out.getvalue().lower())
        self.assertEqual(recorder.call_args_list[0].args[0], 'bgutil.windows-window')
        self.assertEqual(recorder.call_args_list[-1].args[0], 'bgutil.windows-phase')

    def test_handles_number_of_empty_samples(self):
        phase = PROBE.Phase('graph-cold', 'launch-error', 0, ())
        self.assertEqual(PROBE.buckets(phase), [])
        self.assertEqual(PROBE.classification(phase), ['cold-probe-not-successful'])

    def test_mock_win32_os_counters_are_decoded_safely(self):
        # Exercise ctypes pointer handling on Linux too, without Windows APIs.
        import ctypes
        from types import SimpleNamespace
        class Func:
            def __init__(self, fun):
                self.fun = fun
            def __call__(self, *args):
                return self.fun(*args)

        def times(handle, creation, exit_time, kernel, user):
            kernel._obj.low = 20000000
            user._obj.low = 5000000
            return 1

        def io(handle, pointer):
            pointer._obj.read_bytes = 1024 * 2048
            pointer._obj.write_bytes = 1024 * 100
            pointer._obj.other_ops = 55
            return 1

        def mem(handle, pointer, size):
            pointer._obj.faults = 3456
            pointer._obj.working = 48 * 1024 * 1024
            return 1

        def handles(handle, pointer):
            pointer._obj.value = 45
            return 1

        fake = PROBE.WindowsCounters()
        fake.available = True
        fake.kernel = SimpleNamespace(
            GetProcessTimes=Func(times), GetProcessIoCounters=Func(io),
            GetProcessHandleCount=Func(handles))
        fake.psapi = SimpleNamespace(GetProcessMemoryInfo=Func(mem))
        fake._thread_count = lambda pid: 7
        fake._system_busy = lambda: 37
        result = fake.read(SimpleNamespace(_handle=99, pid=888), 31000)
        self.assertEqual((result.cpu_ms, result.read_kb, result.write_kb), (2500, 2048, 100))
        self.assertEqual((result.faults, result.memory_mb, result.threads, result.handles),
                         (3456, 48, 7, 45))
        self.assertEqual(result.system_busy, 37)

    def test_healthy_win32_api_errors_fall_back_to_unknown(self):
        from types import SimpleNamespace
        fake = PROBE.WindowsCounters()
        fake.available = True
        class Broken:
            def __getattr__(self, name):
                raise OSError("PRIVATE PATH")
        fake.kernel = Broken()
        self.assertEqual(fake.read(SimpleNamespace(_handle=8), 10).cpu_ms, -1)

    def test_repeated_idle_windows_are_reported_not_misattributed(self):
        samples = (PROBE.Snap(0,0,0,0), PROBE.Snap(5000,100,100,50),
                   PROBE.Snap(10000,150,150,60), PROBE.Snap(15000,200,200,80))
        result = PROBE.classification(PROBE.Phase('graph-cold','ok',15000,samples))
        self.assertIn('multiple-low-activity-windows', result)
        self.assertFalse(any('defender' in flag for flag in result))

    def test_real_python_child_can_be_safely_observed(self):
        # Real subprocess and stream drain, no Windows-specific API required.
        phase = PROBE.sample_task('graph-cold', lambda: (
            subprocess.Popen([sys.executable, '-c',
                 f'print("PRIVATE");print("{PROBE._MARKER}")'],
                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                 stdin=subprocess.DEVNULL, text=True), None), sampler_factory=Counter)
        self.assertEqual(phase.result, 'ok')
        self.assertTrue(len(phase.snapshots) >= 2)


if __name__ == '__main__':
    unittest.main()
