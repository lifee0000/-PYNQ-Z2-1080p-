"""Real-window GUI acceptance against the physical board; nothing is replayed.

Scenarios, each in a fresh application window with FPGA, managed board, fast
transport and 1080p (the defaults):
  cancel   - press "取消处理" at about 150 processed frames
  close    - press the window close button at about 150 processed frames
  switch   - finish video 1, import video 2 in the same window, finish it
  unplug   - at about 150 frames take the board's eth0 down for 25 s (it comes
             back by itself), then wait for the board's idle lease and run
             video 1 again in the same window (reconnect)
The driver only uses the window's own widgets and close handler. Board-side
state is inspected read-only; the eth0 interruption is the only fault injected.
Writes <folder>/<scenario>.json plus screenshots.
"""
from pathlib import Path
import ctypes, json, threading, time, uuid
from ctypes import wintypes
from PIL import ImageGrab

BOARD = '192.168.2.99'
TRIGGER_FRAMES = 150
UNPLUG = r'''import json,subprocess,sys
# Scheduled while the board is idle: a busy A9 cannot open a new Jupyter kernel in time.
watcher = r"""import glob,sys,time,subprocess
deadline=time.monotonic()+300
while time.monotonic()<deadline:
    dirs=glob.glob('/tmp/pynq_v4_session_*/native/protocol.py')
    if dirs:
        sys.path.insert(0,dirs[0].rsplit('/',1)[0])
        try:
            from protocol import status
            s=status('192.168.2.99',5010,1)
            if s.get('processed',0)>=TRIGGER:
                open('/tmp/p6r_unplug.log','w').write('down processed=%d\n'%s['processed'])
                subprocess.run(['ip','link','set','eth0','down']);time.sleep(25)
                subprocess.run(['ip','link','set','eth0','up']);time.sleep(60)
                subprocess.run(['ip','link','set','eth0','up']);break
        except Exception:pass
    time.sleep(.2)
"""
open('/tmp/p6r_unplug_watch.py','w').write(watcher.replace('TRIGGER','150'))
subprocess.Popen([sys.executable,'/tmp/p6r_unplug_watch.py'],start_new_session=True,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
print('__REVIEW_RESULT__='+json.dumps(dict(scheduled=True)))'''
STATE = r'''from pathlib import Path
import json,socket,tempfile
programs=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        cmd=[a.decode(errors='replace') for a in (p/'cmdline').read_bytes().split(b'\0') if a]
        if any(a.endswith(('native/board_bootstrap.py','native/lease_guard.py')) for a in cmd):programs.append(int(p.name))
    except OSError:pass
temporary=sorted(str(p) for p in Path(tempfile.gettempdir()).glob('pynq_v4_session_*'))
hardware=None
if not programs:
    from pynq import MMIO
    v=MMIO(0x43000000,0x10000);g=MMIO(0x41270000,0x1000)
    hardware=dict(mm2s_status=v.read(4),s2mm_status=v.read(0x34),mm2s_control=v.read(0),s2mm_control=v.read(0x30),reset_gpio=g.read(0))
    hardware['dma_halted']=bool(hardware['mm2s_status']&1 and hardware['s2mm_status']&1 and not (hardware['mm2s_control']|hardware['s2mm_control'])&1)
clean=not programs and not temporary and bool(hardware and hardware['dma_halted'] and hardware['reset_gpio']==0)
print('__REVIEW_RESULT__='+json.dumps(dict(clean=clean,programs=programs,temporary_dirs=temporary,hardware=hardware)))'''


def board(code, timeout=40):
    from jupyter_link import JupyterClient, execute_code
    c = JupyterClient(f'http://{BOARD}:9090', 10); specs = c.login('xilinx')
    k = c.create_kernel(c.choose_kernel(specs, None)); ws = c.connect_channels(k, uuid.uuid4().hex, 12)
    try: return execute_code(ws, code, timeout)
    finally:
        try: ws.close()
        finally: c.delete_kernel(k)


def board_state():
    try: return board(STATE)
    except Exception as exc: return dict(clean=None, error=f'{type(exc).__name__}: {exc}')


def wait_board_clean(limit):
    """Poll read-only until this app's board service and runtime are gone."""
    begin = time.monotonic(); last = None
    while time.monotonic()-begin < limit:
        last = board_state()
        if last.get('clean'): return dict(seconds=round(time.monotonic()-begin, 1), **last)
        time.sleep(10)
    return dict(seconds=round(time.monotonic()-begin, 1), timed_out=True, **(last or {}))


