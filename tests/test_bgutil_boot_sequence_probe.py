"""Unit tests for safe Deno/BgUtils boot-order comparisons."""
from __future__ import annotations

from contextlib import redirect_stdout
import importlib.util
from io import StringIO
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch, MagicMock

FILE = Path(__file__).parent / 'manual' / 'bgutil_boot_sequence_probe.py'
SPEC = importlib.util.spec_from_file_location('rrv_bgutil_boot_sequence_probe', FILE)
assert SPEC and SPEC.loader
PROBE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROBE
SPEC.loader.exec_module(PROBE)


class BootSequenceProbeTests(unittest.TestCase):
    def test_mode_orders_have_distinct_first_stage(self):
        self.assertEqual(PROBE.stage_sequence('server'), ('server', 'server-repeat', 'imports', 'runtime'))
        self.assertEqual(PROBE.stage_sequence('runtime'), ('runtime', 'imports', 'server', 'server-repeat'))
        self.assertEqual(PROBE.stage_sequence('imports'), ('imports', 'runtime', 'server', 'server-repeat'))
        with self.assertRaises(ValueError):
            PROBE.stage_sequence('invalid')

    def test_runtime_uses_same_deno_cache_and_module_working_directory(self):
        completed = types.SimpleNamespace(returncode=0, stdout=PROBE._MARKER_RUNTIME + '\n')
        with patch.object(PROBE.subprocess, 'run', return_value=completed) as run:
            result = PROBE.run_deno_stage('runtime', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'runtime-ready')
        kwargs = run.call_args.kwargs
        self.assertEqual(run.call_args.args[0][:2], ['deno.exe', 'eval'])
        self.assertTrue(str(kwargs['cwd']).endswith(str(Path('server/node_modules'))))
        self.assertEqual(kwargs['env']['DENO_DIR'], str(Path('external/deno-cache')))
        self.assertEqual(kwargs['timeout'], 60.0)
        self.assertEqual(kwargs['stderr'], PROBE.subprocess.PIPE)
        self.assertNotIn('RRV_BGUTIL_STAGE03_HOME', repr(result))

    def test_import_stage_executes_real_pinned_graph_without_server(self):
        completed = types.SimpleNamespace(returncode=0, stdout=PROBE._MARKER_IMPORTS + '\n')
        with patch.object(PROBE.subprocess, 'run', return_value=completed) as run:
            result = PROBE.run_deno_stage('imports', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'imports-ready')
        args = run.call_args.args[0]
        self.assertEqual(args[1:3], ['run', '--cached-only'])
        self.assertEqual(args[-1], '-')
        self.assertIn('session_manager.ts', run.call_args.kwargs['input'])
        self.assertNotIn('main.ts', run.call_args.kwargs['input'])
        self.assertNotIn('/get_pot', run.call_args.kwargs['input'])
        self.assertEqual(run.call_args.kwargs['timeout'], 60.0)

    def test_module_source_uri_is_only_in_stdin_not_command_line(self):
        external = Path("C:/Users/Example Folder/bgutil-stage03-external")
        script = PROBE._module_stdin(external)
        self.assertIn("session_manager.ts", script)
        self.assertIn("file://", script)
        self.assertIn(PROBE._MARKER_IMPORTS, script)
        success = types.SimpleNamespace(returncode=0, stdout=PROBE._MARKER_IMPORTS + "\n")
        with patch.object(PROBE.subprocess, "run", return_value=success) as called:
            PROBE.run_deno_stage("imports", Path("deno.exe"), external)
        self.assertNotIn("session_manager.ts", repr(called.call_args.args[0]))
        self.assertIn("session_manager.ts", called.call_args.kwargs["input"])

    def test_deno_stage_disallows_unexpected_stage(self):
        with self.assertRaises(ValueError):
            PROBE.run_deno_stage('server', Path('deno.exe'), Path('external'))

    def test_token_or_path_in_stdout_cannot_create_false_success(self):
        raw = 'PRIVATE_SECRET_TOKEN\nhttp://sensitive\n'
        completed = types.SimpleNamespace(returncode=0, stdout=raw)
        with patch.object(PROBE.subprocess, 'run', return_value=completed):
            result = PROBE.run_deno_stage('runtime', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'runtime-failed')
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn('http://', repr(result))

    def test_nonzero_exit_is_failure_even_with_success_marker(self):
        completed = types.SimpleNamespace(returncode=3, stdout=PROBE._MARKER_IMPORTS)
        with patch.object(PROBE.subprocess, 'run', return_value=completed):
            result = PROBE.run_deno_stage('imports', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'imports-failed')

    def test_timeout_does_not_leak_raw_exception(self):
        error = PROBE.subprocess.TimeoutExpired('SECRET path', 60, output=b'PRIVATE CREDENTIAL')
        with patch.object(PROBE.subprocess, 'run', side_effect=error):
            result = PROBE.run_deno_stage('runtime', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'runtime-timeout')
        self.assertNotIn('PRIVATE', repr(result))
        self.assertNotIn('SECRET', repr(result))

    def test_launch_error_does_not_leak_path(self):
        with patch.object(PROBE.subprocess, 'run', side_effect=OSError('SECRET path')):
            result = PROBE.run_deno_stage('imports', Path('deno.exe'), Path('external'))
        self.assertEqual(result.result, 'imports-launch-error')

    def test_server_uses_actual_startup_trace_with_diagnostic_only_deadline(self):
        result = types.SimpleNamespace(result='late-ready', startup_ms=34863,
            first_output_ms=34657, announced_ms=34657,tcp_ms=34840,ping_ms=34840)
        with patch.object(PROBE.TRACE, 'run_once', return_value=result) as start:
            actual = PROBE.run_server_stage(object(), Path('external'), Path('deno.exe'), 'server-repeat')
        self.assertEqual(actual.result, 'late-ready')
        self.assertEqual(actual.announced_ms, 34657)
        self.assertEqual(start.call_args.kwargs['deadline'], 60.0)
        self.assertEqual(start.call_args.kwargs['attempt'], 2)

    def test_server_cannot_use_invalid_stage(self):
        with self.assertRaises(ValueError):
            PROBE.run_server_stage(object(), Path('external'), Path('deno.exe'), 'runtime')

    def test_report_never_outputs_raw_private_information(self):
        row = PROBE.StageResult('server', 'late-ready', 34000, 33333, 33333, 33800, 34000)
        log = MagicMock()
        output = StringIO()
        with redirect_stdout(output):
            PROBE.report(row, 'server', log)
        self.assertIn('34000', output.getvalue())
        self.assertNotIn('http://', output.getvalue())
        self.assertEqual(log.call_args.args[0], 'bgutil.boot-sequence')
        self.assertEqual(log.call_args.kwargs['order'], 'server-first')
        self.assertEqual(log.call_args.kwargs['phase'], 'server')

    @staticmethod
    def _fake_modules():
        bgdiag = types.ModuleType('app.bgutil_diagnostics')
        bgdiag.record_bgutil_diagnostic = MagicMock()
        paths = types.ModuleType('app.paths')
        paths.find_executable = lambda _: Path('deno.exe')
        pkg = types.ModuleType('services')
        server = types.ModuleType('services.bgutil_http_service')
        server.ENV_HOME = 'RRV_BGUTIL_STAGE03_HOME'
        server._validate_external_home = lambda h: True
        pkg.bgutil_http_service = server
        return {'app.bgutil_diagnostics': bgdiag, 'app.paths': paths,
                'services': pkg, 'services.bgutil_http_service': server}, bgdiag, server

    def test_main_runs_four_stages_in_requested_order_and_logs_each(self):
        mods, diag, _ = self._fake_modules()
        stages = []
        def runtime(s, d, h):
            stages.append(s)
            return PROBE.StageResult(s, s+'-ready', 90)
        def server(svc,h,d,s):
            stages.append(s)
            return PROBE.StageResult(s,'ready',2900)
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ, {'RRV_BGUTIL_STAGE03_HOME':'external'}),
              patch.object(PROBE,'run_deno_stage',side_effect=runtime),
              patch.object(PROBE,'run_server_stage',side_effect=server),
              redirect_stdout(StringIO()) as stdout):
            code = PROBE.main(['--first','imports'])
        self.assertEqual(code,0)
        self.assertEqual(stages,['imports','runtime','server','server-repeat'])
        self.assertEqual(diag.record_bgutil_diagnostic.call_count,4)
        self.assertIn('BOOT SEQUENCE: COMPLETE',stdout.getvalue())

    def test_main_continues_after_module_error(self):
        mods, diag, _ = self._fake_modules()
        stages=[]
        def runtime(s,d,h):
            stages.append(s)
            return PROBE.StageResult(s, 'imports-failed' if s=='imports' else 'runtime-ready', 44)
        def server(svc,h,d,s):
            stages.append(s)
            return PROBE.StageResult(s,'ready',2513)
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ, {'RRV_BGUTIL_STAGE03_HOME':'external'}),
              patch.object(PROBE,'run_deno_stage',side_effect=runtime),
              patch.object(PROBE,'run_server_stage',side_effect=server),
              redirect_stdout(StringIO()) as stdout):
            code=PROBE.main(['--first','runtime'])
        self.assertEqual(code,1)
        self.assertEqual(stages,['runtime','imports','server','server-repeat'])
        self.assertIn('NEEDS REVIEW',stdout.getvalue())

    def test_main_late_server_start_not_reported_as_fixed(self):
        mods,diag,_=self._fake_modules()
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ, {'RRV_BGUTIL_STAGE03_HOME':'external'}),
              patch.object(PROBE,'run_deno_stage',side_effect=lambda s,d,h:PROBE.StageResult(s,s+'-ready',300)),
              patch.object(PROBE,'run_server_stage',side_effect=lambda svc,h,d,s:PROBE.StageResult(s,'late-ready',35200)),
              redirect_stdout(StringIO()) as stdout):
            code=PROBE.main(['--first','server'])
        self.assertEqual(code,0)
        self.assertIn('LATE-READY',stdout.getvalue())
        self.assertNotIn('root cause', stdout.getvalue())

    def test_main_requires_opt_in(self):
        mods, diag, _ = self._fake_modules()
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ, {'RRV_BGUTIL_STAGE03_HOME':''}),
              redirect_stdout(StringIO()) as stdout):
            code=PROBE.main(['--first','runtime'])
        self.assertEqual(code,2)
        self.assertIn('NOT RUN', stdout.getvalue())

    def test_main_rejects_invalid_installation(self):
        mods, diag, service = self._fake_modules()
        service._validate_external_home = lambda h: False
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ, {'RRV_BGUTIL_STAGE03_HOME':'external'}),
              redirect_stdout(StringIO()) as stdout):
            code=PROBE.main(['--first','server'])
        self.assertEqual(code,2)
        self.assertIn('invalid',stdout.getvalue())

    def test_main_catches_sensitive_exception_and_continues(self):
        mods,diag,_=self._fake_modules()
        with (patch.dict(sys.modules,mods),
              patch.dict(os.environ,{'RRV_BGUTIL_STAGE03_HOME':'external'}),
              patch.object(PROBE,'run_deno_stage',side_effect=OSError('SENSITIVE PATH SECRET')),
              patch.object(PROBE,'run_server_stage',side_effect=lambda svc,h,d,s:PROBE.StageResult(s,'ready',50)),
              redirect_stdout(StringIO()) as stdout):
            code=PROBE.main(['--first','imports'])
        self.assertEqual(code,1)
        self.assertIn('probe-exception',stdout.getvalue())
        self.assertNotIn('SENSITIVE',stdout.getvalue())


if __name__=='__main__':
    unittest.main()
