"""Per-frame signal measurements and editable parameter curves (curve editor back end).

Measured curves: the source file and the exported result are decoded frame-locked (frame i
with frame i, as the exporter writes them) and the same measurements are taken on both,
on the picture or on a selected region (export pixel coordinates):
  noise       Immerkaer sigma of luma (levels): pixel-scale noise; texture raises it too
  brightness  mean luma (levels, 0..255)
  detail      mean |4-neighbour Laplacian| of luma (levels)
  blocking    mean |luma step across 8-px grid columns| / the same inside blocks (1 = none)
These are software measurements of decoded video, not FPGA counters.

Geometry (review F3/F4, 2026-11-01): the export holds the source picture in its content
rectangle (media_frame.fit_rgb: Lanczos fit, centred, black padding). Noise, brightness and
detail of the input are measured on the source resized into that rectangle with the same
swscale Lanczos, i.e. the picture as it went into the FPGA, so both sides share one pixel
grid and a 720p or portrait source is not compared at a different scale; the padding is
never measured. Blocking is a ratio on each file's own 8-px coding grid, so the input's is
taken on the native source pixels of the same area.

Control curves: what each frame's FPGA parameter words were (the .frames.jsonl trace), in
user units. An edited curve becomes per-frame overrides that run_video applies to the
words after the automatic policy and the image controls (apply_curves), so the trace and
the bit-exact reference check keep working.
"""
import json
import os
import threading
import time
from bisect import bisect_left
from collections import deque
from pathlib import Path

import numpy as np

CURVES_SCHEMA = 1


def _clarity_strength(words):
    return (int(words.get('clarity', 0)) & 255) / 64


def _with_clarity(words, strength):
    word = int(words.get('clarity', 0))
    a = max(0, min(255, round(strength * 64)))
    if a == 0:
        return dict(clarity=word & ~255)
    if not word >> 16 & 255:   # no clarity configured: the policy's floor-2 mode-5 word
        word = 32 | 8 << 8 | 24 << 16 | 8 << 24
    return dict(clarity=(word & ~255) | a)


# name: (label, unit, low, high, step, read(words) -> value, write(words, value) -> word updates)
CONTROLS = {
    'gain': ('亮度增益', '倍', .5, 2.5, .01, lambda w: w['gain_q8_8'] / 256, lambda w, v: dict(gain_q8_8=round(v * 256))),
    'brightness': ('黑位偏移', '级', -40, 40, 1, lambda w: w['brightness'], lambda w, v: dict(brightness=round(v))),
    'denoise': ('降噪强度', '级', 0, 12, 1, lambda w: w['noise_floor'] if w.get('filter_enable', 1) else 0,
                lambda w, v: dict(noise_floor=round(v), filter_enable=1)),
    'sharpen': ('锐化强度', '倍', 0, 3, .05, lambda w: w['sharp_q8_8'] / 256, lambda w, v: dict(sharp_q8_8=round(v * 256))),
    'chroma': ('色彩跟随亮度', '%', 0, 100, 1, lambda w: w.get('chroma_q8', 0) / 2.56, lambda w, v: dict(chroma_q8=round(v * 2.56))),
    'clarity': ('清晰度', '强度', 0, 1, .02, _clarity_strength, _with_clarity),
}
METRICS = {
    'noise': ('噪声 σ', '级'),
    'brightness': ('平均亮度', '级，0–255'),
    'detail': ('细节强度', '平均 |拉普拉斯|'),
    'blocking': ('压缩块感', '网格边 / 块内 梯度比'),
}


def luma(rgb):
    # uint8 * float32 scalar stays float32: no float copy of the whole RGB frame.
    return rgb[..., 0] * np.float32(.2126) + rgb[..., 1] * np.float32(.7152) + rgb[..., 2] * np.float32(.0722)


