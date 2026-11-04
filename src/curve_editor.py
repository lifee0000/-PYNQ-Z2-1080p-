"""Parameter-curve window: measured input/output curves and editable FPGA parameter curves.

x = frame, y = the quantity in its own unit. Measured curves (software, signal_curves) show
the source (blue) and the exported result (orange) on the whole frame or a selected region.
Parameter curves show what the FPGA used per frame (grey); dragging with the left button
draws a new curve (green) over those frames. "按曲线重新处理" hands the edited curves (and
optionally the region, processed alone through the FPGA ROI) to the workbench for the next run.
Right click on the chart seeks the player to that frame.

Measurement and control names overlap ('brightness' is both mean luma and the black-level
word), so the chooser keys are 'metric:<name>' / 'control:<name>' (review F1); plans keep the
plain control names. A result made from a plan reopens with that plan's edits and region,
so changing one more curve keeps the earlier ones (review F2); 恢复自动 clears them.
"""
import tkinter as tk
from tkinter import ttk

import signal_curves as sc

INPUT, OUTPUT, AUTO, EDIT, GRID, TEXT = '#3b82f6', '#f59e0b', '#94a3b8', '#16a34a', '#e2e8f0', '#475569'


class CurveWindow(tk.Toplevel):
    def __init__(self, master, source, export, *, seek=None, current=lambda: None, request_region=None,
                 on_process=None, region=None, plan=None):
        super().__init__(master)
        self.title('参数曲线 · 输入／输出对比与逐帧调整'); self.configure(bg='white')
        self.geometry(f'{min(1500, self.winfo_screenwidth() - 120)}x{min(820, self.winfo_screenheight() - 160)}')
        self.source, self.export = source, export
        self.seek, self.current, self.request_region, self.on_process = seek, current, request_region, on_process
        self.words = sc.load_trace(export); self.count = len(self.words)
        self.auto = {name: sc.control_values(self.words, name) for name in sc.CONTROLS}
        self.edits = {name: None for name in sc.CONTROLS}
        self.region = region; self.analysis = None; self.selected = tk.StringVar(value='metric:noise')
        self.region_only = tk.BooleanVar(value=False); self.drag = None; self.view = None
        restored = self.restore(plan)
        self.restored_note = ('' if not (restored or (plan and plan.get('region'))) else
            ' · 已载入上次的修改：' + ('、'.join(sc.CONTROLS[k][0] for k in restored) or '只处理框选区域') + '（再改其他参数时保留，“全部恢复自动”清除）')

        top = ttk.Frame(self, padding=(12, 10, 12, 4)); top.pack(fill='x')
        self.info = tk.StringVar(); ttk.Label(top, textvariable=self.info).pack(side='left')
        ttk.Button(top, text='整幅画面', command=lambda: self.set_region(None)).pack(side='right')
        ttk.Button(top, text='框选区域…', command=self.ask_region).pack(side='right', padx=8)
        body = ttk.Frame(self, padding=(12, 4, 12, 4)); body.pack(fill='both', expand=True)
        side = ttk.Frame(body); side.pack(side='left', fill='y', padx=(0, 12))
        ttk.Label(side, text='测量（软件识别）', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', pady=(0, 4))
        self.choices = {}
        for key, (label, unit) in sc.METRICS.items():
            self.choices['metric:' + key] = ttk.Radiobutton(side, text=f'{label}（{unit}）', value='metric:' + key,
                                                            variable=self.selected, command=self.redraw)
            self.choices['metric:' + key].pack(anchor='w')
        ttk.Label(side, text='处理参数（FPGA，可拖动修改）', font=('Microsoft YaHei UI', 10, 'bold')).pack(anchor='w', pady=(14, 4))
        for key, spec in sc.CONTROLS.items():
            self.choices['control:' + key] = ttk.Radiobutton(side, text=f'{spec[0]}（{spec[1]}）', value='control:' + key,
                                                             variable=self.selected, command=self.redraw)
            self.choices['control:' + key].pack(anchor='w')
        ttk.Label(side, text='蓝：输入（按处理画面缩放）　橙：处理结果\n灰：本结果实际使用的参数\n绿：下一次要用的曲线\n左键拖动：改写这段帧的参数\n右键：播放器跳到该帧',
                  foreground=TEXT, justify='left').pack(anchor='w', pady=(14, 0))
        self.canvas = tk.Canvas(body, bg='white', highlightthickness=0); self.canvas.pack(side='left', fill='both', expand=True)
        bottom = ttk.Frame(self, padding=(12, 4, 12, 10)); bottom.pack(fill='x')
        ttk.Button(bottom, text='本参数恢复自动', command=self.reset_one).pack(side='left')
        ttk.Button(bottom, text='全部恢复自动', command=self.reset_all).pack(side='left', padx=8)
        ttk.Button(bottom, text='平滑本参数', command=self.smooth_one).pack(side='left')
        self.process_button = ttk.Button(bottom, text='按曲线重新处理', command=self.process, style='Accent.TButton')
        self.process_button.pack(side='right')
        self.region_check = ttk.Checkbutton(bottom, text='只处理框选区域（FPGA ROI）', variable=self.region_only)
        self.region_check.pack(side='right', padx=12)
        self.status = tk.StringVar(); ttk.Label(bottom, textvariable=self.status, foreground=TEXT).pack(side='left', padx=16)
        self.canvas.bind('<Configure>', lambda e: self.redraw())
        self.canvas.bind('<ButtonPress-1>', self.press); self.canvas.bind('<B1-Motion>', self.motion)
        self.canvas.bind('<ButtonRelease-1>', self.release); self.canvas.bind('<Button-3>', self.seek_to)
        self.measure(); self.after(150, self.poll)

    def restore(self, plan):
        """Edits and region of the plan this result was made with; returns the restored control names."""
        if not plan:
            return []
        restored = []
        for name, values in (plan.get('curves') or {}).items():
            if name in sc.CONTROLS and values:
                values = list(values)[:self.count] + [None] * max(0, self.count - len(values))
                self.edits[name] = [self.auto[name][i] if v is None else sc.clamp(name, v) for i, v in enumerate(values)]
                restored.append(name)
        if plan.get('region'):
            self.region = tuple(int(v) for v in plan['region']); self.region_only.set(bool(plan.get('region_only', True)))
        return restored

    def chosen(self):
        """('metric' | 'control', name) of the selected curve."""
        kind, _, name = self.selected.get().partition(':')
        return kind, name

    # --- data
    def measure(self):
        # The whole-frame analysis is shared (the workbench starts it after a run and it is cached);
        # only a region analysis belongs to this window and is cancelled when replaced.
        if self.analysis is not None and self.analysis.region is not None:
            self.analysis.cancel()
        self.analysis = (sc.CurveAnalysis.shared(self.source, self.export, self.count) if self.region is None else
                         sc.CurveAnalysis(self.source, self.export, self.region, stride=sc.default_stride(self.count)))
        self.update_info()

    def update_info(self):
        where = '整幅画面' if self.region is None else '区域 x={} y={} 宽={} 高={}'.format(*self.region)
        self.info.set(f'{self.count} 帧 · 测量范围：{where}' + self.restored_note)
        self.region_check.configure(state='normal' if self.region else 'disabled')
        if not self.region:
            self.region_only.set(False)

    def set_region(self, region):
        self.region = tuple(int(v) for v in region) if region else None
        self.measure(); self.redraw()

    def ask_region(self):
        if self.request_region is not None:
            self.status.set('在主窗口的画面上按住左键拖出一个框。')
            self.request_region(self.set_region)

    def curve(self, kind, key):
        if kind == 'metric':
            a = self.analysis
            if a is None:
                return None
            frames, inputs, outputs = a.snapshot()   # consistent while the fill-in pass inserts points
            return frames, inputs[key], outputs[key]
        return self.auto[key], self.edits[key]

    def edited(self):
        return {k: v for k, v in self.edits.items() if v is not None}

    # --- chart
    def layout(self):
        w, h = max(200, self.canvas.winfo_width()), max(150, self.canvas.winfo_height())
        return 70, 20, w - 20, h - 40   # left, top, right, bottom

    def value_range(self, kind, key):
        if kind == 'control':
            return sc.CONTROLS[key][2], sc.CONTROLS[key][3]
        data = self.curve(kind, key)
        values = [] if data is None else [v for v in data[1] + data[2] if v is not None]
        if not values:
            return 0, 1
        low, high = min(values), max(values); pad = (high - low) * .1 or max(abs(high) * .1, .1)
        return max(0, low - pad) if low >= 0 else low - pad, high + pad

    def to_xy(self, frame, value, rng):
        l, t, r, b = self.layout(); low, high = rng
        x = l + (r - l) * frame / max(1, self.count - 1)
        y = b - (b - t) * (value - low) / ((high - low) or 1)
        return x, y

    def from_x(self, x):
        l, t, r, b = self.layout()
        return max(0, min(self.count - 1, round((x - l) / max(1, r - l) * (self.count - 1))))

    def from_y(self, y, rng):
        l, t, r, b = self.layout(); low, high = rng
        return low + (b - y) / max(1, b - t) * (high - low)

    def polyline(self, frames, values, rng, color, width=2):
        points = []
        for f, v in zip(frames, values):
            if v is None:
                if len(points) >= 4: self.canvas.create_line(*points, fill=color, width=width)
                points = []; continue
            points += self.to_xy(f, v, rng)
        if len(points) >= 4: self.canvas.create_line(*points, fill=color, width=width)

    def redraw(self):
        c = self.canvas; c.delete('all'); kind, key = self.chosen(); l, t, r, b = self.layout()
        rng = self.value_range(kind, key); self.view = (kind, key, rng)
        label, unit = sc.METRICS[key] if kind == 'metric' else sc.CONTROLS[key][:2]
        for i in range(5):
            value = rng[0] + (rng[1] - rng[0]) * i / 4; _, y = self.to_xy(0, value, rng)
            c.create_line(l, y, r, y, fill=GRID); c.create_text(l - 8, y, text=f'{value:.2f}'.rstrip('0').rstrip('.'), anchor='e', fill=TEXT)
        for i in range(6):
            frame = round((self.count - 1) * i / 5); x, _ = self.to_xy(frame, rng[0], rng)
            c.create_line(x, t, x, b, fill=GRID); c.create_text(x, b + 14, text=str(frame + 1), fill=TEXT)
        c.create_text(l, t - 10, text=f'{label}（{unit}）', anchor='w', fill='#0f172a', font=('Microsoft YaHei UI', 10, 'bold'))
        c.create_text(r, b + 30, text='帧', anchor='e', fill=TEXT)
        data = self.curve(kind, key)
        if kind == 'metric':
            if data is None or not data[0]:
                c.create_text((l + r) / 2, (t + b) / 2, text='正在测量…', fill=TEXT, font=('Microsoft YaHei UI', 12))
            else:
                self.polyline(data[0], data[1], rng, INPUT); self.polyline(data[0], data[2], rng, OUTPUT)
        else:
            auto, edit = data; frames = range(self.count)
            self.polyline(frames, auto, rng, AUTO, 2)
            if edit is not None: self.polyline(frames, edit, rng, EDIT, 2)
        now = self.current()
        if now is not None and self.count:
            x, _ = self.to_xy(now, rng[0], rng); c.create_line(x, t, x, b, fill='#ef4444', dash=(4, 3))

    def poll(self):
        if not self.winfo_exists():
            return
        a = self.analysis
        if a is not None and a.error is not None:
            if getattr(self, 'shown_error', None) is not a.error:   # the analysis may be shared: leave its error set
                self.shown_error = a.error; self.status.set('测量出错：' + str(a.error))
        elif a is not None and not a.finished:
            measured, expected = a.progress()
            self.status.set(f'正在测量输入与输出 {measured}/{expected or "…"} 帧'
                            + ('：已显示完整的粗略曲线，正在补齐中间各帧…' if a.coarse_done else '…'))
        elif a is not None and (self.status.get().startswith('正在测量') or not self.status.get()):
            self.status.set(('测量完成（读取已保存的测量结果）。' if a.cached else '测量完成。') + '选择左侧的处理参数，按住左键在图上拖动即可修改。')
        self.redraw(); self.after(250 if a is not None and not a.finished else 400, self.poll)

    # --- editing
    def press(self, event):
        kind, key = self.chosen()
        if kind != 'control':
            self.seek_to(event); return
        if self.edits[key] is None:
            self.edits[key] = list(self.auto[key])
        self.drag = (self.from_x(event.x), event.y); self.motion(event)

    def motion(self, event):
        kind, key = self.chosen()
        if self.drag is None or kind != 'control' or self.view[:2] != (kind, key):
            return
        rng = self.view[2]; f0, y0 = self.drag; f1 = self.from_x(event.x)
        v0, v1 = sc.clamp(key, self.from_y(y0, rng)), sc.clamp(key, self.from_y(event.y, rng))
        step = sc.CONTROLS[key][4]
        lo, hi = sorted((f0, f1))
        for f in range(lo, hi + 1):
            share = 0 if f1 == f0 else (f - f0) / (f1 - f0)
            self.edits[key][f] = round((v0 + (v1 - v0) * share) / step) * step
        self.drag = (f1, event.y); self.redraw()

    def release(self, event):
        if self.drag is not None and self.chosen()[0] == 'control':
            self.status.set(f'已修改：{"、".join(sc.CONTROLS[k][0] for k in self.edited())}。点“按曲线重新处理”生效。')
        self.drag = None

    def seek_to(self, event):
        if self.seek is not None:
            self.seek(self.from_x(event.x))

    def reset_one(self):
        kind, key = self.chosen()
        if kind == 'control':
            self.edits[key] = None; self.redraw(); self.status.set(f'{sc.CONTROLS[key][0]}：下一次按自动策略。')

    def reset_all(self):
        self.edits = {name: None for name in sc.CONTROLS}; self.restored_note = ''; self.update_info(); self.redraw()
        self.status.set('全部参数已恢复自动，下一次按自动策略。')

    def smooth_one(self):
        kind, key = self.chosen(); values = self.edits.get(key) if kind == 'control' else None
        if values is None:
            return
        k = 9; padded = [values[0]] * (k // 2) + values + [values[-1]] * (k // 2)
        step = sc.CONTROLS[key][4]
        self.edits[key] = [round(sum(padded[i:i + k]) / k / step) * step for i in range(len(values))]; self.redraw()

    def process(self):
        if not self.edited() and not (self.region_only.get() and self.region):
            self.status.set('还没有修改任何曲线，也没有选择只处理区域。'); return
        if self.on_process is not None:
            self.on_process(dict(curves=self.edited(), region=self.region if self.region_only.get() else None))

    def destroy(self):
        if self.analysis is not None and self.analysis.region is not None:
            self.analysis.cancel()
        super().destroy()
