"""BoardSession keeps one board service between videos; no network is used."""
from pathlib import Path
from unittest import mock
import json, tempfile, unittest
import board_link
from board_link import BoardSession, ManagedBoard, process_managed

IDENTITY = {'manifest_sha256': 'x'}


class FakeBoard:
    made = []

    def __init__(self, host, password, port=5010, poll_us=100, lease_seconds=120):
        self.host, self.port, self.poll_us, self.lease_seconds = host, port, poll_us, lease_seconds
        self.identity = IDENTITY; self.owned = None; self.attached = False
        self.starts = self.stops = 0; self.fail_stop = False; self.fail_start = None
        FakeBoard.made.append(self)

    def start(self):
        self.starts += 1
        if self.fail_start == 'before_owned': raise OSError('jupyter unreachable')
        self.owned = dict(owner='o')
        if self.fail_start == 'reply_lost': raise TimeoutError('reply lost')
        return dict(status='STARTED_TEMPORARY_MATCHED_FPGA_SERVICE', owned=True)

    def stop(self):
        self.stops += 1
        if self.fail_stop: raise OSError('network down')
        self.owned = None
        return dict(status='STOPPED_DMA_HALTED_CORE_RESET')


class Probe:
    def __init__(self): self.state = 'IDLE'; self.down = False; self.calls = 0

    def __call__(self, host, port):
        self.calls += 1
        if self.down: raise ConnectionRefusedError('closed')
        return dict(state=self.state, backend='FPGA_MMIO', identity=IDENTITY)


def session():
    FakeBoard.made.clear(); probe = Probe()
    return BoardSession(factory=FakeBoard, probe=probe), probe


class BoardSessionTest(unittest.TestCase):
    def test_second_video_reuses_the_kept_service(self):
        s, probe = session()
        board, setup = s.acquire('h', 'p', 5010, 20)
        self.assertEqual(setup['status'], 'STARTED_TEMPORARY_MATCHED_FPGA_SERVICE')
        self.assertEqual(board.lease_seconds, BoardSession.LEASE_SECONDS)
        self.assertEqual(s.keep('h', 5010)['status'], 'KEPT_FOR_NEXT_VIDEO')
        self.assertIsNotNone(s.idle_seconds())
        again, setup = s.acquire('h', 'p', 5010, 20)
        self.assertIs(again, board); self.assertEqual(setup['status'], 'REUSED_KEPT_SERVICE')
        self.assertEqual((board.starts, board.stops), (1, 0)); self.assertIsNone(s.idle_seconds())

    def test_service_ended_by_its_lease_is_started_again(self):
        s, probe = session()
        first, _ = s.acquire('h', 'p', 5010, 20); s.keep('h', 5010)
        probe.down = True
        second, setup = s.acquire('h', 'p', 5010, 20)
        self.assertIsNot(second, first); self.assertEqual(first.stops, 1)
        self.assertEqual(setup['status'], 'STARTED_TEMPORARY_MATCHED_FPGA_SERVICE')

    def test_faulted_service_is_stopped_and_replaced(self):
        s, probe = session()
        first, _ = s.acquire('h', 'p', 5010, 20)
        probe.state = 'FAULT_LATCHED'
        second, _ = s.acquire('h', 'p', 5010, 20)
        self.assertIsNot(second, first); self.assertEqual(first.stops, 1)

    def test_other_host_releases_the_kept_service_first(self):
        s, probe = session()
        first, _ = s.acquire('h', 'p', 5010, 20)
        second, _ = s.acquire('other', 'p', 5010, 20)
        self.assertEqual(first.stops, 1); self.assertEqual(second.host, 'other')

    def test_keep_releases_a_service_that_is_not_idle(self):
        s, probe = session()
        board, _ = s.acquire('h', 'p', 5010, 20)
        probe.state = 'FAULT_LATCHED'
        self.assertEqual(s.keep('h', 5010)['status'], 'STOPPED_DMA_HALTED_CORE_RESET')
        self.assertFalse(s.active)

    def test_unconfirmed_stop_keeps_the_owner_for_a_retry(self):
        s, probe = session()
        board, _ = s.acquire('h', 'p', 5010, 20); board.fail_stop = True
        with self.assertRaises(OSError): s.release()
        self.assertTrue(s.active and s.release_pending)
        self.assertEqual(s.last_release['status'], 'STOP_NOT_CONFIRMED')
        board.fail_stop = False
        self.assertEqual(s.release()['status'], 'STOPPED_DMA_HALTED_CORE_RESET')
        self.assertFalse(s.active or s.release_pending)
        self.assertEqual(s.release()['status'], 'NO_OWNED_SERVICE')

    def test_failed_start_without_a_service_leaves_nothing_to_stop(self):
        s, probe = session()
        with mock.patch.object(FakeBoard, 'start', lambda self: (_ for _ in ()).throw(OSError('down'))):
            with self.assertRaises(OSError): s.acquire('h', 'p', 5010, 20)
        self.assertFalse(s.active)

    def test_lost_start_reply_keeps_the_owner_for_release(self):
        s, probe = session()
        real = FakeBoard.start
        def lost(self): self.fail_start = 'reply_lost'; return real(self)
        with mock.patch.object(FakeBoard, 'start', lost):
            with self.assertRaises(TimeoutError): s.acquire('h', 'p', 5010, 20)
        self.assertTrue(s.active and s.release_pending)
        self.assertEqual(s.release()['status'], 'STOPPED_DMA_HALTED_CORE_RESET')

    def test_warm_starts_once_and_leaves_the_idle_clock_of_a_kept_service(self):
        s, probe = session()
        self.assertEqual(s.warm('h', 'p', 5010, 20)['status'], 'STARTED_TEMPORARY_MATCHED_FPGA_SERVICE')
        since = s.idle_since; self.assertIsNotNone(since)
        self.assertEqual(s.warm('h', 'p', 5010, 20)['status'], 'REUSED_KEPT_SERVICE')
        self.assertEqual(s.idle_since, since); self.assertEqual(len(FakeBoard.made), 1)


