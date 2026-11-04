"""Actual Tk window QA. Uses recorded FPGA images; no hardware processing."""
from pathlib import Path
import json,time
from PIL import Image,ImageGrab


def check(folder,fixtures):
    import gui
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    fixtures=Path(fixtures).resolve()
    source=fixtures/'public_sources/FourPeople.webm'
    original=fixtures/'results/upgrade_20261024/FourPeople_FPGA_frames/0000_source.png'
    processed=fixtures/'results/upgrade_20261024/FourPeople_FPGA_frames/0000_fpga.png'
    assert source.is_file() and original.is_file() and processed.is_file()
    result=dict(status='RUNNING',scope='REAL_GUI_RECORDED_FRAME_REPLAY_ONLY',
        no_board_connection=True,checks=[],screenshots=[])
    errors=[]

    def run(root,state):
        try:
            def update():
                until=time.monotonic()+.3
                while time.monotonic()<until:root.update();time.sleep(.015)

            def snapshot(name):
                update()
                import ctypes
                from ctypes import wintypes
                user=ctypes.windll.user32
                user.GetAncestor.argtypes=[wintypes.HWND,wintypes.UINT];user.GetAncestor.restype=wintypes.HWND
                user.GetWindowRect.argtypes=[wintypes.HWND,ctypes.POINTER(wintypes.RECT)]
                rect=wintypes.RECT();hwnd=user.GetAncestor(root.winfo_id(),2)
                assert user.GetWindowRect(hwnd,ctypes.byref(rect))
                target=folder/(name+'.png')
                ImageGrab.grab(bbox=(rect.left,rect.top,rect.right,rect.bottom),all_screens=True).save(target)
                result['screenshots'].append(target.name)

            def geometry(name):
                root.update()
                bounds=[];rx,ry=root.winfo_rootx(),root.winfo_rooty()
                rw,rh=root.winfo_width(),root.winfo_height()
                for widget in [*state['canvases'],state['start_button'],state['cancel_button'],*state['chooser_buttons']]:
                    x,y,w,h=widget.winfo_rootx(),widget.winfo_rooty(),widget.winfo_width(),widget.winfo_height()
                    assert x>=rx and y>=ry and x+w<=rx+rw+1 and y+h<=ry+rh+1,(name,x,y,w,h,rx,ry,rw,rh)
                    bounds.append(dict(x=x-rx,y=y-ry,width=w,height=h))
                assert abs(bounds[0]['width']-bounds[1]['width'])<=1
                assert min(bounds[i]['width'] for i in (0,1))>=250
                assert min(bounds[i]['height'] for i in (0,1))>=140
                assert bounds[0]['x']+bounds[0]['width']<=bounds[1]['x']
                result['checks'].append(dict(name=name,window=[rw,rh],bounds=bounds))

            root.geometry('1240x900');update();geometry('normal_idle');snapshot('01_idle')
            old_dialog=gui.filedialog.askopenfilename
            try:
                gui.filedialog.askopenfilename=lambda **kwargs:str(source)
                state['select_source']()
            finally:gui.filedialog.askopenfilename=old_dialog
            limit=time.monotonic()+15
            while state['images'][0] is None:
                root.update();time.sleep(.025)
                assert time.monotonic()<limit,'Imported first frame not shown'
            assert state['images'][1] is None,'Result was populated without processing'
            geometry('imported_first_frame');snapshot('02_imported')
            state['backend'].set(gui.BACKENDS[1] if hasattr(gui,'BACKENDS') else '离线 CPU 参考（无需开发板）')
            state['change_backend']();root.update()
            assert state['headings'][1].cget('text')=='CPU 参考结果'
            state['backend'].set('FPGA 实板（需要开发板）');state['change_backend']();root.update()
            assert state['headings'][1].cget('text')=='FPGA 处理结果'
            # Only replay previously recorded true FPGA pixels. Never call a
            # software enhancement backend and present it as live board output.
            state['images'][:]=[Image.open(original).convert('RGB'),Image.open(processed).convert('RGB')]
            state['status'].set('界面检查：回放此前保存的同帧 FPGA 结果，本次未连接开发板。')
            state['redraw']();geometry('recorded_pair');snapshot('03_recorded_pair')
            root.geometry('1000x760');update();geometry('compact_recorded_pair');snapshot('04_compact')
            result['status']='PASS'
        except BaseException as exc:
            result.update(status='FAIL',error=str(exc));errors.append(exc)
        finally:
            (folder/'ui_check.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
            root.destroy()

    gui._UI_CHECK_HOOK=run
    try:gui.main()
    finally:gui._UI_CHECK_HOOK=None
    if errors:raise RuntimeError('GUI check failed: '+str(errors[0]))
    print(json.dumps(dict(status='PASS',checks=len(result['checks']),no_board_connection=True)))
