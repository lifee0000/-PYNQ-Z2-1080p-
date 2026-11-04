"""Per-frame transport precision: lossless unless a frame is both all texture and too big.

Near-lossless transport shows as patches in flat areas (walls, sky, smooth
shadows); measured on board-modelled crops, any shift > 0 left visible patches
on frames that have them. A frame whose 16x16 luma blocks are almost never
flat masks a +/-1 error, and complex frames are exactly the ones whose
lossless bytes exceed the board's ~42 MB/s network budget (rain-forest clip:
2.9 MB/frame lossless = 15.6 fps; shift 1 = 2.4 MB/frame). So a frame travels
with shift 1 only when fewer than FLAT_ENTER of its blocks are flat AND the
recent lossless-equivalent size exceeds the per-frame budget for TARGET_FPS;
hysteresis (FLAT_LEAVE) avoids flipping precision every frame. Everything else
stays lossless. No pixel is changed here: the Rice codec quantizes residuals.

The decision is made before encoding (a first version encoded every frame
losslessly and again at shift 1, which made the host encoder the bottleneck);
the size history comes from observe().
"""
import threading

import numpy as np

FLAT_BLOCK, FLAT_STD = 16, 1.5
FLAT_ENTER, FLAT_LEAVE = 0.05, 0.08
LINK_BYTES_PER_SECOND = 42_000_000
TARGET_FPS = 25
RETURN_RATIO = 1.05      # return bytes per input byte at the same shift (measured 0.95-1.1)
SHIFT1_TO_LOSSLESS = 1.22  # lossless/shift-1 input bytes on all-texture frames (rain forest)
# RETURN_RATIO is only the starting value: observe_return() replaces it with the real
# return sizes (both hops in lossless-equivalent bytes, so the estimate does not move
# with the precision it chooses), smoothed and kept within RETURN_RATIO_LIMITS.
RETURN_RATIO_LIMITS = (.6, 1.6)
RETURN_RATIO_WEIGHT = .1
MAX_SHIFT = 1
# Two near-lossless hops can move Y by 2 and U/V by 2. The largest
# BT.709 chroma coefficient is 1.856, giving about six RGB levels of risk.
# Keep precision when a meaningful part of the frame has little headroom.
GAMUT_HEADROOM = 6
GAMUT_ENTER, GAMUT_LEAVE = .002, .001