class ProcessManagedTest(unittest.TestCase):
    def test_cancelled_trace_without_success_flags_gets_a_final_receipt(self):
        from session_receipts import validate_release_receipt
        s,probe=session();s.warm('h','p',5010,20);board=FakeBoard.made[0]
        board.owned={'owner':'a'*32}
        def stopped():
            board.owned=None
            return dict(status='STOPPED_DMA_HALTED_CORE_RESET',pid_gone=True,temporary_files_removed=True,
                reset_gpio=0,registers=dict(mm2s_status=1,s2mm_status=1,mm2s_control=0,s2mm_control=0))
        board.stop=stopped
        with tempfile.TemporaryDirectory() as folder:
            out=Path(folder)/'cancel.mp4';trace=Path(str(out)+'.frames.jsonl')
            def cancelled(*args,**kw):
                trace.write_text('{"frame_id":0}\n',encoding='utf-8')
                return dict(status='CANCELLED',frames=1,identity=IDENTITY,trace_frames=True)
            with mock.patch('run_video.process',cancelled):
                result=process_managed('in.mp4',out,host='h',poll_us=20,session=s)
            self.assertFalse(result['output_video_written']);self.assertTrue(result['trace_written'])
            self.assertEqual(s.receipts.pending_count,1)
            s.release();data=json.loads(Path(str(out)+'.json').read_text(encoding='utf-8'))
            self.assertEqual(validate_release_receipt(data,out,trace),[])

    def run_one(self, s, status=None, error=None):
        def fake_process(source, output, **options):
            if error: raise error
            return dict(status=status, frames=10)
        folder = Path(tempfile.mkdtemp()); out = folder/'o.mp4'
        with mock.patch('run_video.process', fake_process):
            try: result = process_managed('in.mp4', str(out), host='h', poll_us=20, session=s)
            except BaseException as exc: return exc, None
        return result, json.loads(Path(str(out)+'.json').read_text(encoding='utf-8'))

    def test_finished_and_cancelled_runs_keep_the_board(self):
        s, probe = session()
        result, report = self.run_one(s, 'PASS')
        self.assertEqual(report['board_cleanup']['status'], 'KEPT_FOR_NEXT_VIDEO')
        self.assertEqual(report['board_setup']['status'], 'STARTED_TEMPORARY_MATCHED_FPGA_SERVICE')
        self.assertEqual(set(report['lifecycle_seconds']), {'board_ready', 'pixels_done', 'board_kept_or_stopped'})
        result, report = self.run_one(s, 'CANCELLED')
        self.assertEqual(report['board_setup']['status'], 'REUSED_KEPT_SERVICE')
        self.assertEqual(report['board_cleanup']['status'], 'KEPT_FOR_NEXT_VIDEO')
        self.assertEqual((FakeBoard.made[0].starts, FakeBoard.made[0].stops), (1, 0))

    def test_failed_run_stops_the_board(self):
        s, probe = session()
        result, report = self.run_one(s, 'FAIL')
        self.assertEqual(report['board_cleanup']['status'], 'STOPPED_DMA_HALTED_CORE_RESET')
        self.assertFalse(s.active)
        exc, _ = self.run_one(s, error=RuntimeError('socket'))
        self.assertIsInstance(exc, RuntimeError); self.assertFalse(s.active)
        self.assertEqual(FakeBoard.made[1].stops, 1)

    def test_unconfirmed_stop_after_a_failure_fails_the_run(self):
        s, probe = session()
        s.acquire('h', 'p', 5010, 20); FakeBoard.made[0].fail_stop = True
        result, report = self.run_one(s, 'FAIL')
        self.assertEqual(report['board_cleanup']['status'], 'STOP_NOT_CONFIRMED')
        self.assertEqual(report['board_cleanup']['idle_lease_seconds'], BoardSession.LEASE_SECONDS)
        self.assertTrue(s.release_pending)


