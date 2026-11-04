"""V4 workbench with explicit software-reference and physical FPGA modes."""
from pathlib import Path
import json,os,queue,subprocess,sys,threading,time,tkinter as tk
from collections import deque
from fractions import Fraction
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
from run_video import process,PREVIEW_LIMIT
from offline_video import process as process_offline
from board_link import process_managed,BoardSession
from geometry import OUTPUT_PRESETS
from image_controls_ui import ImageControlsPanel
from image_controls import PRESETS,default_profile_path
from preview_compare import CompareWindow, LivePreviewMode, load_samples
from sync_player import SyncPlayback
from curve_editor import CurveWindow
from signal_curves import save_plan,load_plan,content_rect,clip_region,CurveAnalysis

UI_POLL_INTERVAL_MS=16
PREVIEW_FPS=30
PREVIEW_MAX_WIDTH,PREVIEW_MAX_HEIGHT=PREVIEW_LIMIT
OPTIMIZE_CHOICES=['一键全自动优化（推荐）','自动曝光与去噪（v4）','按所选模式处理']
RESOLUTIONS={f'{w} × {h}（{h}p）':(w,h) for w,h in OUTPUT_PRESETS}

def manual_workspace():
    """Find the project-relative acceptance workspace in source and frozen builds."""
    start=Path(sys.executable).resolve().parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parent
    for parent in (start,*start.parents):
        folder=parent/'manual_tests'
        if (folder/'materials.json').is_file() and (parent/'START.cmd').is_file():
            for name in ('outputs','comparisons'):(folder/name).mkdir(exist_ok=True)
            return folder
        # Delivered folder: 启动程序.cmd with 输入视频 / 输出视频 / 对比截图 beside it.
        if (parent/'启动程序.cmd').is_file() and (parent/PACKAGE_FOLDERS['inputs']).is_dir():
            for name in ('outputs','comparisons'):(parent/PACKAGE_FOLDERS[name]).mkdir(exist_ok=True)
            return parent
    return None
PACKAGE_FOLDERS={'inputs':'输入视频','outputs':'输出视频','comparisons':'对比截图'}
def launch_prewarm_allowed():
    """Interactive use only: the private UI checks drive the board themselves, and some close the
    window without the close handler, which would leave a warmed service to its idle lease. The same
    rule decides whether the window restores and saves the processing choice (workbench choices)."""
    return _UI_CHECK_HOOK is None or getattr(_UI_CHECK_HOOK,'allow_launch_prewarm',False)
def workbench_choices_path():
    """Choices kept between sessions (FPGA or offline processing), beside the image-controls profile."""
    profile=default_profile_path()
    return profile.with_name(profile.stem+'.workbench.json')
def load_workbench_choices():
    try:data=json.loads(workbench_choices_path().read_text(encoding='utf-8'))
    except (OSError,ValueError):return {}
    return data if isinstance(data,dict) and data.get('schema')==1 else {}
def save_workbench_choice(**values):
    path=workbench_choices_path()
    try:
        data=load_workbench_choices();data.update(values,schema=1)
        path.parent.mkdir(parents=True,exist_ok=True);temporary=path.with_name(path.name+'.tmp')
        temporary.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8');os.replace(temporary,path)
    except OSError:pass   # only the remembered choice is lost
def workspace_folder(workspace,kind):
    """inputs / outputs / comparisons of a workspace: manual_tests/<kind>, or the delivered folder's named one."""
    named=workspace/PACKAGE_FOLDERS[kind]
    return named if named.is_dir() and not (workspace/'materials.json').is_file() else workspace/kind