def gamut_risk_share(payload, width, height, parameters=None):
    """Bounded, conservative colour-headroom estimate; never modifies pixels.

    Sample whole YUYV pairs on an 8x8 grid. Consider both input colour and
    the requested tone/chroma gain, before the core's gamut clamp. This is a
    precision-selection heuristic, not an exact simulation or an error bound.
    """
    pair = np.frombuffer(payload, np.uint8).reshape(height, width//2, 4)[::8, ::8].astype(np.int32)
    y0, u, y1, v = (pair[..., i] for i in range(4))
    u, v = u-128, v-128
    p = parameters or {}
    def tone(y):
        if p.get('mode', 5) not in (3, 5):
            return y
        mapped = (p.get('gain_q8_8', 256)*y+128)//256+p.get('brightness', 0)
        knee = p.get('knee_out', 255)
        return np.clip(np.where(mapped>knee, knee+np.maximum(mapped-knee, 0)*p.get('soft_q8_8', 256)//256, mapped),0,255)
    t0, t1 = tone(y0), tone(y1)
    ratio = np.minimum(512, ((t0+t1)*256)//np.maximum(y0+y1, 32))
    blend = p.get('chroma_q8', 0) if p.get('mode', 5)==5 else 0
    scale = np.maximum(256, 256+blend*(ratio-256)//256)
    def peak(y, cu, cv):
        return np.maximum.reduce((y+((103206*cv+32768)>>16),
                                  y+((121609*cu+32768)>>16),
                                  y-((12276*cu+30679*cv+32768)>>16)))
    # Signed chroma, with magnitude rounded conservatively for this estimate.
    pu = np.sign(u)*((np.abs(u)*scale+128)//256)
    pv = np.sign(v)*((np.abs(v)*scale+128)//256)
    input_peak = np.maximum(peak(y0,u,v), peak(y1,u,v))
    predicted_peak = np.maximum(peak(t0,pu,pv), peak(t1,pu,pv))
    return float((np.maximum(input_peak,predicted_peak)>=255-GAMUT_HEADROOM).mean())


def flat_share(payload, width, height):
    """Share of 16x16 luma blocks whose std is below FLAT_STD (2x-decimated, 8x8 samples each)."""
    y = np.frombuffer(payload, np.uint8)[0::2].reshape(height, width)[::2, ::2]
    b = FLAT_BLOCK//2
    h, w = y.shape[0]//b*b, y.shape[1]//b*b
    blocks = y[:h, :w].astype(np.float32).reshape(h//b, b, w//b, b)
    return float((blocks.std(axis=(1, 3)) < FLAT_STD).mean())


class TextureAdaptiveShift:
    """Callable for protocol.Session(frame_shift=...); one instance per session."""
    def __init__(self, width, height, max_shift=MAX_SHIFT, target_fps=TARGET_FPS):
        self.width, self.height, self.max_shift = width, height, max_shift
        self.budget = LINK_BYTES_PER_SECOND/target_fps
        self.near = False
        self.lossless_bytes = None   # exponential average of lossless-equivalent input bytes
        self.last = None
        self.gamut_guard = False
        self.gamut_guard_frames = 0
        self.risk_checks = 0
        self.return_ratio = RETURN_RATIO
        self.returns_observed = 0
        self._frame = None
        self._sent = {}              # frame_id -> lossless-equivalent input bytes, until its return
        self._lock = threading.Lock()  # observe_return() runs on the Session's receive thread

    def __call__(self, frame):
        self._frame = frame.frame_id
        over = self.lossless_bytes is not None and self.lossless_bytes*(1+self.return_ratio) > self.budget
        # Cheapest test first: a frame under the network budget is lossless whatever
        # its content, so neither statistic is needed (71.8 % of 2,948 replayed frames
        # were lossless). The colour-risk estimate (~0.85 ms median) runs only for a
        # frame that could go near-lossless; on skipped frames the colour guard holds
        # its state (its enter/leave hysteresis advances on the frames it decides).
        flat = flat_share(frame.payload, self.width, self.height) if over else None
        candidate = over and flat < (FLAT_LEAVE if self.near else FLAT_ENTER)
        risk = None
        if candidate:
            risk = gamut_risk_share(frame.payload, self.width, self.height, frame.parameters)
            self.gamut_guard = risk >= (GAMUT_LEAVE if self.gamut_guard else GAMUT_ENTER)
            self.risk_checks += 1
        self.gamut_guard_frames += int(self.gamut_guard)
        self.near = candidate and not self.gamut_guard
        self.last = dict(flat_share=None if flat is None else round(flat, 4), lossless_bytes=self.lossless_bytes, over_budget=over,
                         gamut_risk_share=None if risk is None else round(risk, 5), gamut_guard=self.gamut_guard,
                         return_ratio=round(self.return_ratio, 3))
        return self.max_shift if self.near else 0

    def observe(self, shift, wire_bytes):
        equivalent = wire_bytes*(SHIFT1_TO_LOSSLESS if shift else 1.0)
        self.lossless_bytes = equivalent if self.lossless_bytes is None else 0.75*self.lossless_bytes+0.25*equivalent
        if self._frame is not None:
            with self._lock:
                self._sent[self._frame] = equivalent
                if len(self._sent) > 64:      # results never seen (cancelled run): drop the oldest
                    del self._sent[next(iter(self._sent))]

    def observe_return(self, frame_id, shift, wire_bytes):
        with self._lock:
            sent = self._sent.pop(frame_id, None)
        if not sent:
            return
        ratio = wire_bytes*(SHIFT1_TO_LOSSLESS if shift else 1.0)/sent
        low, high = RETURN_RATIO_LIMITS
        self.return_ratio += RETURN_RATIO_WEIGHT*(min(max(ratio, low), high)-self.return_ratio)
        self.returns_observed += 1