def blocking(y, x0=0):
    """Grid-edge / in-block mean |horizontal luma step|; x0 = the crop's column in the coded picture."""
    if y.shape[0] < 3 or y.shape[1] < 16:
        return None
    dx = np.abs(np.diff(y, axis=1))
    first = (7 - x0) % 8                       # steps i with (x0 + i) % 8 == 7: a strided view, no mask copy
    grid = dx[:, first::8]
    total, edge = float(dx.sum(dtype=np.float64)), float(grid.sum(dtype=np.float64))
    inner_count = dx.size - grid.size
    inner = (total - edge) / inner_count if inner_count else 0.
    return edge / grid.size / inner if inner > 1e-6 else None


STRIPE_ROWS = 128


def measure(rgb, region=None):
    """The four measurements of one RGB frame, on region (x, y, w, h) or the whole frame.

    Worked through STRIPE_ROWS-row stripes (each with one row of context above and below) and summed
    in float64, so a 1080p frame never holds full-frame float temporaries (~40 MB each before)."""
    if region is not None:
        x, y, w, h = region; rgb = rgb[y:y + h, x:x + w]
    hgt, wid = rgb.shape[:2]
    if hgt < 3 or wid < 3:
        return dict(brightness=float(luma(rgb).mean()) if rgb.size else None, noise=None, detail=None, blocking=None)
    x0 = 0 if region is None else region[0]
    first = (7 - x0) % 8   # horizontal steps i with (x0 + i) % 8 == 7: the coding-grid edges
    total = lap_sum = mask_sum = step_sum = grid_sum = 0.
    for r0 in range(0, hgt, STRIPE_ROWS):
        r1 = min(hgt, r0 + STRIPE_ROWS); off = max(0, r0 - 1)
        y = luma(rgb[off:min(hgt, r1 + 1)])          # rows off .. r1 (one context row each side)
        core = y[r0 - off:r1 - off]
        total += float(core.sum(dtype=np.float64))
        steps = np.abs(np.diff(core, axis=1))
        step_sum += float(steps.sum(dtype=np.float64)); grid_sum += float(steps[:, first::8].sum(dtype=np.float64))
        a, b = max(r0, 1), min(r1, hgt - 1)           # interior rows of this stripe
        if b > a:
            c = y[a - off:b - off]
            lap = 4 * c[:, 1:-1]
            lap -= y[a - 1 - off:b - 1 - off, 1:-1]; lap -= y[a + 1 - off:b + 1 - off, 1:-1]; lap -= c[:, :-2]; lap -= c[:, 2:]
            lap_sum += float(np.abs(lap, out=lap).sum(dtype=np.float64))
            # Immerkaer: sigma = sqrt(pi/2) / (6 (W-2)(H-2)) * sum |I * [[1,-2,1],[-2,4,-2],[1,-2,1]]|;
            # the mask is [1,-2,1] along rows then along columns, so two passes instead of nine terms.
            rows = y[a - 1 - off:b + 1 - off]
            h = rows[:, 1:-1] * -2; h += rows[:, :-2]; h += rows[:, 2:]
            m = h[1:-1] * -2; m += h[:-2]; m += h[2:]
            mask_sum += float(np.abs(m, out=m).sum(dtype=np.float64))
    interior = (hgt - 2) * (wid - 2)
    result = dict(brightness=total / (hgt * wid), detail=lap_sum / interior,
                  noise=float(np.sqrt(np.pi / 2) * mask_sum / interior / 6))
    grid_count = hgt * len(range(first, wid - 1, 8)); inner_count = hgt * (wid - 1) - grid_count
    inner = (step_sum - grid_sum) / inner_count if inner_count else 0.
    result['blocking'] = grid_sum / grid_count / inner if wid >= 16 and grid_count and inner > 1e-6 else None
    return result