class ManagedBoardLeaseTest(unittest.TestCase):
    def test_video_origin_distinguishes_prewarmed_first_use_from_hot_reuse(self):
        s,probe=session();s.warm('h','p',5010,20)
        _,first=s.acquire('h','p',5010,20,for_video=True)
        self.assertEqual(first['service_origin'],'PREWARMED_FIRST_USE');self.assertEqual(first['video_index'],1)
        s.keep('h',5010)
        _,second=s.acquire('h','p',5010,20,for_video=True)
        self.assertEqual(second['service_origin'],'REUSED_PREVIOUS_VIDEO');self.assertEqual(second['video_index'],2)

    def test_new_service_starts_a_new_video_index(self):
        s,probe=session();_,first=s.acquire('h','p',5010,20,for_video=True)
        self.assertEqual(first['service_origin'],'COLD_START')
        s.release();_,again=s.acquire('h','p',5010,20,for_video=True)
        self.assertEqual(again['service_origin'],'COLD_START');self.assertEqual(again['video_index'],1)

    def test_lease_is_bounded_and_reaches_the_guard(self):
        with self.assertRaises(ValueError): ManagedBoard(lease_seconds=601)
        self.assertEqual(ManagedBoard().lease_seconds, 120)
        self.assertIn("'--idle-seconds',str(c.get('idle_seconds',120))", board_link.START_CODE)



class FakeTerminalSocket:
    """Echoes the typed command line like a pty, then prints `output` and the exit marker."""
    def __init__(self, output, status=0, missing=False):
        self.output, self.status, self.missing = output, status, missing; self.queue = [['setup', {}]]; self.sent = []

    def send(self, raw):
        command = json.loads(raw)[1]; self.sent.append(command)
        nonce = command.split(';', 1)[0].split('=', 1)[1]
        done = f'P6R_MISSING_{nonce}' if self.missing else f'P6R_EXIT_{nonce}={self.status}'
        self.queue += [['stdout', command + '\n\x1b[?2004l\r'], ['stdout', self.output], ['stdout', done + '\r\n'], ['disconnect', 1]]

    def settimeout(self, value): pass
    def recv(self): return json.dumps(self.queue.pop(0))
    def close(self): pass


class FakeClient:
    def __init__(self, ws=None, fail=None):
        self.ws, self.fail, self.calls, self.files = ws, fail, [], {}

    def login(self, password): return {'kernelspecs': {'python3': {}}}

    def json_request(self, method, path, data=None, expected=(200,)):
        self.calls.append((method, path))
        if self.fail == method + ' ' + path.split('/')[1]: raise board_link.JupyterError('HTTP 403 for ' + path)
        if path.startswith('api/contents/'): self.files[path[13:]] = data; return {}
        return {'name': '7'}

    def connect_terminal(self, name, timeout): return self.ws

    def request(self, method, path, **kw): self.calls.append((method, path)); return b''


