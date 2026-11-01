"""Offline checks for one-boot Windows diagnostics; no WPR or Deno runs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import importlib.util
import json
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import MagicMock, patch

FILE = Path(__file__).parent / 'manual' / 'bgutil_oneboot_diag.py'
SPEC = importlib.util.spec_from_file_location('rrv_oneboot_diagnostic_test', FILE)
assert SPEC and SPEC.loader
D = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = D
SPEC.loader.exec_module(D)
GB = 1024**3
# Windows virtualenv python.exe can be a redirector that exits before the
# real interpreter. For direct-child timeout tests use the base executable.
TEST_PYTHON = getattr(sys, "_base_executable", sys.executable)


class FakeResult:
    def __init__(self, code=0, text=''):
        self.returncode, self.stdout = code, text


class OnebootTests(unittest.TestCase):
    def test_profiles_only_fixed_names(self):
        x = 'CPU  sampling\nDiskIO read\nFileIO paths\nNetwork activity\nnotMinifilterExtra'
        self.assertEqual(D.fixed_profile_names(x), ('CPU', 'DiskIO', 'FileIO', 'Network'))
        self.assertEqual(D.wpr_command(('CPU', 'FileIO')), ['-start', 'CPU', '-start', 'FileIO'])
        with self.assertRaises(ValueError):
            D.wpr_command(('CPU', 'SECRET_PATH'))

    def test_preflight_refuses_bad_conditions_before_wpr(self):
        self.assertEqual(D.preflight('wpr',admin=False,free_bytes=10*GB,wpa_available=False,check_tools=False).reason,
                         'administrator-rights-required')
        self.assertEqual(D.preflight('wpr',admin=True,free_bytes=100,wpa_available=False,check_tools=False).reason,
                         'insufficient-disk-space')
        self.assertEqual(D.preflight(None,admin=True,free_bytes=10*GB,wpa_available=False,check_tools=False).reason,
                         'wpr-unavailable')

    def test_preflight_wpr_start_and_cancel_verified(self):
        calls=[]
        def run(cmd, **kw):
            calls.append(cmd)
            if '-status' in cmd:
                return FakeResult(text='WPR is not recording')
            if '-stop' in cmd:
                Path(cmd[cmd.index('-stop')+1]).write_bytes(b'WPR_PRIVATE_PREFLIGHT')
            return FakeResult(text='CPU\nDiskIO\nFileIO\nNetwork\nMinifilter\nRegistry')
        with patch.object(D, 'run_private', side_effect=run):
            out=D.preflight('wpr.exe',admin=True,free_bytes=12*GB,wpa_available=True,check_tools=False)
        self.assertTrue(out.ok)
        self.assertIn('Minifilter',out.profiles)
        self.assertTrue(any('-stop' in cmd for cmd in calls))
        self.assertTrue(any('-start' in cmd for cmd in calls))
        self.assertEqual(calls[-1],['wpr.exe','-status'])
        self.assertEqual(out.disk_gb,12)

    def test_start_failure_never_cancels_another_trace(self):
        calls=[]
        def run(cmd, **kw):
            calls.append(cmd)
            if '-status' in cmd:
                return FakeResult(text='WPR is not recording')
            return FakeResult(code=1) if '-start' in cmd else FakeResult(text='CPU DiskIO FileIO')
        with patch.object(D,'run_private',side_effect=run):
            out=D.preflight('wpr.exe',admin=True,free_bytes=10*GB,wpa_available=False,check_tools=False)
        self.assertFalse(out.ok)
        self.assertFalse(any('-cancel' in x for x in calls))

    def test_stop_save_failure_blocks_reboot_and_attempts_cancel(self):
        calls = []
        state={'active':False}
        def run(cmd, **kw):
            calls.append(cmd)
            if '-status' in cmd:
                return FakeResult(text='WPR recording is in progress' if state['active'] else 'WPR is not recording')
            if '-profiles' in cmd:
                return FakeResult(text='CPU DiskIO FileIO')
            if '-start' in cmd:
                state['active']=True
                return FakeResult()
            if '-stop' in cmd:
                return FakeResult(code=1)
            if '-cancel' in cmd:
                state['active']=False
                return FakeResult()
            return FakeResult(code=1)
        with patch.object(D,'run_private',side_effect=run):
            out=D.preflight('wpr.exe',admin=True,free_bytes=10*GB,wpa_available=False,check_tools=False)
        self.assertFalse(out.ok)
        self.assertEqual(out.reason,'wpr-stop-save-not-verified')
        self.assertIn(['wpr.exe','-cancel'],calls)
        self.assertFalse(state['active'])

    def test_manifest_is_explicit_and_expires(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            self.assertEqual(D.read_preflight(root),())
            D.save_preflight(D.Preflight(True,'ready',('CPU','DiskIO','FileIO')),root)
            p=json.loads((root/'preflight.json').read_text())
            self.assertEqual(D.read_preflight(root,now=p['created_utc']+100),('CPU','DiskIO','FileIO'))
            self.assertEqual(D.read_preflight(root,now=p['created_utc']+D.PREFLIGHT_VALID_DAYS*86400+1),())
            p['profiles'].append('MYEVILPROFILE')
            (root/'preflight.json').write_text(json.dumps(p))
            self.assertEqual(D.read_preflight(root),())

    def test_wpr_ownership_lifecycle_never_prints_raw(self):
        wpr=D.WprRecording('wpr.exe',('CPU','DiskIO','FileIO'))
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'trace.etl'
            cmds=[]
            def run(cmd,**kw):
                cmds.append(cmd)
                if '-stop' in cmd:
                    target.write_bytes(b'SENSITIVE_WPR_TRACE')
                return FakeResult()
            with patch.object(D,'run_private',side_effect=run):
                self.assertEqual(wpr.start(),'recording')
                wpr.marker('RRV_COLD_BEGIN')
                wpr.marker('SECRET_USER_INFO')
                self.assertEqual(wpr.stop(target),'saved')
            self.assertEqual(len([x for x in cmds if '-marker' in x]),1)
            self.assertNotIn(['wpr.exe','-cancel'],cmds)
            self.assertFalse(wpr.owned)

    def test_wpr_stop_failed_cancels_only_its_own_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            wpr=D.WprRecording('wpr.exe',('CPU','DiskIO','FileIO'))
            cmds=[]
            def run(cmd,**kw):
                cmds.append(cmd)
                return FakeResult(code=1) if '-stop' in cmd else FakeResult()
            with patch.object(D,'run_private',side_effect=run):
                wpr.start()
                self.assertEqual(wpr.stop(Path(tmp)/'trace.etl'),'stop-failed')
            self.assertIn(['wpr.exe','-cancel'],cmds)
            self.assertFalse(wpr.owned)
            cmds.clear()
            wpr.cancel()
            self.assertEqual(cmds,[])

    def test_to_safe_phase_never_contains_process_or_path(self):
        dummy=types.SimpleNamespace(result='ok',elapsed_ms=30000,snapshots=())
        observe=types.SimpleNamespace(classification=lambda p:['long-startup-observed'],buckets=lambda p:[{'cpu_ms':1}])
        output=D.to_safe_phase(dummy,observe,{'ping_ms':30000})
        self.assertEqual(output['status'],'ok')
        self.assertNotIn('http://',repr(output))
        self.assertNotIn('C:\\',repr(output))

    def test_record_server_reports_real_trace_milestones(self):
        obj=types.SimpleNamespace(status='ready',result='ready',startup_ms=3200,
             first_output_ms=2800,announced_ms=2800,tcp_ms=3100,ping_ms=3200,ping_attempts=5)
        trace=types.SimpleNamespace(run_once=lambda *a,**k:obj)
        service=types.SimpleNamespace(subprocess=types.SimpleNamespace(Popen=None))
        observe=types.SimpleNamespace(WindowsCounters=lambda:None, Phase=lambda n,s,ms,samples:types.SimpleNamespace(
            name=n,result=s,elapsed_ms=ms,snapshots=samples))
        phase, milestones=D.record_server(service,Path('/dummy'),Path('/dummy'),trace,observe,'server-cold')
        self.assertEqual(phase.result,'ok')
        self.assertEqual(milestones['announced_ms'],2800)

    def test_evidence_cold_warm_gap_and_no_defender_accusation(self):
        flags=D.evidence({'elapsed_ms':31000,'signals':['long-startup-observed'],
                          'milestones':{'announced_ms':30400,'ping_ms':30700}},
                         {'elapsed_ms':3200},{'defender_status':'enabled','modules':[]})
        self.assertIn('reproducible-cold-vs-warm-gap-in-this-boot',flags)
        self.assertIn('would-exceed-production-first-use-budget',flags)
        self.assertIn('defender-enabled-not-proof-of-scan-delay',flags)
        self.assertNotIn('defender-caused-delay',flags)

    def test_followups_continue_and_are_safe(self):
        boot=types.SimpleNamespace(run_deno_stage=lambda stage,*a:types.SimpleNamespace(result=stage+'-ready',elapsed_ms=45))
        def deny(stage,*a,**kw):
            if stage == 'jsdom': raise OSError('SECRET PATH')
            return types.SimpleNamespace(status='ok',elapsed_ms=100)
        wide=types.SimpleNamespace(MODULES=(('jsdom','x'),('axios','y')),deno_probe=deny,
             passive_system=lambda: {'uptime_min':12,'proxy':'absent','free_memory_pct':40},
             storage_snapshot=lambda home: {'drive':'fixed','free_disk_gb':42,'deno_cache':'present'},
             defender_snapshot=lambda **kw:'enabled',mark_of_web=lambda x:'absent')
        result=D.run_followup(Path('/tmp'),Path('/deno'),None,boot,wide,None)
        self.assertEqual(result['modules'][0]['status'],'probe-error')
        self.assertEqual(result['modules'][1]['status'],'ok')
        self.assertNotIn('SECRET',repr(result))

    def test_capture_end_to_end_saves_safe_summary_without_raw_trace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            service = types.SimpleNamespace()
            observe = types.SimpleNamespace(
                Phase=lambda name,status,ms,stats: types.SimpleNamespace(
                    name=name,result=status,elapsed_ms=ms,snapshots=stats),
                classification=lambda phase: ['long-startup-observed'] if phase.elapsed_ms > 10000 else [],
                buckets=lambda phase: [{'cpu_ms': 55, 'read_kb': 12, 'write_kb': 0, 'other_ops': 6,
                                        'faults': 4, 'peak_system_busy': 10, 'memory_mb': 2,
                                        'threads': 1, 'handles': 2, 'start_s': 0, 'end_s': 5}],
            )
            def fake_server(service, home, deno, trace, observe, name):
                duration=31000 if name.endswith('cold') else 3000
                return (observe.Phase(name,'ok',duration,()),
                        {'announced_ms':duration-220,'ping_ms':duration-5,
                         'startup_ms':duration, 'first_output_ms':duration-220,
                         'tcp_ms':duration-80, 'ping_attempts':5})
            class FakeWpr:
                names=[]
                def __init__(self, bin, profiles):
                    self.profiles=profiles
                def start(self):
                    self.names.append('start');return 'recording'
                def marker(self, name):
                    self.names.append(name)
                def stop(self, etl):
                    etl.write_bytes(b'PRIVATE_FILENAME_MUST_NOT_APPEAR')
                    self.names.append('stop');return 'saved'
            original_env = D.os
            stub_os=types.SimpleNamespace(name='nt',environ=os.environ,getpid=os.getpid)
            diag=types.ModuleType('app.bgutil_diagnostics')
            diag.record_bgutil_diagnostic=MagicMock()
            follow={'baseline':[{'stage':'runtime','status':'runtime-ready','elapsed_ms':95}],
                    'modules':[], 'system':{'free_memory_pct':40},
                    'storage':{'drive':'fixed'},'defender_status':'enabled'}
            with (patch.object(D,'os',stub_os),
                  patch.object(D,'diagnostic_home',return_value=root),
                  patch.object(D,'read_preflight',return_value=('CPU','DiskIO','FileIO')),
                  patch.object(D,'elevated',return_value=True),
                  patch.object(D,'validate_home_and_deno',return_value=(service,root,root/'deno.exe','ready')),
                  patch.object(D.shutil,'which',return_value='wpr.exe'),
                  patch.object(D.shutil,'disk_usage',return_value=types.SimpleNamespace(free=40*GB)),
                  patch.object(D,'WprRecording',FakeWpr),
                  patch.object(D,'load_module',side_effect=lambda name,file: observe),
                  patch.object(D,'record_server',side_effect=fake_server),
                  patch.object(D,'run_followup',return_value=follow),
                  patch.dict(sys.modules, {'app.bgutil_diagnostics':diag}),
                  patch('sys.stdout',new_callable=__import__('io').StringIO) as stdout):
                code=D.run_capture()
            self.assertEqual(code,0)
            self.assertEqual(FakeWpr.names,['start','RRV_COLD_BEGIN','RRV_COLD_END','stop'])
            self.assertIn('COMPLETE',stdout.getvalue())
            self.assertNotIn('PRIVATE_FILENAME_MUST_NOT_APPEAR',stdout.getvalue())
            summary=list(root.glob('oneboot-*/*summary.json'))
            self.assertEqual(len(summary),1)
            data=json.loads(summary[0].read_text())
            self.assertEqual(data['cold']['elapsed_ms'],31000)
            self.assertEqual(data['warm']['elapsed_ms'],3000)
            self.assertTrue(data['wpr']['raw_etl_local_only'])
            self.assertNotIn('PRIVATE_FILENAME_MUST_NOT_APPEAR',repr(data))
            self.assertEqual(len(list(root.glob('oneboot-*/*.etl'))),1)

    def test_capture_not_run_without_preflight_or_admin(self):
        from contextlib import redirect_stdout
        from io import StringIO
        stub_os=types.SimpleNamespace(name='nt',environ=os.environ,getpid=os.getpid)
        with (redirect_stdout(StringIO()),
              patch.object(D,'os',stub_os),
              patch.object(D,'read_preflight',return_value=()),
              patch.object(D,'elevated',return_value=True)):
            self.assertEqual(D.run_capture(),2)
        with (redirect_stdout(StringIO()),
              patch.object(D,'os',stub_os),
              patch.object(D,'read_preflight',return_value=('CPU','DiskIO','FileIO')),
              patch.object(D,'elevated',return_value=False)):
            self.assertEqual(D.run_capture(),2)

    def test_nonwindows_capture_refused_before_any_operation(self):
        from contextlib import redirect_stdout
        from io import StringIO
        if os.name!='nt':
            with redirect_stdout(StringIO()):
                self.assertEqual(D.run_capture(),2)

    def test_main_requires_explicit_mode(self):
        from contextlib import redirect_stderr
        from io import StringIO
        with redirect_stderr(StringIO()) as stderr:
            with self.assertRaises(SystemExit):
                D.main([])
        self.assertIn("--preflight", stderr.getvalue())

    def test_preflight_failure_does_not_store_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            D.save_preflight(D.Preflight(False,'not-ready'),p)
            self.assertFalse((p/'preflight.json').exists())

    def test_wpr_args_in_memory_mode_not_unbounded_filemode(self):
        self.assertNotIn('-filemode', D.wpr_command(('CPU','DiskIO','FileIO')))
        self.assertNotIn('-recordtempto', D.wpr_command(('CPU','DiskIO','FileIO')))

    def test_preflight_existing_wpr_session_is_never_touched(self):
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            return FakeResult(text='WPR recording is in progress')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=11*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        self.assertIn('existing-or-unverified', result.reason)
        self.assertEqual(calls, [['wpr.exe', '-status']])

    def test_preflight_unknown_wpr_status_fails_closed(self):
        with patch.object(D, 'run_private', return_value=FakeResult(text='INDETERMINATE_WPR_STATE')) as fake:
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        self.assertEqual(fake.call_count, 1)

    def test_preflight_start_timeout_does_not_cancel_unverified_trace(self):
        calls = []
        def fake(command, **kw):
            calls.append(command)
            if '-status' in command:
                return FakeResult(text='WPR is not recording')
            if '-profiles' in command:
                return FakeResult(text='CPU DiskIO FileIO')
            if '-start' in command:
                raise __import__('subprocess').TimeoutExpired('PRIVATE_COMMAND', 25)
            raise AssertionError('no other WPR command should be run')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertEqual(result.reason, 'wpr-start-timeout-ownership-uncertain-check-status')
        self.assertFalse(any('-cancel' in cmd for cmd in calls))

    def test_preflight_optional_profile_failure_uses_safe_core_fallback(self):
        calls = []
        def fake(command, **kw):
            calls.append(command)
            if '-status' in command:
                return FakeResult(text='WPR is not recording')
            if '-profiles' in command:
                return FakeResult(text='CPU DiskIO FileIO Registry Network Minifilter')
            if '-start' in command:
                return FakeResult(code=1 if 'Registry' in command else 0)
            if '-stop' in command:
                Path(command[command.index('-stop')+1]).write_bytes(b'PRIVATE_WPR_OUTPUT')
                return FakeResult()
            raise AssertionError('unexpected WPR call')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=True, check_tools=False)
        self.assertTrue(result.ok)
        self.assertEqual(result.profiles, D.PROFILES_CORE)
        self.assertEqual(sum('-start' in cmd for cmd in calls), 2)
        self.assertFalse(any('-cancel' in cmd for cmd in calls))

    def test_preflight_optional_profile_failure_never_retries_while_recording(self):
        calls = []
        status = {'count': 0}
        def fake(command, **kw):
            calls.append(command)
            if '-status' in command:
                status['count'] += 1
                return FakeResult(text='WPR is not recording' if status['count'] == 1
                                  else 'WPR recording is in progress')
            if '-profiles' in command:
                return FakeResult(text='CPU DiskIO FileIO Registry')
            if '-start' in command:
                return FakeResult(code=1)
            raise AssertionError('should not try another WPR operation')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        self.assertEqual(sum('-start' in cmd for cmd in calls), 1)
        self.assertFalse(any('-cancel' in cmd for cmd in calls))

    def test_preflight_stop_timeout_attempts_cancel_only_after_confirmed_start(self):
        status = {'recording': False}
        calls = []
        def fake(command, **kw):
            calls.append(command)
            if '-status' in command:
                return FakeResult(text='WPR recording is in progress' if status['recording']
                                  else 'WPR is not recording')
            if '-profiles' in command:
                return FakeResult(text='CPU DiskIO FileIO')
            if '-start' in command:
                status['recording'] = True
                return FakeResult()
            if '-stop' in command:
                raise __import__('subprocess').TimeoutExpired('PRIVATE_PATH', 90)
            if '-cancel' in command:
                status['recording'] = False
                return FakeResult()
            raise AssertionError('unexpected WPR call')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'wpr-stop-save-not-verified')
        self.assertIn(['wpr.exe', '-cancel'], calls)
        self.assertFalse(status['recording'])

    def test_preflight_cancel_failure_requires_manual_check(self):
        state = {'active': False}
        def fake(command, **kw):
            if '-status' in command:
                return FakeResult(text='WPR recording is in progress' if state['active']
                                  else 'WPR is not recording')
            if '-profiles' in command:
                return FakeResult(text='CPU DiskIO FileIO')
            if '-start' in command:
                state['active'] = True
                return FakeResult()
            if '-stop' in command or '-cancel' in command:
                return FakeResult(code=1)
            raise AssertionError('unexpected WPR call')
        with patch.object(D, 'run_private', side_effect=fake):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, 'wpr-owned-trace-cleanup-unconfirmed')

    def test_preflight_global_budget_bounds_work(self):
        with (patch.object(D, 'PREFLIGHT_OVERALL_TIMEOUT', 0.0),
              patch.object(D, 'run_private') as run):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertFalse(result.ok)
        run.assert_not_called()
        self.assertEqual(result.reason, 'wpr-command-timeout-or-global-budget-check-status')

    def test_preflight_ctrl_c_returns_visible_safe_status(self):
        with patch.object(D, 'run_private', side_effect=KeyboardInterrupt):
            result = D.preflight('wpr.exe', admin=True, free_bytes=10*GB,
                                 wpa_available=False, check_tools=False)
        self.assertEqual(result.reason, 'interrupted-check-wpr-status-do-not-reboot')

    def test_private_subprocess_timeout_is_bounded_without_raw_output(self):
        import subprocess
        import time
        started = time.monotonic()
        with self.assertRaises(subprocess.TimeoutExpired):
            D.run_private([TEST_PYTHON, '-c', 'import time; time.sleep(10)'],
                          timeout=.25, stage='TEST')
        # taskkill /T on Windows can spend extra seconds cleaning descendants.
        self.assertLess(time.monotonic() - started, 9.0 if os.name == "nt" else 2.0)

    def test_private_subprocess_heartbeat_shows_only_safe_timing(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with (patch.object(D, 'WPR_POLL_INTERVAL', .08),
              redirect_stdout(StringIO()) as captured):
            result = D.run_private([TEST_PYTHON, '-c',
                "import time;print('PRIVATE_SECRET');time.sleep(.35)"],
                timeout=2, stage='TEST')
        self.assertEqual(result.returncode, 0)
        self.assertIn('PRIVATE_SECRET', result.stdout)
        self.assertIn('[WPR TEST] still running', captured.getvalue())
        self.assertNotIn('PRIVATE_SECRET', captured.getvalue())

    def test_wpr_idle_parser_recognizes_user_version_and_rejects_unknown(self):
        self.assertEqual(D._wpr_status_category('WPR is not recording'), 'idle')
        self.assertEqual(D._wpr_status_category('WPR recording is in progress'), 'active')
        self.assertEqual(D._wpr_status_category('WPR something else'), 'unknown')

    def test_run_preflight_failure_invalidates_stale_manifest(self):
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder/'preflight.json').write_text('{"ready": true}')
            with (patch.object(D, 'diagnostic_home', return_value=folder),
                  patch.object(D, 'validate_home_and_deno', return_value=(None,folder,folder/'deno','ready')),
                  patch.object(D, 'preflight', return_value=D.Preflight(False, 'failure', admin=True, disk_gb=11)),
                  patch.object(D.shutil, 'which', return_value='wpr.exe'),
                  patch.object(D.shutil, 'disk_usage', return_value=types.SimpleNamespace(free=11*GB)),
                  patch.object(D, 'elevated', return_value=True),
                  redirect_stdout(StringIO()) as output):
                status = D.run_preflight()
            self.assertEqual(status, 2)
            self.assertFalse((folder/'preflight.json').exists())
            self.assertIn('PREFLIGHT: NOT READY', output.getvalue())
            self.assertIn('[WPR START]', output.getvalue())


    def test_preflight_real_subprocess_wpr_emulator_completes_and_cleans_up(self):
        """Exercise actual Popen/wait/tempfile/phase logic without Windows WPR."""
        if os.name == 'nt':
            self.skipTest('POSIX executable script for offline integration')
        from contextlib import redirect_stdout
        from io import StringIO
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            executable = root / 'fake-wpr'
            recording = root / 'recording'
            executable.write_text('''#!/usr/bin/env python3
import sys
from pathlib import Path
state = Path(__file__).with_name('recording')
a = sys.argv[1:]
if '-status' in a:
    print('WPR recording is in progress' if state.exists() else 'WPR is not recording')
elif '-profiles' in a:
    print('CPU DiskIO FileIO Registry Network Minifilter')
elif '-start' in a:
    state.write_text('private-state')
elif '-stop' in a:
    Path(a[a.index('-stop')+1]).write_bytes(b'PRIVATE-ETL-DATA')
    state.unlink()
elif '-cancel' in a:
    state.unlink(missing_ok=True)
else:
    raise SystemExit(2)
''', encoding='utf-8')
            executable.chmod(0o755)
            with redirect_stdout(StringIO()) as captured:
                result = D.preflight(str(executable), admin=True, free_bytes=10*GB,
                                     wpa_available=False, check_tools=False)
            self.assertTrue(result.ok, result.reason)
            self.assertFalse(recording.exists())
            self.assertIn('5/5 status-after', captured.getvalue())
            self.assertIn('all checks passed', captured.getvalue())
            self.assertNotIn('private-state', captured.getvalue())
            self.assertNotIn('PRIVATE-ETL-DATA', captured.getvalue())

    def test_subprocess_with_inherited_child_output_does_not_block(self):
        """Grandchild holds stdout open; our wait must not wait for that child."""
        import time
        with tempfile.TemporaryDirectory() as tmp:
            sentinel = Path(tmp) / 'release-child'
            grandchild = ("import time,pathlib; "
                          f"p=pathlib.Path({str(sentinel)!r}); "
                          "[(time.sleep(.05)) for _ in range(120) if not p.exists()]")
            parent = ("import subprocess,sys; "
                      f"subprocess.Popen([sys.executable,'-c',{grandchild!r}],"
                      "stdout=sys.stdout,stderr=sys.stderr,stdin=subprocess.DEVNULL); "
                      "print('WPR is not recording')")
            started = time.monotonic()
            try:
                out = D.run_private([TEST_PYTHON, '-c', parent], timeout=3)
            finally:
                sentinel.touch()  # Release only our test's descendant.
                time.sleep(.2)
            self.assertEqual(out.returncode, 0)
            self.assertIn('WPR is not recording', out.stdout)
            self.assertLess(time.monotonic()-started, 2.9)

    def test_existing_preflight_manifest_version_one_is_invalidated(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp)
            D.save_preflight(D.Preflight(True, 'ready', D.PROFILES_CORE), path)
            self.assertEqual(D.read_preflight(path), D.PROFILES_CORE)
            payload = json.loads((path / 'preflight.json').read_text())
            payload['version'] = 1
            (path / 'preflight.json').write_text(json.dumps(payload))
            self.assertEqual(D.read_preflight(path), ())



if __name__ == '__main__':
    unittest.main()
