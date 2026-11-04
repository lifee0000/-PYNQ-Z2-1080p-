"""Same-frame comparison rendering; never changes processing or exported video pixels."""
from pathlib import Path
import json
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageTk

VIEWS = ('适配窗口', '原像素 1×', '细节 2×', '细节 4×')
MODES = ('滑动对比', '左右对照')


class LivePreviewMode:
    def __init__(self, enabled=False):
        self._enabled = bool(enabled)
        self._lock = threading.Lock()

    def set(self, enabled):
        with self._lock:
            self._enabled = bool(enabled)

    def __bool__(self):
        with self._lock:
            return self._enabled


def native_available(meta, image_size):
    window = meta.get('preview_window')
    if window:
        return tuple(image_size) == tuple(window[2:4])
    return bool(meta.get('native_full_frame') and tuple(image_size) == tuple(meta.get('processing_size', ())))


def view_images(source, result, available, zoom=0, focus=(.5,.5)):
    """Return aligned display images and their exact source-pixel crop.

    zoom=0 fits the whole supplied preview; integer zoom keeps visible pixels
    exact, cropping before magnifying so a large photo is never allocated.
    """
    if source.size != result.size:
        raise ValueError('Comparison needs matching source/result geometry')
    width, height = max(1, int(available[0])), max(1, int(available[1]))
    if zoom not in (0, 1, 2, 4):
        raise ValueError('Unsupported viewing magnification')
    iw, ih = source.size
    if not zoom:
        scale = min(width / iw, height / ih)
        size = (max(1, round(iw * scale)), max(1, round(ih * scale)))
        return source.resize(size, Image.Resampling.BILINEAR), result.resize(size, Image.Resampling.BILINEAR), (0, 0, iw, ih)
    cw = min(iw, max(1, width // zoom))
    ch = min(ih, max(1, height // zoom))
    x = min(max(round(float(focus[0])*iw-cw/2),0),iw-cw)
    y = min(max(round(float(focus[1])*ih-ch/2),0),ih-ch)
    box = (x, y, x + cw, y + ch)
    size = (cw * zoom, ch * zoom)
    return (source.crop(box).resize(size, Image.Resampling.NEAREST),
            result.crop(box).resize(size, Image.Resampling.NEAREST), (x, y, cw, ch))


def compose(source, result, available, *, mode='滑动对比', zoom=0, divider=.5, original=False, focus=(.5,.5)):
    pane = ((max(1, available[0] - 12) // 2, available[1]) if mode == '左右对照' else available)
    before, after, crop = view_images(source, result, pane, zoom, focus)
    if original:
        after = before
    width, height = before.size
    if mode == '左右对照':
        picture = Image.new('RGB', (width * 2 + 12, height), '#182536')
        picture.paste(before, (0, 0))
        picture.paste(after, (width + 12, 0))
    elif mode == '滑动对比':
        cut = round(width * max(0., min(1., divider)))
        picture = after.copy()
        if cut:
            picture.paste(before.crop((0, 0, cut, height)), (0, 0))
    else:
        raise ValueError('Unsupported comparison layout')
    return picture, crop


def dark_levels(source, result, crop):
    x, y, width, height = crop
    box = (x, y, x + width, y + height)
    def luma(image):
        a = np.asarray(image.crop(box), dtype=np.int32)[::2, ::2]
        return (54*a[..., 0] + 183*a[..., 1] + 19*a[..., 2] + 128) >> 8
    before, after = luma(source), luma(result)
    dark = (before >= 5) & (before < 64)
    if int(dark.sum()) < 64:
        return None
    return round(float(before[dark].mean()), 1), round(float(after[dark].mean()), 1)


def _font(size):
    for path in ('C:/Windows/Fonts/msyh.ttc', 'C:/Windows/Fonts/arial.ttf'):
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


class CompareWindow(tk.Toplevel):
    def __init__(self, master, *, request_detail=lambda enabled: None, request_focus=lambda fx,fy: None, samples=None, export_directory=None):
        super().__init__(master)
        self.title('画质效果 · 同帧对比')
        self.geometry('1180x780')
        self.minsize(800, 570)
        self.configure(bg='#f3f6fb')
        self.request_detail = request_detail
        self.request_focus = request_focus
        self.export_directory = Path(export_directory) if export_directory is not None else None
        self.focus = [.5,.5]
        self.pair = None
        self.latest = None
        self.live_latest = None
        self.sample_mode = False
        self.frozen = tk.BooleanVar(value=False)
        self.view = tk.StringVar(value=VIEWS[0])
        self.mode = tk.StringVar(value=MODES[0])
        self.caption = tk.StringVar(value='处理视频或选择下方样张，查看同一帧的增强前后。')
        self.measured = tk.StringVar(value='左右始终使用同一帧、同一位置。')
        self.divider = .5
        self.peek = False
        self.photo = None
        self.rect = None
        self.last_crop = None
        self._draw_job = None
        self._updating = False
        self.samples = samples or []
        bar = ttk.Frame(self, padding=(14, 10))
        bar.pack(fill='x')
        ttk.Label(bar, text='同帧画质对比', font=('Microsoft YaHei UI', 15, 'bold')).pack(side='left')
        ttk.Label(bar, textvariable=self.caption, foreground='#52647a').pack(side='left', padx=16)
        tools = ttk.Frame(self, padding=(14, 0, 14, 8))
        tools.pack(fill='x')
        mode = ttk.Combobox(tools, textvariable=self.mode, values=MODES, width=10, state='readonly')
        mode.pack(side='left')
        mode.bind('<<ComboboxSelected>>', lambda event: self.redraw())
        zoom = ttk.Combobox(tools, textvariable=self.view, values=VIEWS, width=12, state='readonly')
        zoom.pack(side='left', padx=8)
        zoom.bind('<<ComboboxSelected>>', self.change_view)
        self.freeze = ttk.Checkbutton(tools, text='冻结当前帧', variable=self.frozen, command=self.change_freeze)
        self.freeze.pack(side='left', padx=6)
        self.peek_button = ttk.Button(tools, text='按住看原图')
        self.peek_button.pack(side='left', padx=6)
        self.peek_button.bind('<ButtonPress-1>', lambda event: self.show_original(True))
        self.peek_button.bind('<ButtonRelease-1>', lambda event: self.show_original(False))
        self.peek_button.bind('<Leave>', lambda event: self.show_original(False))
        ttk.Button(tools, text='保存对比图…', command=self.save_dialog).pack(side='right')
        sample_bar = ttk.Frame(self, padding=(14, 0, 14, 8))
        sample_bar.pack(fill='x')
        ttk.Label(sample_bar, text='实板核验样张').pack(side='left')
        self.sample_choice = ttk.Combobox(sample_bar, values=[s['title'] for s in self.samples], state='readonly', width=23)
        self.sample_choice.pack(side='left', padx=8)
        self.sample_choice.bind('<<ComboboxSelected>>', self.select_sample)
        ttk.Button(sample_bar, text='返回当前视频', command=self.show_live).pack(side='left')
        ttk.Label(sample_bar, text='拖分界线；右键选细节位置', foreground='#68798e').pack(side='right')
        self.canvas = tk.Canvas(self, bg='#101c2d', highlightthickness=0)
        self.canvas.pack(fill='both', expand=True, padx=14)
        self.canvas.bind('<Configure>', lambda event: self.redraw())
        self.canvas.bind('<Button-1>', self.drag)
        self.canvas.bind('<B1-Motion>', self.drag)
        self.canvas.bind('<Button-3>', self.choose_focus)
        self.canvas.bind('<Shift-Button-1>', self.choose_focus)
        ttk.Label(self, textvariable=self.measured, padding=(14, 10), foreground='#435773').pack(fill='x')
        self.bind('<KeyPress-space>', lambda event: self.show_original(True))
        self.bind('<KeyRelease-space>', lambda event: self.show_original(False))
        self.protocol('WM_DELETE_WINDOW', self.destroy)
        self.redraw()

    def set_live(self, source, result, meta):
        self.live_latest = (source.copy().convert('RGB'), result.copy().convert('RGB'), dict(meta))
        if self.sample_mode:
            return
        self.latest = self.live_latest
        if not self.frozen.get() or self.pair is None:
            self.pair = self.latest
            self.focus = [.5,.5]
            self.redraw()

    def clear_live(self):
        self.live_latest = None
        if not self.sample_mode:
            self.latest = self.pair = None
            self.redraw()

    def show_live(self):
        self.sample_mode = False
        self.sample_choice.set('')
        self.latest = self.pair = self.live_latest
        self.frozen.set(False)
        self.request_detail(self.view.get() != VIEWS[0])
        self.redraw()

    def select_sample(self, event=None):
        index = self.sample_choice.current()
        if index < 0:
            return
        sample = self.samples[index]
        try:
            with Image.open(sample['source']) as image:
                before = image.convert('RGB')
            with Image.open(sample['result']) as image:
                after = image.convert('RGB')
            self.sample_mode = True
            self.latest = self.pair = (before, after, dict(sample['metadata'], display_label='实板核验样张', sample_title=sample['title']))
            self.focus = [.5,.5]
            self.frozen.set(False)
            self.redraw()
        except (OSError, ValueError) as exc:
            messagebox.showerror('样张读取失败', str(exc), parent=self)

    def change_view(self, event=None):
        if not self.sample_mode:
            # The producer takes its own atomic boolean snapshot. Tk variables
            # are never accessed by the processing thread.
            self.request_detail(self.view.get() != VIEWS[0])
            if self.frozen.get() and self.pair and not native_available(self.pair[2], self.pair[0].size):
                self.frozen.set(False)
                self.pair = self.latest
        self.redraw()

    def change_freeze(self):
        if not self.frozen.get():
            self.pair = self.latest
        self.redraw()

    def show_original(self, active):
        self.peek = bool(active)
        self.redraw()
        return 'break'

    def drag(self, event):
        if self.mode.get() == MODES[0] and self.rect:
            self.divider = max(0., min(1., (event.x-self.rect[0])/max(1,self.rect[2])))
            self.redraw()

    def choose_focus(self, event):
        if not self.pair or not self.rect or not self.last_crop:
            return 'break'
        x,y,width,height=self.rect
        px=event.x-x
        if self.mode.get()==MODES[1]:
            pane=(width-12)/2
            if px>pane+12:px-=pane+12
            elif px>pane:return 'break'
            width=pane
        u=max(0.,min(1.,px/max(1,width)))
        v=max(0.,min(1.,(event.y-y)/max(1,height)))
        cx,cy,cw,ch=self.last_crop
        before,_,meta=self.pair
        self.focus=[(cx+u*cw)/before.width,(cy+v*ch)/before.height]
        if not self.sample_mode:
            window=meta.get('preview_window')
            size=meta.get('processing_size')
            if window and size:
                fx=(window[0]+self.focus[0]*window[2])/size[0]
                fy=(window[1]+self.focus[1]*window[3])/size[1]
            else:fx,fy=self.focus
            self.request_focus(fx,fy)
        self.redraw()
        return 'break'

    def redraw(self):
        if not self.winfo_exists():
            return
        if self._draw_job is None:
            self._draw_job = self.after_idle(self._draw)

    def _draw(self):
        self._draw_job = None
        self.canvas.delete('all')
        width, height = max(1,self.canvas.winfo_width()), max(1,self.canvas.winfo_height())
        if self.pair is None:
            self.rect = None
            self.caption.set('选择实板核验样张，或开始视频处理')
            self.canvas.create_text(width/2,height/2,text='从样张开始，直观看到提亮、色彩与细节差别',fill='#bfd0e2',font=('Microsoft YaHei UI',13))
            return
        before, after, meta = self.pair
        desired = VIEWS.index(self.view.get())
        zoom = (0,1,2,4)[desired]
        ready = native_available(meta,before.size)
        if zoom and not ready:
            zoom = 0
            waiting = ' · 等待原像素帧；视频未运行时请先开始处理'
        else:
            waiting = ''
        picture, crop = compose(before,after,(width,height),mode=self.mode.get(),zoom=zoom,divider=self.divider,original=self.peek,focus=self.focus)
        self.last_crop = crop
        self.photo = ImageTk.PhotoImage(picture)
        x, y = (width-picture.width)/2, (height-picture.height)/2
        self.rect = (x,y,picture.width,picture.height)
        self.canvas.create_image(x,y,image=self.photo,anchor='nw')
        if self.mode.get() == MODES[0]:
            cut = x + round(picture.width*self.divider)
            self.canvas.create_line(cut,y,cut,y+picture.height,fill='#38bdf8',width=2)
        label = meta.get('display_label','处理结果')
        shown_label = '原始输入（按住查看）' if self.peek else label
        for px,text in ((x+12,'原始输入'),(x+picture.width-12,shown_label)):
            anchor = 'nw' if px == x+12 else 'ne'
            self.canvas.create_text(px,y+10,text=text,anchor=anchor,fill='white',font=('Microsoft YaHei UI',11,'bold'))
        frame = meta.get('frames')
        position = (' · 第 '+str(frame)+' 帧') if frame is not None else ''
        geometry = meta.get('processing_size')
        shape = (' · '+str(geometry[0])+'×'+str(geometry[1])) if geometry else ''
        self.caption.set(label+position+shape+(' · 已冻结' if self.frozen.get() else '')+waiting)
        levels = dark_levels(before,after,crop)
        metric = ('暗部平均亮度 '+str(levels[0])+' → '+str(levels[1])+' / 255 · 当前区域') if levels else '当前区域暗部样本不足；可切换样张或细节位置'
        scale = '适配窗口' if not zoom else '1 个处理像素显示为 '+str(zoom)+'×'+str(zoom)+' 像素'
        self.measured.set(scale+' · '+metric)

    def export(self, path):
        if self.pair is None:
            raise ValueError('请先选择样张或等待处理结果')
        before, after, meta = self.pair
        zoom = (0,1,2,4)[VIEWS.index(self.view.get())]
        if zoom and not native_available(meta,before.size):
            raise ValueError('原像素帧尚未到达，请先使用全图适配或等待下一帧')
        if zoom and self.last_crop:
            x,y,w,h=self.last_crop
            box=(x,y,x+w,y+h)
            picture,_=compose(before.crop(box),after.crop(box),(w*zoom*2+12,h*zoom),mode=MODES[1],zoom=zoom)
            crop=self.last_crop
        else:
            picture,crop=compose(before,after,(1440,760),mode=MODES[1],zoom=zoom,focus=self.focus)
        image = Image.new('RGB',(picture.width,picture.height+76),'#122238')
        image.paste(picture,(0,76))
        draw = ImageDraw.Draw(image)
        draw.text((14,10),'原始输入',font=_font(20),fill='white')
        draw.text((picture.width//2+14,10),meta.get('display_label','处理结果'),font=_font(20),fill='white')
        draw.text((14,43),self.caption.get(),font=_font(14),fill='#b8cce2')
        path = Path(path)
        path.parent.mkdir(parents=True,exist_ok=True)
        image.save(path)
        allowed = ('frames','processing_size','source_size','preview_window','display_label','sample_title',
                   'image_controls','parameters','sample_provenance','physical_output_sha256')
        record = dict(schema=1,kind='ANNOTATED_SAME_FRAME_PREVIEW_COMPARISON',
            view=self.view.get(),native_pixels=native_available(meta,before.size),crop_pixels=list(crop),
            metadata={key:meta[key] for key in allowed if key in meta})
        path.with_suffix(path.suffix+'.json').write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
        return record

    def save_dialog(self):
        if self.pair is None:
            return
        options=dict(parent=self,title='保存同帧对比图',defaultextension='.png',filetypes=[('PNG 图像','*.png')])
        if self.export_directory is not None:
            self.export_directory.mkdir(parents=True,exist_ok=True)
            options['initialdir']=str(self.export_directory)
        name=filedialog.asksaveasfilename(**options)
        if not name:
            return
        try:
            self.export(name)
            self.measured.set('已保存同帧对比图与画面来源记录：'+Path(name).name)
        except (OSError,ValueError) as exc:
            messagebox.showerror('保存失败',str(exc),parent=self)

    def destroy(self):
        if self._draw_job is not None:
            self.after_cancel(self._draw_job)
            self._draw_job = None
        super().destroy()


def load_samples(root=None):
    import hashlib
    folder = Path(root) if root is not None else Path(__file__).resolve().parent/'comparison_samples'
    index = folder/'index.json'
    if not index.is_file():
        return []
    data=json.loads(index.read_text(encoding='utf-8'))
    samples=[]
    for item in data['samples']:
        source=(folder/item['source']).resolve()
        result=(folder/item['result']).resolve()
        if not source.is_relative_to(folder.resolve()) or not result.is_relative_to(folder.resolve()):
            raise ValueError('Invalid sample path')
        for path,key in ((source,'source_png_sha256'),(result,'result_png_sha256')):
            if hashlib.sha256(path.read_bytes()).hexdigest()!=item[key]:
                raise ValueError('Sample image integrity mismatch')
        samples.append(dict(title=item['title'],source=source,result=result,metadata=item['metadata']))
    return samples
