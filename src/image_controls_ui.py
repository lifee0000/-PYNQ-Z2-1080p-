"""Tk controls for live image tuning; the processing thread only sees snapshots."""
from dataclasses import replace
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from image_controls import (CONTROL_LABELS, CONTROL_RANGES, PRESETS, ImageControls,
                            LiveImageControls, available_controls, default_profile_path,
                            load_profile, save_profile)


class ImageControlsPanel(ttk.Frame):
    def __init__(self, master, *, on_status=lambda text: None, on_restore=lambda: None, profile_path=None):
        super().__init__(master)
        self.on_status = on_status
        self.on_restore = on_restore
        self.profile_path = Path(profile_path) if profile_path is not None else default_profile_path()
        self.live = LiveImageControls()
        self.window = None
        self.mode, self.automatic = 5, True
        self.pending_save = None
        self.loading = False
        self.preset = tk.StringVar(self, value=PRESETS['auto'])
        self.summary = tk.StringVar(self)
        self.hint = tk.StringVar(self)
        self.follow = {name: tk.BooleanVar(self, value=True) for name in CONTROL_LABELS}
        self.values = {name: tk.DoubleVar(self, value=0 if name == 'brightness' else 50)
                       for name in CONTROL_LABELS}
        self.readouts = {name: tk.StringVar(self) for name in CONTROL_LABELS}
        self.scales, self.checks = {}, {}
        ttk.Label(self, text='画质预设').grid(row=0, column=0, padx=(0, 8))
        self.choice = ttk.Combobox(self, textvariable=self.preset, values=list(PRESETS.values()),
                                   state='readonly', width=9)
        self.choice.grid(row=0, column=1, sticky='ew')
        self.choice.bind('<<ComboboxSelected>>', self.choose_preset)
        ttk.Button(self, text='手动微调…', style='Small.TButton', command=self.open).grid(row=0, column=2, padx=(6, 0))
        actions = ttk.Frame(self)
        actions.grid(row=1, column=0, columnspan=3, sticky='e', pady=(3, 0))
        ttk.Button(actions, text='恢复全自动', style='Small.TButton', command=self.restore).pack(side='left')
        ttk.Button(actions, text='保存预设…', style='Small.TButton', command=self.save_as).pack(side='left', padx=6)
        ttk.Button(actions, text='载入预设…', style='Small.TButton', command=self.load).pack(side='left')
        try:
            if self.profile_path.exists():
                self.set_settings(load_profile(self.profile_path), persist=False)
        except (OSError, ValueError, TypeError) as exc:
            self.on_status('画质配置读取失败，已使用全自动：' + str(exc))
        self.refresh()

    def settings(self):
        return self.live.snapshot()

    def set_settings(self, settings, *, persist=True):
        self.live.update(settings)
        self.loading = True
        try:
            self.preset.set(PRESETS[settings.preset])
            for name in CONTROL_LABELS:
                value = getattr(settings, name)
                self.follow[name].set(value is None)
                if value is not None:
                    self.values[name].set(value)
        finally:
            self.loading = False
        self.refresh()
        if persist:
            if self.pending_save is not None:
                self.after_cancel(self.pending_save)
            self.pending_save = self.after(400, self.persist)

    def persist(self):
        if self.pending_save is not None:
            self.after_cancel(self.pending_save)
            self.pending_save = None
        try:
            save_profile(self.profile_path, self.settings())
        except (OSError, ValueError) as exc:
            self.on_status('画质已生效，但保存失败：' + str(exc))

    def choose_preset(self, event=None):
        # A preset is a complete starting point. Previously touched knobs do not
        # secretly carry over; subsequent slider edits override only that preset.
        key = next(key for key, label in PRESETS.items() if label == self.preset.get())
        self.set_settings(ImageControls(preset=key))

    def restore(self):
        self.set_settings(ImageControls())
        message = self.on_restore()
        self.on_status(message or '已恢复画质全自动；下一个待处理帧生效。')

    def changed(self, name, value=None):
        if self.loading:
            return
        amount = None if self.follow[name].get() else round(self.values[name].get())
        self.set_settings(replace(self.settings(), **{name: amount}))

    def slide(self, name, value):
        if self.loading:
            return
        self.follow[name].set(False)
        self.changed(name)

    def set_context(self, mode, automatic):
        self.mode, self.automatic = mode, automatic
        self.refresh()

    def refresh(self):
        settings = self.settings()
        active = available_controls(self.mode, self.automatic)
        manual = [CONTROL_LABELS[n] for n in CONTROL_LABELS if n in active and getattr(settings, n) is not None]
        self.summary.set('手动：' + '、'.join(manual) if manual else '跟随场景')
        if not active:
            self.summary.set('此处理模式不支持画质微调')
        self.choice.configure(state='readonly' if 'sharpen' in active else 'disabled')
        self.hint.set('调整后用于后续帧，已送出的帧保留原设置。\n'
                      + ('自动场景分析继续工作；手动亮度、降噪或色彩保留会使用综合增强模式。'
                         if self.automatic else '灰色项目不作用于当前单项模式；设置会保留。'))
        for name in CONTROL_LABELS:
            v = getattr(settings, name)
            self.readouts[name].set('跟随预设' if v is None else f'{v:+d}' if name == 'brightness' else f'{v}%')
            if name in self.scales:
                self.checks[name].configure(state='normal' if name in active else 'disabled')
                self.scales[name].configure(state='normal' if name in active else 'disabled')

    def open(self):
        if self.window is not None and self.window.winfo_exists():
            self.window.deiconify(); self.window.lift()
            return
        self.window = tk.Toplevel(self)
        self.window.title('画质手动微调')
        self.window.transient(self.winfo_toplevel())
        self.window.resizable(True, False)
        content = ttk.Frame(self.window, padding=16)
        content.pack(fill='both', expand=True)
        content.columnconfigure(1, weight=1)
        ttk.Label(content, textvariable=self.hint, wraplength=560).grid(
            row=0, column=0, columnspan=4, sticky='w', pady=(0, 12))
        for row, (name, label) in enumerate(CONTROL_LABELS.items(), 1):
            ttk.Label(content, text=label).grid(row=row, column=0, sticky='w', padx=(0, 10))
            low, high = CONTROL_RANGES[name]
            scale = ttk.Scale(content, from_=low, to=high, variable=self.values[name], length=260,
                              command=lambda value, n=name: self.slide(n, value))
            scale.grid(row=row, column=1, sticky='ew', pady=10)
            ttk.Label(content, textvariable=self.readouts[name], width=9).grid(row=row, column=2, padx=8)
            check = ttk.Checkbutton(content, text='跟随预设', variable=self.follow[name],
                                    command=lambda n=name: self.changed(n))
            check.grid(row=row, column=3)
            self.scales[name], self.checks[name] = scale, check
        ttk.Label(content, text='锐化调整边缘；清晰度调整较大范围的明暗层次。\n'
                  '色彩保留用于提亮后的颜色恢复。强降噪可能损失纹理，高清晰度可能放大噪声。',
                  foreground='#68798e', wraplength=560).grid(row=6, column=0, columnspan=4, sticky='w', pady=12)
        ttk.Button(content, text='恢复全自动', command=self.restore).grid(row=7, column=0, columnspan=2, sticky='w')
        ttk.Button(content, text='完成', command=self.window.withdraw).grid(row=7, column=3, sticky='e')
        self.window.protocol('WM_DELETE_WINDOW', self.window.withdraw)
        self.refresh()

    def save_as(self):
        name = filedialog.asksaveasfilename(parent=self, title='保存画质预设', defaultextension='.json',
                                          filetypes=[('画质预设', '*.json')])
        if name:
            try:
                save_profile(name, self.settings())
                self.on_status('画质预设已保存：' + name)
            except (OSError, ValueError) as exc:
                messagebox.showerror('保存失败', str(exc), parent=self)

    def load(self):
        name = filedialog.askopenfilename(parent=self, title='载入画质预设', filetypes=[('画质预设', '*.json')])
        if name:
            try:
                settings = load_profile(name)  # Validate fully before replacing live settings.
                self.set_settings(settings)
                self.on_status('画质预设已载入；下一个待处理帧生效。')
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror('载入失败', str(exc), parent=self)