def main():
    if os.name=='nt':
        import ctypes
        try:ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError,OSError):pass
    app=tk.Tk();app.title('PYNQ · FPGA 视频图像增强')
    app.geometry(f'{min(1600,app.winfo_screenwidth()-80)}x{min(1000,app.winfo_screenheight()-100)}')
    app.minsize(980,720);app.configure(bg='#f3f6fb')
    # The two pictures are the point of the window: open maximised.
    if os.name=='nt':
        try:app.state('zoomed')
        except tk.TclError:pass
    style=ttk.Style(app);style.theme_use('clam')
    style.configure('.',font=('Microsoft YaHei UI',9),background='#f3f6fb',foreground='#1c2d45')
    style.configure('TButton',padding=(10,5))
    style.configure('Small.TButton',padding=(7,2))
    style.configure('Tool.TButton',padding=(8,5))
    style.configure('Accent.TButton',background='#2563eb',foreground='white',font=('Microsoft YaHei UI',10,'bold'),padding=(16,6))
    style.map('Accent.TButton',background=[('disabled','#bac9dc'),('active','#1d4ed8')])
    style.configure('TEntry',padding=4)
    style.configure('Card.TFrame',background='white')
    style.configure('Card.TLabel',background='white',font=('Microsoft YaHei UI',10,'bold'))
    style.configure('Stage.TFrame',background='#0b1220')
    style.configure('Stage.TLabel',background='#0b1220',foreground='#e5edf7',font=('Microsoft YaHei UI',13,'bold'))
    style.configure('Hint.TLabel',foreground='#68798e')
    header=ttk.Frame(app,padding=(16,8,16,0));header.pack(fill='x')
    header_text=ttk.Frame(header);header_text.pack(side='left')
    ttk.Label(header_text,text='FPGA 视频增强',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w')
    ttk.Label(header_text,text='导入视频 · 开发板处理 · 左右同帧对比',foreground='#68798e').pack(anchor='w',pady=(2,0))
    # Toolbar: file, start/cancel and the view switches; everything else folds into `body`.
    toolbar=ttk.Frame(app,padding=(16,8,16,6));toolbar.pack(fill='x');toolbar.columnconfigure(1,weight=1)
    source=tk.StringVar();output=tk.StringVar();mode=tk.StringVar(value='5 自适应曝光与保边去噪')
    backend=tk.StringVar(value='FPGA 实板（需要开发板）')
    workspace=manual_workspace()
    save=tk.BooleanVar(value=workspace is not None);compress=tk.BooleanVar(value=True)
    manage=tk.BooleanVar(value=True);board_host=tk.StringVar(value='192.168.2.99');board_password=tk.StringVar(value='xilinx')
    auto=tk.BooleanVar(value=True);serial=tk.BooleanVar(value=False);detail=tk.BooleanVar(value=False);native720=tk.BooleanVar(value=False);quality=tk.StringVar(value='自动（推荐：无损为主，满屏纹理的复杂画面轻度量化保流畅）');resolution=tk.StringVar(value=next(iter(RESOLUTIONS)));status=tk.StringVar(value='导入视频后开始 FPGA 处理，左右同步查看原图与回传画面。')
    events=queue.Queue();preview_events=queue.Queue(maxsize=1)
    cancel=threading.Event();worker=None;photos=[None,None];preview_images=[None,None]
    # Detail preview focus (fx, fy in 0..1 of the frame), shared with run_video while it runs;
    # shown_rects: where each preview image is drawn; shown_window: the last crop and frame size.
    preview_focus=[.5,.5];shown_rects=[None,None];shown_window=dict(window=None,size=None)
    live_preview=LivePreviewMode();comparison=None;last_compare_pair=None
    detail.trace_add('write',lambda *args:live_preview.set(detail.get()))
    load_token=0;chooser_buttons=[];last_frames=0;closing=False;source_ready=False
    # One board service kept between videos while this window is open (board_link.BoardSession).
    board_session=BoardSession();prewarm=None;releaser=None;closer=None;last_release_try=0.;loaded_text=''
    prewarm_started=None;board_wait_started=None;board_waiting=False
    display_metrics=dict(rendered_pairs=0,last_processed_frame_count=0,draw_seconds=0.,timer_resolution_ms=None)
    # (wall time, processed frames) samples for the output's current rate.
    rate_window=deque(maxlen=64)
    body=ttk.Frame(app,padding=(16,2,16,8))
    body.columnconfigure(1,weight=1)
    def new_output(name):
        suffix='_V4_CPU_REF' if backend.get().startswith('离线') else '_V4_FPGA'
        for number in range(1,10000):
            folder=workspace_folder(workspace,'outputs') if workspace is not None else Path(name).parent
            p=folder/(Path(name).stem+suffix+('' if number==1 else f'_{number}')+'.mp4')
            if not any(Path(str(p)+s).exists() for s in ('','.json','.frames.jsonl')):return str(p)
        raise ValueError('请换一个结果文件名。')
    def select_source():
        nonlocal load_token,source_ready,last_compare_pair
        if worker and worker.is_alive():return
        options=dict(filetypes=[('视频','*.mp4 *.mov *.mkv *.avi *.webm'),('所有文件','*.*')])
        if workspace is not None:options['initialdir']=str(workspace_folder(workspace,'inputs'))
        name=filedialog.askopenfilename(**options)
        if name:
            source.set(name);output.set(new_output(name));load_token+=1;token=load_token
            preview_focus[:]=[.5,.5];shown_window.update(window=None,size=None)
            source_ready=False;start_button.configure(state='disabled')
            stop_player();loaded_still[0]=None;progress.update(frames=0,total=0,fps=0.);region_pick.update(region=None,callback=None,start=None)
            preview_images[:]=[None,None];preview_native[0]=False;redraw();status.set('正在读取视频首帧…')
            display_metrics['last_processed_frame_count']=0;rate_window.clear()
            headings[0].configure(text='原始视频')
            headings[1].configure(text='CPU 参考结果' if backend.get().startswith('离线') else 'FPGA 处理结果')
            last_compare_pair=None
            if comparison is not None and comparison.winfo_exists():comparison.clear_live()
            def read_preview():
                try:
                    import av
                    with av.open(name) as video:
                        if not video.streams.video:raise ValueError('文件中没有视频画面。')
                        stream=video.streams.video[0];frame=next(video.decode(stream),None)
                        if frame is None:raise ValueError('视频中没有可读取的帧。')
                        data=dict(token=token,source=frame.to_ndarray(format='rgb24'),
                            width=stream.width,height=stream.height,rate=str(stream.average_rate or stream.guessed_rate or '未知'),count=stream.frames or 0)
                    events.put_nowait(('loaded',data))
                except Exception as exc:events.put_nowait(('load_error',dict(token=token,error=str(exc))))
            threading.Thread(target=read_preview,name='video-first-frame',daemon=True).start()
    def select_output():
        options=dict(defaultextension='.mp4',filetypes=[('MP4','*.mp4'),('MKV','*.mkv')])
        if workspace is not None:options.update(initialdir=str(workspace_folder(workspace,'outputs')),initialfile=Path(output.get()).name or 'result_V4_FPGA.mp4')
        name=filedialog.asksaveasfilename(**options)
        if name:output.set(name)
    import_button=ttk.Button(toolbar,text='导入视频',command=select_source,style='Tool.TButton')
    import_button.grid(row=0,column=0,padx=(0,8));chooser_buttons.append(import_button)
    ttk.Entry(toolbar,textvariable=source,width=1,state='readonly').grid(row=0,column=1,sticky='ew')
    ttk.Label(body,text='输出视频').grid(row=0,column=0,sticky='w',pady=4)
    ttk.Entry(body,textvariable=output,width=1).grid(row=0,column=1,sticky='ew')
    output_button=ttk.Button(body,text='选择位置',command=select_output)
    output_button.grid(row=0,column=2,padx=8);chooser_buttons.append(output_button)
    choices=['0 原图','1 Sobel 轮廓','2 高斯平滑','3 亮度调整','4 锐化','5 自适应曝光与保边去噪']
    ttk.Label(body,text='执行方式').grid(row=1,column=0,sticky='w')
    backend_choice=ttk.Combobox(body,textvariable=backend,values=['FPGA 实板（需要开发板）','离线 CPU 参考（无需开发板）'],state='readonly',width=38)
    backend_choice.grid(row=1,column=1,sticky='w',pady=2)
    ttk.Label(body,text='处理模式').grid(row=2,column=0,sticky='w')
    mode_options=ttk.Frame(body);mode_options.grid(row=2,column=1,sticky='w',pady=2)
    mode_choice=ttk.Combobox(mode_options,textvariable=mode,values=choices,state='readonly',width=22);mode_choice.pack(side='left')
    auto_choice=ttk.Checkbutton(mode_options,text='自动参数',variable=auto);auto_choice.pack(side='left',padx=12)
    # v5 picks per scene between V4 denoise/tone (mode 5) and unsharp mask (mode 4).
    optimize=tk.StringVar(value=OPTIMIZE_CHOICES[0])
    optimize_choice=ttk.Combobox(mode_options,textvariable=optimize,values=OPTIMIZE_CHOICES,state='readonly',width=20);optimize_choice.pack(side='left')
    connection=ttk.Frame(body);connection.grid(row=1,column=2,rowspan=2,sticky='w')
    ttk.Label(connection,text='IP').grid(row=0,column=0,sticky='w',padx=(0,6))
    ttk.Entry(connection,textvariable=board_host,width=16).grid(row=0,column=1,pady=3)
    ttk.Label(connection,text='密码').grid(row=1,column=0,sticky='w',padx=(0,6))
    ttk.Entry(connection,textvariable=board_password,show='*',width=16).grid(row=1,column=1,pady=3)
    options=ttk.Frame(body);options.grid(row=4,column=0,columnspan=3,sticky='w',pady=(5,0))
    first_options=ttk.Frame(options);first_options.pack(anchor='w')
    second_options=ttk.Frame(options);second_options.pack(anchor='w',pady=(4,0))
    save_choice=ttk.Checkbutton(first_options,text='导出结果视频',variable=save);save_choice.pack(side='left')
    manage_choice=ttk.Checkbutton(first_options,text='自动启停开发板',variable=manage);manage_choice.pack(side='left',padx=12)
    serial_choice=ttk.Checkbutton(first_options,text='串行处理',variable=serial);serial_choice.pack(side='left',padx=12)
    compress_choice=ttk.Checkbutton(first_options,text='压缩传输',variable=compress);compress_choice.pack(side='left')
    # Decimated full-frame previews hide pixel-scale sharpening; this shows a 1:1 crop of
    # both sides at the same place, chosen by clicking either preview (default: centre).
    # While processing the stage shows progress; the comparison is played from the files afterwards.
    live_display=tk.BooleanVar(value=False)
    ttk.Checkbutton(second_options,text='处理中显示实时画面',variable=live_display,command=lambda:redraw()).pack(side='left',padx=(0,12))
    detail_choice=ttk.Checkbutton(second_options,text='原像素细节（点击画面选位置）',variable=detail);detail_choice.pack(side='left')
    native_choice=ttk.Checkbutton(second_options,text='720p 素材按原生 720p 处理后放大（更快）',variable=native720);native_choice.pack(side='left',padx=12)
    def open_comparison():
        nonlocal comparison
        if comparison is not None and comparison.winfo_exists():
            comparison.deiconify();comparison.lift();return comparison
        try:samples=load_samples()
        except (OSError,ValueError,KeyError) as exc:
            samples=[];status.set('样张校验失败：'+str(exc))
        comparison=CompareWindow(app,request_detail=lambda enabled:detail.set(enabled),
            request_focus=lambda fx,fy:preview_focus.__setitem__(slice(None),[fx,fy]),samples=samples,
            export_directory=workspace_folder(workspace,'comparisons') if workspace is not None else None)
        if last_compare_pair is not None:comparison.set_live(*last_compare_pair)
        elif samples:
            comparison.sample_choice.current(0);comparison.select_sample()
        return comparison
    compare_button=ttk.Button(toolbar,text='画质对比…',command=open_comparison,style='Tool.TButton')
    compare_button.grid(row=0,column=5,padx=(8,0))
    ttk.Label(body,text='传输质量').grid(row=3,column=0,sticky='w')
    transport_options=ttk.Frame(body);transport_options.grid(row=3,column=1,columnspan=2,sticky='w',pady=4)
    quality_choice=ttk.Combobox(transport_options,textvariable=quality,values=['自动（推荐：无损为主，满屏纹理的复杂画面轻度量化保流畅）','全程无损（画质与原片一致，复杂画面较慢）','精细传输（误差≤1，稍快，平坦处偶见淡斑）','高质量传输（误差≤2，更快，平坦处有淡斑）','极速传输（误差≤4，最快，平坦处有色块）'],state='readonly',width=38);quality_choice.pack(side='left')
    ttk.Label(transport_options,text='输出分辨率').pack(side='left',padx=(16,6))
    resolution_choice=ttk.Combobox(transport_options,textvariable=resolution,values=list(RESOLUTIONS),state='readonly',width=16);resolution_choice.pack(side='left')
    def control_context(event=None):
        image_panel.set_context(int(mode.get().split()[0]),auto.get())
    def restore_auto():
        mode.set(choices[5]);auto.set(True);optimize.set(OPTIMIZE_CHOICES[0])
        if worker and worker.is_alive():
            return '已清除画质微调；本次处理策略保持至结束，下次开始使用全自动。'
        control_context()
    image_panel=ImageControlsPanel(header,on_status=status.set,on_restore=restore_auto)
    image_panel.pack(side='right')
    def select_mode(event=None):
        optimize.set(OPTIMIZE_CHOICES[2])
        if not mode.get().startswith('5 '):auto.set(False)
        control_context()
    def select_optimize(event=None):
        if optimize.get()!=OPTIMIZE_CHOICES[2]:mode.set(choices[5]);auto.set(True)
        control_context()
    def select_auto():
        if not auto.get():optimize.set(OPTIMIZE_CHOICES[2])
        control_context()
    mode_choice.bind('<<ComboboxSelected>>',select_mode)
    optimize_choice.bind('<<ComboboxSelected>>',select_optimize)
    auto_choice.configure(command=select_auto)
    control_context()
    run_options=[auto_choice,save_choice,manage_choice,serial_choice,compress_choice,native_choice]
    run_choices=[mode_choice,optimize_choice,quality_choice,resolution_choice,backend_choice]
    # One line summarising the folded settings, next to the switch that opens them.
    settings_summary=tk.StringVar()
    def summarize(*args):
        parts=[backend.get().split('（')[0],optimize.get().split('（')[0] if auto.get() and optimize.get()!=OPTIMIZE_CHOICES[2] else mode.get()[2:],
               '传输 '+quality.get().split('（')[0],'输出 '+resolution.get().split('（')[0]]
        settings_summary.set('当前设置：'+' · '.join(parts))
    for variable in (backend,optimize,mode,auto,quality,resolution):variable.trace_add('write',summarize)
    summarize()
    settings_open=tk.BooleanVar(value=False)
    def toggle_settings(event=None):
        settings_open.set(not settings_open.get())
        if settings_open.get():body.pack(fill='x',after=toolbar)
        else:body.pack_forget()
        settings_button.configure(text='收起设置 ▴' if settings_open.get() else '设置 ▾')
    settings_button=ttk.Button(toolbar,text='设置 ▾',command=toggle_settings,style='Tool.TButton')
    settings_button.grid(row=0,column=4,padx=(8,0))
    ttk.Label(toolbar,textvariable=settings_summary,style='Hint.TLabel').grid(row=1,column=1,columnspan=6,sticky='w',pady=(4,0))
    status_bar=ttk.Frame(app,padding=(16,4,16,8));status_bar.pack(side='bottom',fill='x')
    stage=ttk.Frame(app,style='Stage.TFrame',padding=(10,8,10,10));stage.pack(fill='both',expand=True)
    previews=stage
    # Cards sit in the middle row; the outer rows take the slack so the titles stay on the pictures.
    previews.columnconfigure(0,weight=1,uniform='preview');previews.columnconfigure(1,weight=1,uniform='preview')
    previews.rowconfigure(0,weight=1);previews.rowconfigure(2,weight=1)
    canvases=[];headings=[];image_items=[None,None]
    # The detail view shows processing pixels 1:1; never stretch it.
    preview_native=[False]
    for index,title in enumerate(('原始视频','FPGA 处理结果')):
        card=ttk.Frame(previews,style='Stage.TFrame')
        card.grid(row=1,column=index,sticky='ew',padx=(0,5) if index==0 else (5,0))
        card.columnconfigure(0,weight=1);card.rowconfigure(1,weight=1)
        heading=ttk.Label(card,text=title,style='Stage.TLabel');heading.grid(row=0,column=0,sticky='w',pady=(0,6));headings.append(heading)
        canvas=tk.Canvas(card,width=480,height=270,bg='#000000',highlightthickness=0)
        canvas.grid(row=1,column=0,sticky='nsew');canvases.append(canvas)
    # Full-screen demo: only the two pictures, their titles and the status line.
    demo=dict(on=False)
    def toggle_demo(event=None):
        demo['on']=not demo['on']
        if demo['on']:
            for widget in (header,toolbar,body,note_label):widget.pack_forget()
            app.attributes('-fullscreen',True);demo_button.configure(text='退出 (Esc)')
            status_hint.set('全屏演示 · 按 Esc 或 F11 退出')
        else:
            app.attributes('-fullscreen',False)
            header.pack(fill='x',before=stage);toolbar.pack(fill='x',before=stage)
            if settings_open.get():body.pack(fill='x',after=toolbar)
            note_label.pack(anchor='w');demo_button.configure(text='全屏 (F11)');status_hint.set('')
    def leave_demo(event=None):
        if demo['on']:toggle_demo()
    demo_button=ttk.Button(toolbar,text='全屏 (F11)',command=toggle_demo,style='Tool.TButton')
    demo_button.grid(row=0,column=6,padx=(8,0))
    app.bind('<F11>',toggle_demo);app.bind('<Escape>',leave_demo)
    # preview_images: the latest frames from processing (model, also read by checks);
    # the stage shows the player's pair, or while processing the first frame and progress.
    loaded_still=[None];player_view=[None];progress=dict(frames=0,total=0,fps=0.);drawn=[None,None];canvas_size=[960,540]
    def shown_image(index):
        if player_view[0] is not None:return player_view[0][index]
        if busy(worker) and not live_display.get():return loaded_still[0] if index==0 else None
        return preview_images[index]
    def fit_stage(event=None):
        # Canvas height follows the video's aspect at the width each side gets, within the stage.
        image=shown_image(0) or shown_image(1)
        aspect=image.height/image.width if image is not None else 9/16
        width=max(1,canvases[0].winfo_width())
        room=stage.winfo_height()-headings[0].winfo_reqheight()-30
        height=max(120,min(room,round(width*aspect)))
        for canvas in canvases:
            if int(canvas.cget('height'))!=height:canvas.configure(height=height)
    stage.bind('<Configure>',fit_stage)
    def redraw(event=None):
        fit_stage()
        canvas_size[:]=[max(64,canvases[0].winfo_width()),max(36,canvases[0].winfo_height())]
        for index,canvas in enumerate(canvases):
            width=max(1,canvas.winfo_width());height=max(1,canvas.winfo_height())
            image=shown_image(index)
            if image is None:
                canvas.delete('all');image_items[index]=None;shown_rects[index]=None;drawn[index]=None
                if index==1 and busy(worker):
                    total=progress['total'];done=progress['frames']
                    share=min(1.,done/total) if total else 0.
                    message=(f'正在处理 {share*100:.0f}%\n' if total else '正在处理\n')+f'已完成 {done}'+(f' / {total}' if total else '')+' 帧'+(f" · {progress['fps']:.1f} 帧/秒" if progress['fps'] else '')+'\n\n完成后在这里与原片同帧播放'
                    bar=min(560,width-80)
                    if total and bar>40:
                        canvas.create_rectangle(width/2-bar/2,height/2+70,width/2+bar/2,height/2+82,outline='#3b4b63',fill='#1b2638')
                        canvas.create_rectangle(width/2-bar/2,height/2+70,width/2-bar/2+bar*share,height/2+82,outline='',fill='#3b82f6')
                    font=('Microsoft YaHei UI',14)
                else:
                    message='尚未导入视频\n点击上方“导入视频”' if index==0 else '处理完成后\n在这里与原片同帧播放'
                    font=('Microsoft YaHei UI',10)
                canvas.create_text(width/2,height/2,text=message,fill='#a5b6cc',justify='center',
                    width=max(80,width-24),font=font)
            else:
                ratio=min(width/image.width,height/image.height)
                if preview_native[0]:ratio=min(ratio,1.)
                size=(max(1,round(image.width*ratio)),max(1,round(image.height*ratio)))
                if drawn[index]==(id(image),size) and image_items[index] is not None:
                    canvas.coords(image_items[index],width/2,height/2);continue
                drawn[index]=(id(image),size)
                resized=image if image.size==size else image.resize(size,Image.Resampling.BILINEAR);photo=photos[index]
                # Same size as the shown picture: paste into it instead of building a new Tk image.
                if image_items[index] is not None and photo is not None and (photo.width(),photo.height())==size:
                    photo.paste(resized);shown_rects[index]=((width-size[0])/2,(height-size[1])/2,size[0],size[1])
                    canvas.coords(image_items[index],width/2,height/2);continue
                photo=ImageTk.PhotoImage(resized)
                if image_items[index] is None:
                    canvas.delete('all')
                    image_items[index]=canvas.create_image(width/2,height/2,image=photo,anchor='center')
                else:
                    canvas.itemconfigure(image_items[index],image=photo)
                    canvas.coords(image_items[index],width/2,height/2)
                photos[index]=photo;shown_rects[index]=((width-size[0])/2,(height-size[1])/2,size[0],size[1])
    def frame_fraction(event,index):
        rect=shown_rects[index]
        if rect is None:return None
        return (min(max((event.x-rect[0])/max(rect[2],1),0.),1.),min(max((event.y-rect[1])/max(rect[3],1),0.),1.))
    # Regions are kept in export pixels. The left picture is the source at its own aspect,
    # which sits in the export's content rectangle (letterbox), so points on either side map
    # through that rectangle (review F3: a portrait source was mapped by plain proportion).
    def player_geometry():
        if player[0] is None:return None
        source_size,export_size=player[0].sizes
        return export_size,content_rect(source_size,export_size)
    def to_export(event,index):
        point=frame_fraction(event,index);geometry=player_geometry()
        if point is None or geometry is None:return None
        (width,height),(cx,cy,cw,ch)=geometry
        return (point[0]*width,point[1]*height) if index==1 else (cx+point[0]*cw,cy+point[1]*ch)
    def draw_region(box=None):
        for canvas in canvases:canvas.delete('region')
        box=box or region_pick.get('region');geometry=player_geometry()
        if box is None or geometry is None:return
        (width,height),(cx,cy,cw,ch)=geometry;x,y,w,h=box
        for index,canvas in enumerate(canvases):
            rect=shown_rects[index]
            if rect is None:continue
            u0,v0,u1,v1=(x/width,y/height,(x+w)/width,(y+h)/height) if index==1 else ((x-cx)/cw,(y-cy)/ch,(x+w-cx)/cw,(y+h-cy)/ch)
            u0,v0,u1,v1=(min(max(value,0.),1.) for value in (u0,v0,u1,v1))
            if u1<=u0 or v1<=v0:continue
            canvas.create_rectangle(rect[0]+u0*rect[2],rect[1]+v0*rect[3],rect[0]+u1*rect[2],rect[1]+v1*rect[3],
                                    outline='#facc15',width=2,dash=(6,3),tags='region')
    def drag_box(start_point,point):
        (x0,y0),(x1,y1)=start_point,point
        return (round(min(x0,x1)),round(min(y0,y1)),round(abs(x1-x0)),round(abs(y1-y0)))
    def region_drag(event,index):
        if region_pick['callback'] is None or region_pick['start'] is None:return
        point=to_export(event,index)
        if point:draw_region(drag_box(region_pick['start'],point))
    def region_release(event,index):
        callback=region_pick['callback']
        if callback is None or region_pick['start'] is None:return
        point=to_export(event,index);start_point=region_pick['start'];region_pick.update(callback=None,start=None)
        if point is None or player[0] is None:return
        box=clip_region(drag_box(start_point,point),player_geometry()[1])
        if box is None or box[2]<16 or box[3]<16:status.set('框太小了或不在画面内，请在视频画面上拖出更大的区域。');draw_region();return
        x,y,w,h=box;region_pick.update(region=box);draw_region()
        status.set(f'已框选区域：x={x} y={y} 宽={w} 高={h}（导出画面像素），曲线窗口正在重新测量。');callback(box)
    def choose_detail(event,index):
        if region_pick['callback'] is not None:
            region_pick['start']=to_export(event,index);return
        # A click on either side moves the 1:1 window of both sides to that point.
        rect=shown_rects[index]
        if rect is None:return
        u=min(max((event.x-rect[0])/max(rect[2],1),0.),1.);v=min(max((event.y-rect[1])/max(rect[3],1),0.),1.)
        window,size=shown_window['window'],shown_window['size']
        if window and size:u,v=(window[0]+u*window[2])/size[0],(window[1]+v*window[3])/size[1]
        preview_focus[:]=[u,v]
        status.set(f'细节位置：画面 {u*100:.0f}% × {v*100:.0f}%'+('' if detail.get() else '（勾选“原像素细节”后生效）'))
    for index,canvas in enumerate(canvases):
        canvas.bind('<Configure>',redraw);canvas.bind('<Button-1>',lambda event,i=index:choose_detail(event,i))
        canvas.bind('<Double-Button-1>',toggle_demo)
        canvas.bind('<B1-Motion>',lambda event,i=index:region_drag(event,i));canvas.bind('<ButtonRelease-1>',lambda event,i=index:region_release(event,i))
    def preview_payload(data):
        source,result=data['source'],data['result']
        if source.shape[1]>PREVIEW_MAX_WIDTH or source.shape[0]>PREVIEW_MAX_HEIGHT:
            step=max(1,(source.shape[1]+PREVIEW_MAX_WIDTH-1)//PREVIEW_MAX_WIDTH,(source.shape[0]+PREVIEW_MAX_HEIGHT-1)//PREVIEW_MAX_HEIGHT)
            return dict(data,source=source[::step,::step].copy(),result=result[::step,::step].copy())
        return data
    def notify(kind,data):
        if kind=='progress':
            # A slow GUI can replace only a preview. All FPGA results still
            # reach the exporter/trace in order; this never drops processing.
            preview=preview_payload(data)
            try:preview_events.put_nowait(preview)
            except queue.Full:
                try:preview_events.get_nowait()
                except queue.Empty:pass
                try:preview_events.put_nowait(preview)
                except queue.Full:pass
        else:events.put_nowait((kind,data))
    def busy(thread):return thread is not None and thread.is_alive()
    def start_prewarm():
        # After an import in FPGA mode, bring the board up while the user is still choosing.
        nonlocal prewarm,prewarm_started
        if busy(prewarm) or busy(worker) or board_session.active:return False
        host,password=board_host.get(),board_password.get()
        def run():
            try:
                board_session.warm(host,password,5010,20)
                events.put_nowait(('board_ready',{}))
            except BaseException as exc:
                events.put_nowait(('board_prewarm_failed',dict(error=str(exc) or type(exc).__name__)))
        prewarm_started=time.perf_counter();prewarm=threading.Thread(target=run,daemon=False);prewarm.start()
        return True
    def start():
        nonlocal worker,last_compare_pair,board_wait_started,board_waiting
        if worker and worker.is_alive():return
        if not source_ready or not output.get():messagebox.showerror('请选择文件','先导入一个可以读取的视频并选择输出位置。');return
        offline=backend.get().startswith('离线')
        target=Path(output.get())
        if any(Path(str(target)+s).exists() for s in ('','.json','.frames.jsonl')):
            messagebox.showerror('请选择新文件名','该位置已经有结果，请选择新的保存文件名。');return
        cancel.clear();rate_window.clear();status.set('运行电脑端 V4 参考算法…' if offline else '连接 V4 FPGA 服务并校验硬件身份…');start_button.configure(state='disabled');backend_choice.configure(state='disabled')
        display_metrics['last_processed_frame_count']=0
        headings[1].configure(text='CPU 参考结果' if offline else 'FPGA 处理结果')
        board_waiting=not offline and manage.get();board_wait_started=time.perf_counter() if board_waiting else None
        for button in chooser_buttons:button.configure(state='disabled')
        stop_player();progress.update(frames=0,fps=0.)
        cancel_button.configure(state='normal');resolution_choice.configure(state='disabled');preview_images[1]=None;redraw()
        input_value,output_value=source.get(),output.get()
        run_output[0]=output_value;set_open_output(None)
        width,height=RESOLUTIONS[resolution.get()]
        one_click=optimize.get()==OPTIMIZE_CHOICES[0] and auto.get()
        if auto.get() and optimize.get()!=OPTIMIZE_CHOICES[2]:mode.set(choices[5])
        control_context()
        for choice in run_choices:choice.configure(state='disabled')
        for choice in run_options:choice.configure(state='disabled')
        last_compare_pair=None
        if comparison is not None and comparison.winfo_exists():comparison.clear_live()
        def frame_notify(kind,data):
            notify(kind,dict(data,display_label='CPU 参考' if offline else 'FPGA 回传') if kind=='progress' else data)
        options=dict(mode=int(mode.get().split()[0]),auto=auto.get(),cancel=cancel,notify=notify,width=width,height=height,
                     image_controls=image_panel.live,auto_policy='v5' if one_click else 'v4',preview_detail=live_preview,preview_focus=preview_focus)
        options['notify']=frame_notify
        managed=not offline and manage.get()
        # preview_fps is a run_video option only; the CPU reference has no preview cap.
        if not offline:options.update(preview_fps=PREVIEW_FPS,max_inflight=1 if serial.get() or not compress.get() else 6,save_output=save.get(),host=board_host.get(),wire_codec='rice03' if compress.get() else 'raw',transport_quality=('adaptive' if quality.get().startswith('自动') else 'fast' if quality.get().startswith('极速') else 'preview' if quality.get().startswith('高质量') else 'fine' if quality.get().startswith('精细') else 'lossless') if compress.get() else 'lossless',realtime_preview=False,trace_frames=workspace is not None,auto_analysis_interval=4,native_processing=native720.get())
        if managed:options.update(password=board_password.get(),poll_us=20,session=board_session)
        plan,curve_plan[0]=curve_plan[0],None
        if plan:
            options.update(parameter_curves=plan['curves'] or None,curve_region=plan['region'])
            try:save_plan(str(output_value)+'.curves.json',input_value,plan['based_on'],plan['curves'],plan['region'],plan['region'] is not None)
            except OSError:pass
        def run():
            try:(process_offline if offline else process_managed if managed else process)(input_value,output_value,**options)
            except BaseException as exc:
                failure=dict(schema=1,status='FAIL',backend='CPU_REFERENCE' if offline else 'FPGA_MMIO',
                             input=input_value,output=output_value,error=str(exc) or type(exc).__name__,
                             error_type=type(exc).__name__,failure_stage='GUI_WORKER_SETUP_OR_RUN',frames=0)
                try:
                    target=Path(str(output_value)+'.json');target.parent.mkdir(parents=True,exist_ok=True)
                    if target.exists():target=Path(str(output_value)+'.gui_error.json')
                    target.write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding='utf-8')
                except OSError as write_error:failure['report_write_error']=str(write_error)
                notify('done',failure)
        worker=threading.Thread(target=run,daemon=False);worker.start()
    start_button=ttk.Button(toolbar,text='开始 FPGA 处理',command=start,style='Accent.TButton',state='disabled');start_button.grid(row=0,column=2,padx=(12,0))
    def change_backend(event=None):
        nonlocal last_compare_pair
        offline=backend.get().startswith('离线')
        start_button.configure(text='开始离线处理' if offline else '开始 FPGA 处理')
        headings[1].configure(text='CPU 参考结果' if offline else 'FPGA 处理结果')
        preview_images[1]=None;redraw()
        last_compare_pair=None
        if comparison is not None and comparison.winfo_exists():comparison.clear_live()
        save_choice.configure(state='disabled' if offline else 'normal')
        manage_choice.configure(state='disabled' if offline else 'normal')
        if offline:save.set(True)
        status.set('离线 CPU 参考：无需开发板，输出用于算法验证。' if offline else 'FPGA 实板：自动启动板端服务，窗口打开期间保持就绪；空闲 7 分钟或关闭窗口时安全停止。')
        if not offline and source_ready and manage.get():start_prewarm()
        if source.get():
            output.set(new_output(source.get()))
        if event is not None and launch_prewarm_allowed():save_workbench_choice(backend='offline' if offline else 'fpga')
    backend_choice.bind('<<ComboboxSelected>>',change_backend)
    cancel_button=ttk.Button(toolbar,text='取消处理',command=cancel.set,state='disabled',style='Tool.TButton');cancel_button.grid(row=0,column=3,padx=(8,0))
    status_line=ttk.Frame(status_bar);status_line.pack(fill='x')
    status_label=ttk.Label(status_line,textvariable=status,wraplength=1100,font=('Microsoft YaHei UI',10));status_label.pack(side='left',fill='x',expand=True)
    status_hint=tk.StringVar();ttk.Label(status_line,textvariable=status_hint,style='Hint.TLabel').pack(side='right')
    # The live preview is reduced for speed; the exported file is the full-resolution result.
    run_output=[None];finished_output=[None]
    def reveal(path,folder=False):
        try:
            if os.name=='nt':
                if folder:subprocess.Popen(['explorer','/select,',str(path)])
                else:os.startfile(str(path))
            else:subprocess.Popen(['xdg-open',str(Path(path).parent if folder else path)])
        except OSError as exc:status.set('无法打开：'+str(exc))
    def play_output():
        if finished_output[0]:reveal(finished_output[0])
    def show_output_folder():
        if finished_output[0]:reveal(finished_output[0],folder=True)
    folder_button=ttk.Button(status_line,text='打开所在文件夹',command=show_output_folder,state='disabled',style='Tool.TButton')
    folder_button.pack(side='right',padx=(8,12))
    play_button=ttk.Button(status_line,text='播放输出视频',command=play_output,state='disabled',style='Tool.TButton')
    play_button.pack(side='right',padx=(8,0))
    def set_open_output(path):
        finished_output[0]=path
        for button in (play_button,folder_button):button.configure(state='normal' if path else 'disabled')
    # Same-frame playback of the source file and the exported file (sync_player.SyncPlayback).
    player=[None];playing=[False];pending_show=[False];current=[0];last_pair=[None];dragging=[False]
    player_bar=ttk.Frame(app,padding=(16,6,16,0));player_bar.pack(side='bottom',fill='x',before=stage)
    def toggle_play(event=None):
        if player[0] is None:return
        if event is not None and isinstance(event.widget,(ttk.Entry,tk.Entry)):return
        playing[0]=not playing[0];play_toggle.configure(text='暂停' if playing[0] else '播放')
        return 'break'
    def step(delta,event=None):
        if player[0] is None:return
        if event is not None and isinstance(event.widget,(ttk.Entry,tk.Entry,ttk.Combobox)):return
        playing[0]=False;play_toggle.configure(text='播放')
        if delta>0:pending_show[0]=True
        else:player[0].seek(current[0]-1);pending_show[0]=True
        return 'break'
    def scale_moved(value):
        if player[0] is not None and dragging[0]:frame_label.configure(text=f'跳到第 {int(float(value))+1} 帧…')
    def scale_released(event=None):
        dragging[0]=False
        if player[0] is not None:player[0].seek(int(position.get()));pending_show[0]=True
    def zoom_current():
        # The paused pair at full resolution in the comparison window (1:1, 4x, divider, flash original).
        nonlocal last_compare_pair
        pair=last_pair[0]
        if pair is None:return
        playing[0]=False;play_toggle.configure(text='播放')
        index,_,_,source_frame,result_frame=pair
        after=Image.fromarray(result_frame.to_ndarray(format='rgb24'))
        if (source_frame.width,source_frame.height)==after.size:before=Image.fromarray(source_frame.to_ndarray(format='rgb24'))
        else:
            # The source placed as the exporter placed it (Lanczos fit into the content rectangle, black
            # padding), so both sides show the same scene at the same position (review F3).
            x,y,w,h=content_rect((source_frame.width,source_frame.height),after.size);before=Image.new('RGB',after.size)
            before.paste(source_frame.reformat(width=w,height=h,format='rgb24',interpolation='LANCZOS').to_image(),(x,y))
        meta=dict(display_label='导出文件',frames=index+1,processing_size=list(after.size),output_size=list(after.size),
                  source_size=[source_frame.width,source_frame.height],native_full_frame=True)
        last_compare_pair=(before,after,meta)
        window=open_comparison();window.set_live(*last_compare_pair);window.show_live()
    play_toggle=ttk.Button(player_bar,text='播放',command=toggle_play,state='disabled',style='Tool.TButton');play_toggle.pack(side='left')
    previous_button=ttk.Button(player_bar,text='上一帧',command=lambda:step(-1),state='disabled',style='Tool.TButton');previous_button.pack(side='left',padx=(8,0))
    next_button=ttk.Button(player_bar,text='下一帧',command=lambda:step(1),state='disabled',style='Tool.TButton');next_button.pack(side='left',padx=(8,0))
    position=tk.DoubleVar(value=0)
    seek_scale=ttk.Scale(player_bar,from_=0,to=1,variable=position,command=scale_moved,state='disabled')
    seek_scale.pack(side='left',fill='x',expand=True,padx=12)
    seek_scale.bind('<ButtonPress-1>',lambda event:dragging.__setitem__(0,True));seek_scale.bind('<ButtonRelease-1>',scale_released)
    loop_play=tk.BooleanVar(value=True);ttk.Checkbutton(player_bar,text='循环',variable=loop_play).pack(side='right')
    zoom_button=ttk.Button(player_bar,text='放大细看当前帧…',command=zoom_current,state='disabled',style='Tool.TButton');zoom_button.pack(side='right',padx=(0,12))
    curves_window=[None];curve_plan=[None];region_pick=dict(callback=None,start=None,region=None)
    def player_seek(frame):
        if player[0] is None:return
        playing[0]=False;play_toggle.configure(text='播放');player[0].seek(frame);pending_show[0]=True
    def begin_region_select(callback):
        region_pick.update(callback=callback,start=None);status.set('框选区域：在左边或右边的画面上按住左键拖出一个框。')
    def open_curves():
        if not finished_output[0] or not Path(str(finished_output[0])+'.frames.jsonl').is_file():
            status.set('需要一次带逐帧记录的完整处理结果，才能读取参数曲线。');return
        window=curves_window[0]
        if window is not None and window.winfo_exists():
            if window.export==finished_output[0]:window.deiconify();window.lift();return
            window.destroy()   # still showing the previous result
        # A result made from a plan reopens with that plan (review F2): later edits add to it.
        plan=None;plan_path=Path(str(finished_output[0])+'.curves.json')
        if plan_path.is_file():
            try:plan=load_plan(plan_path)
            except (OSError,ValueError) as exc:status.set('上次的曲线计划无法读取：'+str(exc))
        if plan and plan.get('region'):region_pick['region']=tuple(int(v) for v in plan['region']);draw_region()
        def process_with_plan(plan):
            if busy(worker):status.set('正在处理，结束后再按曲线处理。');return
            curve_plan[0]=dict(plan,based_on=finished_output[0]);output.set(new_output(source.get()))
            status.set('按编辑后的曲线'+('、只处理框选区域' if plan['region'] else '')+'重新处理…');start()
        curves_window[0]=CurveWindow(app,source.get(),finished_output[0],seek=player_seek,
            current=lambda:current[0] if player[0] is not None else None,request_region=begin_region_select,
            on_process=process_with_plan,region=region_pick['region'],plan=plan)
    curves_button=ttk.Button(player_bar,text='参数曲线…',command=open_curves,state='disabled',style='Tool.TButton');curves_button.pack(side='right',padx=(0,12))
    frame_label=ttk.Label(player_bar,text='处理完成后，原片与导出结果在上方同帧播放',width=34);frame_label.pack(side='right',padx=(0,12))
    player_controls=(play_toggle,previous_button,next_button,seek_scale,zoom_button,curves_button)
    app.bind('<space>',toggle_play);app.bind('<Left>',lambda event:step(-1,event));app.bind('<Right>',lambda event:step(1,event))
    def show_pair(item):
        index,left,right=item[:3];current[0]=index;last_pair[0]=item;player_view[0]=(left,right)
        seconds=player[0].seconds(index)
        frame_label.configure(text=f'第 {index+1} / {player[0].count} 帧 · {int(seconds//60)}:{seconds%60:04.1f}')
        if not dragging[0]:position.set(index)
        redraw();draw_region()
    def tick(owner,due=None):
        if player[0] is not owner:return
        if owner.error is not None:
            status.set('同帧播放出错：'+str(owner.error));stop_player();return
        interval=1/float(owner.rate);now=time.perf_counter()
        due=now if due is None else due
        if playing[0] or pending_show[0]:
            item=owner.next_pair()
            if item is not None:
                pending_show[0]=False;show_pair(item);due+=interval
            elif owner.ended and playing[0]:
                if loop_play.get():owner.seek(0)
                else:playing[0]=False;play_toggle.configure(text='播放')
        # Paced by the clock: the drawing time is not added to every frame interval.
        due=max(due,time.perf_counter()-interval)
        app.after(max(1,int((due-time.perf_counter())*1000)) if playing[0] else 15,lambda:tick(owner,due))
    def start_player(source_path,result_path):
        stop_player()
        try:owner=SyncPlayback(source_path,result_path,lambda:tuple(canvas_size))
        except Exception as exc:
            status.set('无法同帧播放：'+str(exc));return
        player[0]=owner;playing[0]=True;pending_show[0]=True
        seek_scale.configure(to=max(1,owner.count-1))
        for control in player_controls:control.configure(state='normal')
        play_toggle.configure(text='暂停')
        headings[0].configure(text='原始视频 · 原文件');headings[1].configure(text='处理结果 · 导出文件（同帧）')
        tick(owner)
    def stop_player():
        owner=player[0];player[0]=None;player_view[0]=None;last_pair[0]=None;playing[0]=False
        if owner is not None:owner.close()
        for control in player_controls:control.configure(state='disabled')
        play_toggle.configure(text='播放');frame_label.configure(text='处理完成后，原片与导出结果在上方同帧播放')
    note_label=ttk.Label(status_bar,text='FPGA 模式的画面由开发板处理；速度按实际完成的帧数统计。双击画面或按 F11 全屏演示。',style='Hint.TLabel');note_label.pack(anchor='w')
    def resize_labels(event):
        if event.widget==app:
            status_label.configure(wraplength=max(200,app.winfo_width()-260))
            for heading in headings:heading.configure(wraplength=max(200,(app.winfo_width()-90)//2))
    app.bind('<Configure>',resize_labels)
    def poll():
        nonlocal last_frames,source_ready,last_compare_pair,releaser,closer,last_release_try,loaded_text,board_waiting,board_wait_started
        data=None
        while True:
            try:
                data=preview_events.get_nowait()
            except queue.Empty:
                break
        if data is not None:
            board_waiting=False;board_wait_started=None
            drawing=time.perf_counter()
            preview_images[:]=[Image.fromarray(data[k]) for k in ('source','result')];preview_native[0]=bool(data.get('preview_detail'))
            progress.update(frames=data['frames'],fps=data['frames']/max(data['elapsed'],.001));redraw()
            shown_window.update(window=data.get('preview_window'),size=data.get('processing_size'))
            comparison_meta={key:value for key,value in data.items() if key not in ('source','result')}
            comparison_meta.setdefault('display_label','CPU 参考' if backend.get().startswith('离线') else 'FPGA 回传')
            last_compare_pair=(*preview_images,comparison_meta)
            if comparison is not None and comparison.winfo_exists():comparison.set_live(*last_compare_pair)
            display_metrics['draw_seconds']+=time.perf_counter()-drawing
            display_metrics['rendered_pairs']+=1;display_metrics['last_processed_frame_count']=data['frames']
            last_frames=data['frames']
            fps=data['frames']/max(data['elapsed'],.001)
            now=time.perf_counter();rate_window.append((now,data['frames']))
            while len(rate_window)>2 and now-rate_window[0][0]>1.5:rate_window.popleft()
            span=rate_window[-1][0]-rate_window[0][0]
            current=(rate_window[-1][1]-rate_window[0][1])/span if span>=.4 else fps
            source_fps=data.get('source_fps')
            size=lambda key:f" · {data[key][0]}×{data[key][1]}" if data.get(key) else ''
            title=headings[1].cget('text').split(' · ')[0]
            headings[0].configure(text='原始视频'+size('source_size')+(f" · 输入 {source_fps:g} 帧/秒" if source_fps else ''))
            native=data.get('processing_size') and tuple(data['processing_size'])!=tuple(data.get('output_size') or ())
            note=f"（FPGA 按 {data['processing_size'][0]}×{data['processing_size'][1]} 原生处理后放大）" if native else ''
            headings[1].configure(text=title+size('output_size')+note+f" · 输出 {current:.1f} 帧/秒（平均 {fps:.1f}）")
            ratio=f" · 实时倍率 {fps/source_fps:.2f}×" if source_fps else ''
            applied=data.get('image_controls')
            tuning=(' · 当前帧画质：'+PRESETS[applied['preset']]+('＋微调' if any(v is not None for k,v in applied.items() if k!='preset') else '')) if applied else ''
            # The displayed frame was processed with an older knob setting: the change
            # is still travelling through the frames already on the board (~0.3 s).
            if applied and data.get('settings_revision') is not None and data['settings_revision']<image_panel.live.revision_snapshot()[1]:
                tuning+='（新调节生效中…）'
            status.set(f"已处理 {data['frames']} 帧 · 输出平均 {fps:.2f} 帧/秒 · 当前 {current:.1f} 帧/秒{ratio} · 用时 {data['elapsed']:.1f} 秒"+tuning)
        try:
            while True:
                kind,data=events.get_nowait()
                if kind=='loaded' and data['token']==load_token:
                    source_ready=True;start_button.configure(state='normal')
                    preview_images[0]=Image.fromarray(data['source']).copy();preview_native[0]=False
                    loaded_still[0]=preview_images[0];progress.update(total=data.get('count',0));redraw()
                    status.set(f"视频已载入 · {data['width']} × {data['height']} · {data['rate']} fps。点击开始处理。")
                    loaded_text=status.get()
                    try:rate=f"{float(Fraction(data['rate'])):g}"
                    except (ValueError,ZeroDivisionError):rate=data['rate']
                    headings[0].configure(text=f"原始视频 · {data['width']}×{data['height']} · 输入 {rate} 帧/秒")
                    if not backend.get().startswith('离线') and manage.get() and start_prewarm():
                        status.set(loaded_text+'正在后台连接开发板（首次约 20 秒），也可以直接点击开始。')
                elif kind=='board_ready':
                    if not busy(worker):status.set(loaded_text+'开发板已就绪。')
                elif kind=='board_prewarm_failed':
                    if not busy(worker):status.set(loaded_text+'开发板暂未连接（'+data['error']+'），点击开始时会重试。')
                elif kind=='board_released':
                    if not busy(worker):
                        errors=(data.get('release_receipts') or {}).get('errors') or []
                        if data.get('status')=='STOPPED_DMA_HALTED_CORE_RESET':
                            status.set('开发板空闲后已安全停止；'+(f'{len(errors)} 份结果凭据保存未完成。' if errors else '结果停机凭据已保存。')+'下次处理时会重新准备。')
                        else:status.set('本窗口会话已结束；未取得完整停机凭据的结果仍需复核。')
                elif kind=='board_release_failed':
                    if not busy(worker):status.set('开发板停止尚未确认：'+data['error']+'；稍后自动重试。')
                elif kind=='load_error' and data['token']==load_token:status.set('视频读取失败：'+data['error'])
                elif kind=='connecting_board':
                    board_waiting=True
                    if board_wait_started is None:board_wait_started=time.perf_counter()
                    status.set('正在确认开发板状态，请稍候…')
                elif kind=='board_acquired':
                    board_waiting=False;board_wait_started=None
                    origin=(data.get('setup') or {}).get('service_origin')
                    status.set('开发板已热复用就绪，正在处理视频…' if origin=='REUSED_PREVIOUS_VIDEO' else '开发板准备完成，正在处理视频…')
                elif kind=='stopping_board':status.set('视频处理已结束，正在安全停止开发板…')
                elif kind=='done':
                    board_waiting=False;board_wait_started=None
                    start_button.configure(state='normal' if source_ready else 'disabled')
                    backend_choice.configure(state='readonly');resolution_choice.configure(state='readonly')
                    for choice in run_choices:choice.configure(state='readonly')
                    for choice in run_options:choice.configure(state='normal')
                    if backend.get().startswith('离线'):
                        save_choice.configure(state='disabled');manage_choice.configure(state='disabled')
                    control_context()
                    for button in chooser_buttons:button.configure(state='normal')
                    cancel_button.configure(state='disabled')
                    saved=('视频和逐帧记录已保存。' if data.get('trace_written',True) else '结果视频已保存，未写入逐帧审计日志。') if data.get('output_video_written',True) else ('仅预览完成，逐帧记录已保存。' if data.get('trace_written',True) else '仅实时预览完成，未写入逐帧审计日志。')
                    kept=(data.get('board_cleanup') or {}).get('status')=='KEPT_FOR_NEXT_VIDEO'
                    if data['status']=='CANCELLED':
                        saved='已取消，未生成完整视频；'+('逐帧记录已保留。' if data.get('trace_written') else '本次没有逐帧记录。')
                    exported=run_output[0] if (data['status']=='PASS' and data.get('output_video_written',True)
                                               and run_output[0] and Path(run_output[0]).is_file()) else None
                    set_open_output(exported)
                    if exported:
                        saved+=' 下方已开始原片与结果同帧播放（空格暂停，←/→ 逐帧）。'
                        start_player(source.get(),exported)
                        # Measure the curves now, while the result plays: 参数曲线 then opens on finished
                        # (and cached) curves instead of starting a minute-long measurement.
                        if player[0] is not None and Path(str(exported)+'.frames.jsonl').is_file():
                            try:CurveAnalysis.shared(source.get(),exported,player[0].count,background=True)
                            except Exception:pass   # measured when the curve window opens instead
                    else:redraw()
                    detail=' · '+data['error'] if data.get('error') and data['status']!='CANCELLED' else ' · '+saved
                    status.set(f"{data['status']} · {data.get('frames',0)} 帧 · {data.get('processing_fps',0):.2f} 帧/秒"+detail+(' 开发板保持就绪，可继续处理；停机时补齐验收凭据。' if kept else ''))
        except queue.Empty:pass
        if not closing:
            if board_waiting and busy(worker):
                since=prewarm_started if busy(prewarm) and prewarm_started is not None else board_wait_started
                if since is not None:status.set(f'正在准备开发板 · 已等待 {time.perf_counter()-since:.0f} 秒。准备完成后自动处理。')
            elif busy(prewarm) and not busy(worker) and prewarm_started is not None:
                status.set(loaded_text+f' 开发板后台准备中 · 已等待 {time.perf_counter()-prewarm_started:.0f} 秒，可直接点击开始。')
        if closing and not busy(worker):
            if closer is None and (board_session.active or busy(prewarm) or busy(releaser) or board_session.receipts.pending_count):
                status.set('正在安全停止开发板并退出…')
                def close_board():
                    for thread in (prewarm,releaser):
                        if thread is not None:thread.join()
                    # A stop that is not confirmed leaves the board to its own idle lease.
                    try:board_session.release()
                    except BaseException:pass
                closer=threading.Thread(target=close_board,daemon=False);closer.start()
            if not busy(closer):
                errors=((board_session.last_release or {}).get('release_receipts') or {}).get('errors') or []
                if errors:messagebox.showwarning('结果凭据未保存',f'开发板停止流程已结束，但 {len(errors)} 份结果凭据未写入。请保留视频和 JSON，结果收集时将继续列为待复核。')
                if board_session.release_pending:
                    messagebox.showwarning('开发板停止未确认','关闭窗口时没能确认开发板已停止（网络或 Jupyter 繁忙）。板端服务会在空闲 10 分钟内由租约自动停止；如需立即处理，请重新打开程序再关闭一次。')
                app.destroy();return
        elif (board_session.active and not busy(worker) and not busy(prewarm) and not busy(releaser)):
            idle=board_session.idle_seconds()
            # Idle release well inside the board's own lease; a failed stop is retried every 30 s.
            if ((idle is not None and idle>=board_session.RELEASE_SECONDS) or
                    (board_session.release_pending and time.monotonic()-last_release_try>=30)):
                last_release_try=time.monotonic()
                def release_board():
                    try:
                        result=board_session.release();events.put_nowait(('board_released',result))
                    except BaseException as exc:
                        events.put_nowait(('board_release_failed',dict(error=str(exc) or type(exc).__name__)))
                releaser=threading.Thread(target=release_board,daemon=False);releaser.start()
        app.after(UI_POLL_INTERVAL_MS,poll)
    def close():
        nonlocal closing
        stop_player()
        if image_panel.pending_save is not None:image_panel.persist()
        if worker and worker.is_alive():
            closing=True;cancel.set();status.set('正在停止处理并等待安全退出…');return
        if board_session.active or busy(prewarm) or busy(releaser) or board_session.receipts.pending_count:
            closing=True;status.set('正在安全停止开发板并退出…');return
        app.destroy()
    app.protocol('WM_DELETE_WINDOW',close);app.after(UI_POLL_INTERVAL_MS,poll)
    # Prepare the board as soon as the window is up (~15 s on the board), so it is usually ready by the
    # time a video is chosen; nothing processed for RELEASE_SECONDS stops it again.
    def launch_prewarm():
        if not backend.get().startswith('离线') and manage.get() and start_prewarm():
            status.set('正在后台准备开发板（约 15 秒），可以先导入视频。')
    if launch_prewarm_allowed():
        # The processing choice of the last session comes back first, so offline use never warms the board.
        if load_workbench_choices().get('backend')=='offline':
            backend.set(backend_choice.cget('values')[1]);change_backend()
        app.after(800,launch_prewarm)
    # Private deterministic UI check hook. No board service is contacted.
    hook=_UI_CHECK_HOOK
    if hook is not None:app.after(350,lambda:hook(app,dict(
        canvases=canvases,images=preview_images,redraw=redraw,headings=headings,
        source=source,output=output,status=status,start_button=start_button,save=save,workspace=workspace,select_output=select_output,
        cancel_button=cancel_button,backend=backend,change_backend=change_backend,play_button=play_button,folder_button=folder_button,finished_output=finished_output,
        image_panel=image_panel,mode=mode,auto=auto,optimize=optimize,quality=quality,detail=detail,
        resolution=resolution,
        mode_choice=mode_choice,select_mode=select_mode,control_context=control_context,
        preview_focus=preview_focus,is_running=lambda:bool(worker and worker.is_alive()),board_session=board_session,
        select_source=select_source,events=events,chooser_buttons=chooser_buttons,display_metrics=display_metrics,
        compare_button=compare_button,open_comparison=open_comparison,live_preview=live_preview,preview_events=preview_events,
        live_display=live_display,player=player,player_view=player_view,shown_image=shown_image,player_controls=player_controls,
        start_player=start_player,stop_player=stop_player,last_pair=last_pair,playing=playing,step=step,zoom_current=zoom_current,
        open_curves=open_curves,curves_window=curves_window,region_pick=region_pick,region_release=region_release,choose_detail=choose_detail,shown_rects=shown_rects)))
    timer=None
    try:
        if os.name=='nt':
            import ctypes
            winmm=ctypes.windll.winmm
            if winmm.timeBeginPeriod(1)==0:
                timer=winmm;display_metrics['timer_resolution_ms']=1
        app.mainloop()
    finally:
        if timer is not None:timer.timeEndPeriod(1)

_UI_CHECK_HOOK=None

if __name__=='__main__':main()
