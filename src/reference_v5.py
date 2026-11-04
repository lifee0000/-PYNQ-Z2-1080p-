"""V5 luma edge term on top of the frozen V4 reference; integer model of the FPGA.

V4 mode 5 sharpens only texture inside its bilateral band, never edges (edge
differences exceed 3 sigma, so the bilateral base equals the pixel). V5 adds a
noise-gated unsharp term computed from the 3x3 Gaussian the core already has:

    edge = e - smooth3x3(e)            (V4 window clamping and ROI rules)
    edge = 0 if |edge| < max(2, noise_floor); clamp to +/-detail_limit
    term = trunc(weight[e] * edge_gain_q8_8 * edge / 65536)   (C division)
    Y    = clip8(Y_v4 + term)          (mode 5 pixels V4 itself processes)

weight[] is V4's dark/light protection table. edge_gain_q8_8 == 0 returns the
V4 output unchanged, byte for byte; UV is never touched by the edge term.
"""
import numpy as np
from reference import Params, enhance as enhance_v4

MAX_EDGE_GAIN_Q8 = 512


def weight_table(dark_thr, light_thr):
    i = np.arange(256, dtype=np.int64)
    q = np.full(256, 256, np.int64)
    dark = i < dark_thr
    q[dark] = q[dark]*(i[dark]+1)//(dark_thr+1)
    light = i > light_thr
    q[light] = q[light]*(256-i[light])//(256-light_thr)
    return q


def _trunc_div(a, d):
    return np.where(a >= 0, a//d, -((-a)//d))


def edge_term(y, w, h, p, edge_gain):
    """Integer edge term for every luma sample (zero where V4 leaves the pixel)."""
    y = y.astype(np.int64)
    if p.roi_enable:
        x0, y0, x1, y1 = p.roi_x, p.roi_y, p.roi_x+p.roi_width-1, p.roi_y+p.roi_height-1
    else:
        x0, y0, x1, y1 = 0, 0, w-1, h-1
    rows = np.arange(h); cols = np.arange(w)
    def shifted(dy, dx):
        r = np.clip(rows+dy, y0, y1); c = np.clip(cols+dx, x0, x1)
        return y[r][:, c]
    a = {(dy, dx): shifted(dy, dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)}
    smooth = (a[-1, -1]+2*a[-1, 0]+a[-1, 1]+2*a[0, -1]+4*a[0, 0]+2*a[0, 1]+a[1, -1]+2*a[1, 0]+a[1, 1]+8) >> 4
    edge = y-smooth
    edge = np.where(np.abs(edge) < max(2, int(p.noise_floor)), 0, edge)
    edge = np.clip(edge, -int(p.detail_limit), int(p.detail_limit))
    term = _trunc_div(weight_table(p.dark_thr, p.light_thr)[y]*int(edge_gain)*edge, 65536)
    if p.roi_enable:
        inside = np.zeros((h, w), bool); inside[y0:y1+1, x0:x1+1] = True
    else:
        inside = np.ones((h, w), bool); inside[0, :] = inside[-1, :] = inside[:, 0] = inside[:, -1] = False
    return np.where(inside & (p.mode == 5), term, 0)


def enhance(payload, width, height, params=Params(), edge_gain_q8_8=0):
    if type(edge_gain_q8_8) is not int or not 0 <= edge_gain_q8_8 <= MAX_EDGE_GAIN_Q8:
        raise ValueError(f'edge_gain_q8_8 must be an integer in 0..{MAX_EDGE_GAIN_Q8}')
    out = enhance_v4(payload, width, height, params)
    if edge_gain_q8_8 == 0 or params.mode != 5:
        return out
    source = np.frombuffer(payload, np.uint8).reshape(height, width, 2)[:, :, 0]
    frame = np.frombuffer(out, np.uint8).reshape(height, width, 2).copy()
    frame[:, :, 0] = np.clip(frame[:, :, 0].astype(np.int64)+edge_term(source, width, height, params, edge_gain_q8_8), 0, 255)
    return frame.tobytes()