def content_rect(source_size, export_size):
    """(x, y, w, h) of the source picture inside the export, as media_frame.fit_rgb places it."""
    (sw, sh), (width, height) = source_size, export_size
    if (sw, sh) == (width, height):
        return (0, 0, width, height)
    ratio = min(width / sw, height / sh); w, h = round(sw * ratio), round(sh * ratio)
    return ((width - w) // 2, (height - h) // 2, w, h)


def clip_region(region, rect):
    """region (x, y, w, h) intersected with rect; None when they do not overlap."""
    x, y, w, h = region; rx, ry, rw, rh = rect
    x1, y1, x2, y2 = max(x, rx), max(y, ry), min(x + w, rx + rw), min(y + h, ry + rh)
    return (x1, y1, x2 - x1, y2 - y1) if x2 > x1 and y2 > y1 else None


def export_to_source(region, rect, source_size):
    """An export-pixel region inside the content rectangle, in native source pixels."""
    x, y, w, h = region; cx, cy, cw, ch = rect; sx, sy = source_size[0] / cw, source_size[1] / ch
    x1, y1 = max(0, round((x - cx) * sx)), max(0, round((y - cy) * sy))
    x2, y2 = min(source_size[0], round((x + w - cx) * sx)), min(source_size[1], round((y + h - cy) * sy))
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def scale_region(region, src_size, dst_size):
    if region is None:
        return None
    sx, sy = dst_size[0] / src_size[0], dst_size[1] / src_size[1]
    x, y, w, h = region
    x2, y2 = min(dst_size[0], round((x + w) * sx)), min(dst_size[1], round((y + h) * sy))
    x1, y1 = max(0, round(x * sx)), max(0, round(y * sy))
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


MEASURE_CACHE_SCHEMA = 1
WORKERS = max(1, min(6, (os.cpu_count() or 2) // 2))
BACKGROUND_WORKERS = 1        # while the result plays: one frame at a time ...
BACKGROUND_PAUSE = 1.0        # ... resting as long as it took (about half of one core)
DECODE_THREADS = 3            # per decoder: FFmpeg's automatic count is one per core, each holding frames
_thread_state = threading.local()


def set_thread_priority(low):
    """Below-normal (low) or normal priority for the calling thread; Windows only, a no-op elsewhere."""
    if getattr(_thread_state, 'low', False) == bool(low) or os.name != 'nt':
        return
    import ctypes
    kernel = ctypes.windll.kernel32; kernel.GetCurrentThread.restype = ctypes.c_void_p
    kernel.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
    if kernel.SetThreadPriority(kernel.GetCurrentThread(), -1 if low else 0):   # BELOW_NORMAL / NORMAL
        _thread_state.low = bool(low)


def default_stride(count):
    return 1 if count <= 600 else 2


class CurveAnalysis:
    """Measure source and export frame-locked (progress via .done / .count).

    One thread decodes both files in frame order; the per-frame work (Lanczos fit, RGB conversion,
    the numpy measurements, which release the GIL) runs on WORKERS pool threads. Two passes: the
    first measures every COARSE-th sampled frame over the whole video, so a complete (coarse) curve
    shows within a second or two; the second fills in the other frames. Results are inserted in
    frame order under a lock; readers take snapshot(). A whole-frame analysis is cached next to the
    export (<export>.measure.json) and reused while both files are unchanged; shared() lets the
    workbench start it right after a run, before the curve window asks for it.

    A background analysis (started while the result plays) uses BACKGROUND_WORKERS frames at a time
    at below-normal thread priority, so playback keeps its pace; boost() (the curve window asking for
    it) raises it to WORKERS at normal priority.
    """
    COARSE = 8
    _shared = {}
    _shared_lock = threading.Lock()

    @classmethod
    def shared(cls, source, result, count, background=False):
        """The whole-frame analysis of this pair: running, finished, cached, or started now."""
        key = (os.path.abspath(str(source)), os.path.abspath(str(result)), default_stride(count))
        with cls._shared_lock:
            analysis = cls._shared.get(key)
            if analysis is None or analysis.error is not None or analysis.stop.is_set() or not analysis._files_unchanged():
                analysis = cls(source, result, None, key[2], background=background); cls._shared[key] = analysis
            elif not background:
                analysis.boost()
            return analysis

    def boost(self):
        """Full speed now (someone is waiting for the curves)."""
        self.parallel = WORKERS; self.low_priority = False

    def __init__(self, source, result, region=None, stride=1, background=False):
        import av
        self.paths = (str(source), str(result)); self.region = region; self.stride = max(1, int(stride))
        self.parallel = BACKGROUND_WORKERS if background else WORKERS; self.low_priority = bool(background)
        with av.open(self.paths[1]) as r:
            self.count = r.streams.video[0].frames or 0
        self.frames = []; self.input = {k: [] for k in METRICS}; self.output = {k: [] for k in METRICS}
        self.done = 0; self.error = None; self.finished = False; self.cached = False; self.stop = threading.Event()
        self.lock = threading.Lock(); self.expected = None; self.coarse_done = False
        self.stamp = self._stamp()
        if region is None and self._load():
            self.thread = threading.Thread(target=lambda: None, name='curve-analysis-cached', daemon=True)
            self.finished = True; self.thread.start(); return
        self.thread = threading.Thread(target=self._run, name='curve-analysis', daemon=True); self.thread.start()

    # --- cache
    def _stamp(self):
        stamps = []
        for path in self.paths:
            st = os.stat(path); stamps.append([os.path.abspath(path), st.st_size, st.st_mtime_ns])
        return stamps

    def _files_unchanged(self):
        try: return self._stamp() == self.stamp
        except OSError: return False

    def cache_path(self):
        return Path(self.paths[1] + '.measure.json')

    def _load(self):
        try:
            data = json.loads(self.cache_path().read_text(encoding='utf-8'))
        except (OSError, ValueError):
            return False
        if data.get('schema') != MEASURE_CACHE_SCHEMA or data.get('files') != self.stamp or data.get('stride') != self.stride:
            return False
        self.frames, self.input, self.output, self.done = data['frames'], data['input'], data['output'], data['done']
        self.cached = True
        return True

    def _save(self):
        data = dict(schema=MEASURE_CACHE_SCHEMA, files=self.stamp, stride=self.stride, done=self.done,
                    frames=self.frames, input=self.input, output=self.output)
        try: self.cache_path().write_text(json.dumps(data), encoding='utf-8')
        except OSError: pass   # a read-only folder only costs the cache

    # --- measuring
    def _pair(self, a, b):
        set_thread_priority(self.low_priority)
        start = time.perf_counter()
        try: return self._measure_pair(a, b)
        finally:
            if self.low_priority: time.sleep((time.perf_counter() - start) * BACKGROUND_PAUSE)

    def _measure_pair(self, a, b):
        rect = content_rect((a.width, a.height), (b.width, b.height))
        out_region = rect if self.region is None else clip_region(self.region, rect)
        if out_region is None:
            raise ValueError('框选区域不在视频画面内')
        cx, cy, cw, ch = rect
        # The input on the export's grid: the source fitted into the content rectangle.
        fitted = (a.to_ndarray(format='rgb24') if (a.width, a.height) == (cw, ch) else
                  a.reformat(width=cw, height=ch, format='rgb24', interpolation='LANCZOS').to_ndarray())
        mi = measure(fitted, (out_region[0] - cx, out_region[1] - cy, out_region[2], out_region[3]))
        if (a.width, a.height) != (cw, ch):
            sx, sy, sw, sh = export_to_source(out_region, rect, (a.width, a.height))
            mi['blocking'] = blocking(luma(a.to_ndarray(format='rgb24')[sy:sy + sh, sx:sx + sw]), sx)
        return mi, measure(b.to_ndarray(format='rgb24'), out_region)

    def _collect(self, index, future):
        mi, mo = future.result()
        with self.lock:   # keep frame order: the fill-in pass lands between coarse points
            at = bisect_left(self.frames, index); self.frames.insert(at, index)
            for k in METRICS:
                self.input[k].insert(at, mi[k]); self.output[k].insert(at, mo[k])

    def snapshot(self):
        """(frames, input, output) copies that belong together, for drawing while measuring continues."""
        with self.lock:
            return list(self.frames), {k: list(v) for k, v in self.input.items()}, {k: list(v) for k, v in self.output.items()}

    def progress(self):
        """(measured frames, frames to measure or None while the first pass has not reached the end)."""
        with self.lock:
            return len(self.frames), self.expected

    def _pass(self, pool, wanted):
        """Decode both files once, measuring the frames for which wanted(index); returns the decoded count."""
        import av
        pending = deque(); decoded = 0
        with av.open(self.paths[0]) as s, av.open(self.paths[1]) as r:
            for stream in (s.streams.video[0], r.streams.video[0]):
                stream.thread_type = 'AUTO'; stream.thread_count = DECODE_THREADS
            for index, (a, b) in enumerate(zip(s.decode(video=0), r.decode(video=0))):
                if self.stop.is_set():
                    break
                set_thread_priority(self.low_priority)
                decoded = index + 1
                if wanted(index):
                    pending.append((index, pool.submit(self._pair, a, b)))
                # self.parallel frames measured at a time, one more decoded and waiting (memory, CPU share).
                while pending and (len(pending) > self.parallel or pending[0][1].done()):
                    self._collect(*pending.popleft())
                if decoded > self.done: self.done = decoded
        while pending and not self.stop.is_set():
            self._collect(*pending.popleft())
        for _, future in pending: future.cancel()
        return decoded

    def _run(self):
        from concurrent.futures import ThreadPoolExecutor
        coarse = self.stride * self.COARSE
        try:
            with ThreadPoolExecutor(WORKERS, 'curve-measure') as pool:
                decoded = self._pass(pool, lambda i: i % coarse == 0)
                with self.lock: self.expected = (decoded + self.stride - 1) // self.stride
                self.coarse_done = True
                if not self.stop.is_set():
                    self._pass(pool, lambda i: i % self.stride == 0 and i % coarse != 0)
                if not self.stop.is_set():
                    self.done = decoded
                    if self.region is None: self._save()
        except Exception as exc:
            self.error = exc
        finally:
            self.finished = True

    def cancel(self):
        self.stop.set()


def load_trace(export):
    """Per-frame FPGA parameter words of an export (its .frames.jsonl), in frame order."""
    rows = [json.loads(line) for line in Path(str(export) + '.frames.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    rows.sort(key=lambda r: r['frame_id'])
    return [r['parameters'] for r in rows]


def control_values(words_list, name):
    read = CONTROLS[name][5]
    return [float(read(w)) for w in words_list]


def clamp(name, value):
    low, high = CONTROLS[name][2], CONTROLS[name][3]
    return min(high, max(low, float(value)))


def apply_curves(words, index, curves):
    """Per-frame overrides: curves maps a control name to a list of values (None = automatic)."""
    if not curves:
        return words
    words = dict(words)
    for name, values in curves.items():
        if name in CONTROLS and values is not None and index < len(values) and values[index] is not None:
            words.update(CONTROLS[name][6](words, clamp(name, values[index])))
    return words


def roi_words(region, size):
    """FPGA ROI words for region (x, y, w, h) in processing pixels: even x and width, inside the frame."""
    x, y, w, h = (int(v) for v in region); width, height = size
    x = max(0, min(x, width - 4)) & ~1; y = max(0, min(y, height - 3))
    w = max(4, min(w, width - x)) & ~1; h = max(3, min(h, height - y))
    return dict(roi_enable=1, roi_x=x, roi_y=y, roi_width=w, roi_height=h)


def plan_roi(region, output_size, processing_size, letterbox=None):
    """ROI words for a region chosen on the export (output pixels), inside the processed picture."""
    x, y, w, h = scale_region(region, output_size, processing_size)
    if letterbox is not None:
        lx, ly, lw, lh = letterbox
        x1, y1, x2, y2 = max(x, lx), max(y, ly), min(x + w, lx + lw), min(y + h, ly + lh)
        if x2 - x1 < 4 or y2 - y1 < 3:
            raise ValueError('框选区域不在视频画面内')
        x, y, w, h = x1, y1, x2 - x1, y2 - y1
    return roi_words((x, y, w, h), processing_size)


def save_plan(path, source, export, curves, region, region_only):
    data = dict(schema=CURVES_SCHEMA, source=str(source), based_on=str(export), region=list(region) if region else None,
                region_only=bool(region_only), curves={k: v for k, v in curves.items() if v is not None})
    Path(path).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    return data


def load_plan(path):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    if data.get('schema') != CURVES_SCHEMA:
        raise ValueError('unsupported curve plan')
    return data
