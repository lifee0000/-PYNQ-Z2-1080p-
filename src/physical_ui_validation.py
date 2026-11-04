"""Explicit real GUI + real board exercise; never replay recorded output pixels."""
from pathlib import Path
import ctypes,json,time
from ctypes import wintypes
from PIL import ImageGrab

def run(folder,source):
    import gui
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    source=Path(source).resolve();assert source.is_file()
    target=folder/'gui_physical_preview.mp4'
    assert not Path(str(target)+'.json').exists()
    report=dict(status='RUNNING',scope='ACTUAL_TK_GUI_PHYSICAL_FPGA_NO_REPLAY',source=str(source),screenshots=[])
    errors=[];began=time.monotonic();started=False;captured=False;cancelling=False;session_box={}
    def hook(root,state):
        nonlocal started,captured,cancelling
        def save():(folder/'gui_physical.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        def snapshot(name):
            user=ctypes.windll.user32
            user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
            user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
            rect=wintypes.RECT();hwnd=user.GetAncestor(root.winfo_id(),2)
            assert user.GetWindowRect(hwnd,ctypes.byref(rect))
            path=folder/(name+'.png')
            ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom),all_screens=True).save(path)
            report['screenshots'].append(path.name);save()
        old=gui.filedialog.askopenfilename
        try:
            gui.filedialog.askopenfilename=lambda **kwargs:str(source)
            state['select_source']()
        finally:gui.filedialog.askopenfilename=old
        def tick():
            nonlocal started,captured,cancelling
            try:
                if not started and str(state['start_button'].cget('state'))=='normal':
                    state['output'].set(str(target));started=True
                    state['start_button'].invoke()
                if state['images'][1] is not None and not captured:
                    captured=True;root.after(500,lambda:snapshot('01_actual_preview'))
                result_file=Path(str(target)+'.json')
                if result_file.is_file():
                    try:result=json.loads(result_file.read_text(encoding='utf-8'))
                    except json.JSONDecodeError:result={}
                    cleanup=result.get('board_cleanup',{})
                    if cleanup.get('status') in ('STOPPED_DMA_HALTED_CORE_RESET','KEPT_FOR_NEXT_VIDEO'):
                        assert result['status']=='PASS' and result['frames']>0 and captured
                        assert result['pixel_algorithm_execution']=='FPGA' and result['playback_pacing']=='MAX_THROUGHPUT'
                        assert result['trace_written'] and result['output_video_written']
                        assert result['capabilities'].get('return_lossless') is True
                        report.update(status='PASS',frames=result['frames'],processing_fps=result['processing_fps'],
                            source_rate=result['source_rate'],playback_pacing=result['playback_pacing'],
                            preview_notifications=result['preview_notifications'],identity=result['identity'],cleanup=cleanup)
                        report['display_metrics']=dict(state['display_metrics'])
                        # The window's own close handler releases a board kept for the next video.
                        save();root.after(700,lambda:snapshot('02_completed'))
                        root.after(1400,lambda:root.tk.call(root.protocol('WM_DELETE_WINDOW')));return
                if time.monotonic()-began>180 and not cancelling:
                    cancelling=True;state['cancel_button'].invoke()
                    raise TimeoutError('GUI deadline reached; requested cooperative cancellation')
                root.after(100,tick)
            except BaseException as exc:
                report.update(status='FAIL',error=repr(exc));errors.append(exc);save()
                if not started:root.destroy()
                else:
                    state['cancel_button'].invoke()
                    # The normal GUI close handler waits for native cleanup.
                    command=root.protocol('WM_DELETE_WINDOW')
                    root.tk.call(command)
        session_box['session']=state['board_session']
        root.after(100,tick)
    gui._UI_CHECK_HOOK=hook
    try:gui.main()
    finally:gui._UI_CHECK_HOOK=None
    session=session_box.get('session')
    if session is not None:
        report['window_release']=dict(last_release=session.last_release,still_active=session.active)
        if report.get('cleanup',{}).get('status')=='KEPT_FOR_NEXT_VIDEO':
            from session_receipts import validate_release_receipt
            saved=json.loads(Path(str(target)+'.json').read_text(encoding='utf-8'))
            issues=validate_release_receipt(saved,target,Path(str(target)+'.frames.jsonl'))
            report['final_release_receipt']=dict(status='PASS' if not issues else 'FAIL',issues=issues)
            if issues or (session.last_release or {}).get('status')!='STOPPED_DMA_HALTED_CORE_RESET' or session.active:
                report.update(status='FAIL',error='Final release or its saved receipt was not confirmed')
        (folder/'gui_physical.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    if errors:raise RuntimeError(str(errors[0]))
    assert report['status']=='PASS'