class TerminalChannelTest(unittest.TestCase):
    def board(self, client, channel='auto'):
        b = ManagedBoard(channel=channel); b.client = client; return b

    def test_start_code_runs_from_an_uploaded_file_with_the_runtime_beside_it(self):
        ws = FakeTerminalSocket('__REVIEW_RESULT__={"status": "OK"}\r\n'); c = FakeClient(ws); b = self.board(c)
        self.assertEqual(b.run('c=1;blob=__BLOB__\nprint(1)', 5, payload=b'zip'), {'status': 'OK'})
        self.assertEqual(b.last_channel, 'TERMINAL')
        script = [k for k in c.files if k.endswith('.py')][0]; archive = script[:-3] + '.zip'
        self.assertIn('blob=_blob', c.files[script]['content']); self.assertTrue(c.files[script]['content'].startswith(board_link.TERMINAL_PRELUDE))
        self.assertEqual(c.files[archive]['format'], 'base64')
        self.assertIn('python3 -I -u ' + ManagedBoard.NOTEBOOK_ROOT + '/' + script, ws.sent[0])
        # The terminal and both uploads are removed afterwards.
        self.assertIn(('DELETE', 'api/terminals/7'), c.calls)
        self.assertIn(('DELETE', 'api/contents/' + script), c.calls); self.assertIn(('DELETE', 'api/contents/' + archive), c.calls)

    def test_echoed_command_line_is_not_taken_for_the_result_or_exit(self):
        ws = FakeTerminalSocket('Traceback ...\r\nAssertionError: Another FPGA program is running\r\n', status=1)
        b = self.board(FakeClient(ws))
        with self.assertRaisesRegex(RuntimeError, '(?s)exit 1.*Another FPGA program'): b.run('x', 5)

    def test_unusable_terminal_falls_back_to_the_kernel_with_the_payload_inline(self):
        b = self.board(FakeClient(fail='POST terminals'))
        with mock.patch.object(ManagedBoard, 'execute', return_value={'status': 'OK'}) as execute:
            self.assertEqual(b.run('blob=__BLOB__', 5, payload=b'zip'), {'status': 'OK'})
        self.assertEqual(execute.call_args[0][0], "blob=base64.b64decode('emlw',validate=True)")
        self.assertEqual(b.last_channel, 'KERNEL'); self.assertIn('HTTP 403', b.channel_record()['terminal_fallback'])

    def test_missing_upload_falls_back_but_a_failed_script_does_not(self):
        b = self.board(FakeClient(FakeTerminalSocket('', missing=True)))
        with mock.patch.object(ManagedBoard, 'execute', return_value={'status': 'OK'}) as execute:
            b.run('x', 5); self.assertEqual(execute.call_count, 1)
        b = self.board(FakeClient(FakeTerminalSocket('', status=2)))
        with mock.patch.object(ManagedBoard, 'execute') as execute:
            with self.assertRaises(RuntimeError): b.run('x', 5)
            execute.assert_not_called()

    def test_forced_terminal_channel_never_uses_a_kernel(self):
        b = self.board(FakeClient(fail='PUT contents'), channel='terminal')
        with mock.patch.object(ManagedBoard, 'execute') as execute:
            with self.assertRaises(board_link.TerminalUnavailable): b.run('x', 5, payload=b'z')
            execute.assert_not_called()
        with self.assertRaises(ValueError): ManagedBoard(channel='ssh')

    def test_board_code_takes_the_payload_by_placeholder_and_stop_avoids_pynq(self):
        self.assertIn('blob=__BLOB__', board_link.START_CODE); self.assertNotIn('__PAYLOAD__', board_link.START_CODE)
        self.assertNotIn('from pynq', board_link.STOP_CODE); self.assertIn("os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)", board_link.STOP_CODE)
        for code in (board_link.START_CODE, board_link.STOP_CODE):
            compile(board_link.TERMINAL_PRELUDE + code.replace('__CONTEXT__', '{}').replace('__BLOB__', '_blob'), 'board', 'exec')



class LeanLaunchTest(unittest.TestCase):
    def launcher(self):
        code = board_link.START_CODE; namespace = {}
        exec(code[code.index('LEAN_LAUNCH="""'):code.index('launch=[')], namespace)
        return namespace['LEAN_LAUNCH']

    def test_launcher_runs_the_script_as_if_started_directly(self):
        import subprocess, sys
        with tempfile.TemporaryDirectory() as folder:
            script = Path(folder)/'native'/'board_bootstrap.py'; script.parent.mkdir()
            script.write_text('import json,sys\nprint(json.dumps([__name__,__file__,sys.argv,sys.path[0]]))\n', encoding='utf-8')
            done = subprocess.run([sys.executable, '-u', '-c', self.launcher(), str(script), '--manifest', 'm.json'],
                                  capture_output=True, text=True, cwd=folder, timeout=60)
            self.assertEqual(done.returncode, 0, done.stderr)
            name, file, argv, first = json.loads(done.stdout.splitlines()[-1])
            self.assertEqual((name, Path(file), argv[1:]), ('__main__', script, ['--manifest', 'm.json']))
            self.assertEqual(Path(argv[0]), script); self.assertEqual(Path(first), script.parent.resolve())

    def test_bootstrap_path_stays_its_own_argument_and_lean_can_be_switched_off(self):
        code = board_link.START_CODE
        self.assertIn("launch=['python3','-u']+(['-c',LEAN_LAUNCH] if c.get('native_env',{}).get('P6_LEAN_PYNQ')!='0' else [])", code)
        self.assertIn("child=subprocess.Popen(launch+[str(root/'native/board_bootstrap.py'),'--manifest',", code)
        self.assertEqual(ManagedBoard.NATIVE_ENV_KEYS['P6_LEAN_PYNQ'], ('0', '1'))
        self.assertIn("NAMES=('IPython','tqdm.notebook')", self.launcher())


if __name__ == '__main__':
    unittest.main()