def run(scenario, folder, inputs):
    import gui
    folder = Path(folder).resolve(); folder.mkdir(parents=True, exist_ok=True)
    inputs = [Path(p).resolve() for p in inputs]
    assert scenario in ('cancel', 'close', 'switch', 'unplug') and all(p.is_file() for p in inputs)
    if scenario == 'switch': assert len(inputs) >= 2
    report = dict(scenario=scenario, status='RUNNING', inputs=[str(p) for p in inputs], board_before=board_state(),
                  runs=[], screenshots=[], events=[])
    report_path = folder/f'{scenario}.json'
    assert not report_path.exists(), 'choose a new folder; evidence is never overwritten'
    save = lambda: report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    began = time.monotonic()
    plan = [(inputs[0], 'run1')] + ([(inputs[1], 'run2')] if scenario == 'switch' else []) + ([(inputs[0], 'reconnect')] if scenario == 'unplug' else [])
    state_box = {}

    def event(text, **extra):
        report['events'].append(dict(t=round(time.monotonic()-began, 2), event=text, **extra)); save()

    def hook(root, state):
        state_box.update(root=root, state=state)
        user = ctypes.windll.user32
        user.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]; user.GetAncestor.restype = wintypes.HWND
        user.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]

        def snapshot(name):
            try:
                rect = wintypes.RECT(); hwnd = user.GetAncestor(root.winfo_id(), 2)
                user.GetWindowRect(hwnd, ctypes.byref(rect))
                ImageGrab.grab(bbox=(rect.left, rect.top, rect.right, rect.bottom), all_screens=True).save(folder/f'{scenario}_{name}.png')
                report['screenshots'].append(f'{scenario}_{name}.png'); save()
            except Exception as exc:
                event('screenshot failed', error=str(exc))

        def widgets(widget):
            yield widget
            for child in widget.winfo_children(): yield from widgets(child)
        # Export on, so a cancelled/closed run must also leave no partial video.
        export = [w for w in widgets(root) if w.winfo_class() == 'TCheckbutton' and str(w.cget('text')) == '导出结果视频']
        assert len(export) == 1, 'export checkbox not found'
        if 'selected' not in export[0].state(): export[0].invoke()
        event('export enabled', selected='selected' in export[0].state())

        step = dict(index=0, phase='load', triggered=False, target=None, waited_since=None)

        def load(index):
            source, tag = plan[index]
            old = gui.filedialog.askopenfilename
            try:
                gui.filedialog.askopenfilename = lambda **kw: str(source)
                state['select_source']()
            finally:
                gui.filedialog.askopenfilename = old
            step.update(index=index, phase='wait_loaded', triggered=False, target=folder/f'{scenario}_{tag}.mp4')
            event('import', source=str(source), run=tag)

        def tick():
            try:
                phase = step['phase']; status_text = state['status'].get()
                if phase == 'wait_loaded' and scenario == 'unplug' and plan[step['index']][1] == 'run1' and not step.get('armed'):
                    step['armed'] = True
                    try: event('eth0 watcher armed (down 25 s at %d processed frames)' % TRIGGER_FRAMES, reply=board(UNPLUG, 30))
                    except Exception as exc: event('eth0 watcher failed', error=str(exc)); raise
                if phase == 'wait_loaded' and str(state['start_button'].cget('state')) == 'normal':
                    state['output'].set(str(step['target']))
                    state['start_button'].invoke(); step['phase'] = 'running'
                    event('start pressed', output=str(step['target']))
                elif phase == 'running':
                    frames = state['display_metrics']['last_processed_frame_count']
                    if not step['triggered'] and frames >= TRIGGER_FRAMES and plan[step['index']][1] == 'run1' and scenario in ('cancel', 'close', 'unplug'):
                        step['triggered'] = True; snapshot('before_action')
                        if scenario == 'cancel':
                            state['cancel_button'].invoke(); event('cancel pressed', frames=frames)
                        elif scenario == 'close':
                            event('window close pressed', frames=frames)
                            root.tk.call(root.protocol('WM_DELETE_WINDOW'))
                        else:
                            event('trigger frames reached; board watcher takes eth0 down', frames=frames)
                    result = Path(str(step['target'])+'.json')
                    if result.is_file():
                        try: data = json.loads(result.read_text(encoding='utf-8'))
                        except json.JSONDecodeError: data = {}
                        if 'board_cleanup' in data and str(state['start_button'].cget('state')) == 'normal':
                            run_record = dict(run=plan[step['index']][1], status=data.get('status'), error=data.get('error'),
                                frames=data.get('frames'), processing_fps=data.get('processing_fps'),
                                geometry=data.get('processing_geometry'), output_video_written=data.get('output_video_written'),
                                output_exists=Path(step['target']).exists(), board_cleanup=data.get('board_cleanup'),
                                board_setup=data.get('board_setup'), lifecycle_seconds=data.get('lifecycle_seconds'),
                                window_status=status_text)
                            report['runs'].append(run_record); event('run finished', run=run_record['run'], status=run_record['status'])
                            snapshot(f'{run_record["run"]}_done')
                            step['phase'] = 'after_run'
                elif phase == 'after_run':
                    nxt = step['index']+1
                    if nxt >= len(plan):
                        # The window's own close handler releases a board kept between videos.
                        step['phase'] = 'end'; event('window close requested')
                        root.after(1500, lambda: root.tk.call(root.protocol('WM_DELETE_WINDOW'))); return
                    if plan[nxt][1] == 'reconnect' and step['waited_since'] is None:
                        step['waited_since'] = time.monotonic()
                        def wait_then_continue():
                            report['board_after_unplug'] = wait_board_clean(420); save()
                            event('board state after unplug', clean=report['board_after_unplug'].get('clean'))
                            step['phase'] = 'ready_next'
                        step['phase'] = 'waiting_board'
                        threading.Thread(target=wait_then_continue, daemon=True).start()
                    else:
                        load(nxt)
                elif phase == 'ready_next':
                    load(step['index']+1)
                root.after(200, tick)
            except Exception as exc:
                report.update(status='DRIVER_ERROR', error=repr(exc)); save()
                state['cancel_button'].invoke()
                root.tk.call(root.protocol('WM_DELETE_WINDOW'))

        load(0)
        root.after(300, tick)

    gui._UI_CHECK_HOOK = hook
    closed_at = None
    try:
        gui.main()
        closed_at = time.monotonic()
    except Exception as exc:
        # A window that cannot start (e.g. Tk cannot load init.tcl) must end in a
        # FAIL report; re-raising in the windowed EXE opens a modal dialog and hangs.
        report.update(status='WINDOW_ERROR', error=f'{type(exc).__name__}: {exc}'); save()
    finally:
        gui._UI_CHECK_HOOK = None
    report['window_closed_seconds'] = round((closed_at or time.monotonic())-began, 1)
    session = state_box.get('state', {}).get('board_session')
    if session is not None:
        report['window_release'] = dict(last_release=session.last_release, still_active=session.active)
    if scenario == 'close' and not report['runs']:
        # The window waited for its worker before closing; read the run's own report.
        target = folder/f'{scenario}_run1.mp4'; result = Path(str(target)+'.json')
        data = json.loads(result.read_text(encoding='utf-8')) if result.is_file() else {}
        report['runs'].append(dict(run='run1', status=data.get('status'), error=data.get('error'), frames=data.get('frames'),
                                   board_cleanup=data.get('board_cleanup'), output_exists=target.exists()))
    report['board_after'] = wait_board_clean(300)
    runs = report['runs']
    expect = dict(
        cancel=lambda: len(runs) == 1 and runs[0]['status'] == 'CANCELLED',
        close=lambda: len(runs) == 1 and runs[0]['status'] == 'CANCELLED',
        switch=lambda: len(runs) == 2 and all(r['status'] == 'PASS' and r['output_exists'] for r in runs),
        unplug=lambda: len(runs) == 2 and runs[0]['status'] in ('FAIL', 'CANCELLED') and runs[1]['status'] == 'PASS'
                       and bool(report.get('board_after_unplug', {}).get('clean')))[scenario]
    # A finished or cancelled run keeps the board for the next video; the window must then
    # have stopped it on close through the confirmed stop path.
    statuses = [(r.get('board_cleanup') or {}).get('status') for r in runs if not (scenario == 'unplug' and r['run'] == 'run1')]
    kept = 'KEPT_FOR_NEXT_VIDEO' in statuses
    release = report.get('window_release') or {}
    cleanup_ok = (all(s in ('STOPPED_DMA_HALTED_CORE_RESET', 'KEPT_FOR_NEXT_VIDEO') for s in statuses) and
                  (not kept or ((release.get('last_release') or {}).get('status') == 'STOPPED_DMA_HALTED_CORE_RESET'
                                and release.get('still_active') is False)))
    from session_receipts import validate_release_receipt
    receipt_checks=[]
    for run in runs:
        if (run.get('board_cleanup') or {}).get('status')!='KEPT_FOR_NEXT_VIDEO':continue
        target=folder/f'{scenario}_{run["run"]}.mp4'
        try:
            saved=json.loads(Path(str(target)+'.json').read_text(encoding='utf-8'))
            issues=validate_release_receipt(saved,target,Path(str(target)+'.frames.jsonl'))
        except (OSError,ValueError) as exc:issues=[str(exc)]
        receipt_checks.append(dict(run=run['run'],status='PASS' if not issues else 'FAIL',issues=issues))
    report['final_release_receipts']=receipt_checks
    receipts_ok=all(r['status']=='PASS' for r in receipt_checks)
    report['status'] = 'PASS' if expect() and cleanup_ok and receipts_ok and report['board_after'].get('clean') and report.get('status') not in ('DRIVER_ERROR', 'WINDOW_ERROR') else 'FAIL'
    save()
    return report
