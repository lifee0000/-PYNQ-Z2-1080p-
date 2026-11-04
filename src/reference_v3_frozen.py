"""Independent YUYV422/AXI16 v3 candidate. No RGB or board-service dependency.

Byte order is Y0 U0 Y1 V0; uint16 little endian beat = Y | (C << 8).
Every mode preserves every input chroma byte, including Sobel. All arithmetic
uses full-range luma code levels. This is NOT the legacy RGB24 wire format.
"""
from dataclasses import asdict, dataclass
import numpy as np

PIXEL_FORMAT = "YUYV422_BT709_FULL_Y_V3"
TOP = "video_enhance_yuyv422_v3_core"
# Geometry bound only; raised with the 1080p FPGA build. Pixel rules are unchanged.
from geometry import MAX_WIDTH, MAX_HEIGHT

MODES = {"original": 0, "sobel": 1, "gaussian": 2, "brightness": 3,
         "sharpen": 4, "adaptive": 5}
PARAMETER_ORDER = ("width", "height", "mode", "brightness", "gain_q8_8",
    "threshold", "sharp_q8_8", "filter_enable", "knee_out", "soft_q8_8",
    "noise_floor", "detail_limit", "dark_thr", "light_thr", "roi_enable",
    "roi_x", "roi_y", "roi_width", "roi_height", "discard_startup_frame")


@dataclass(frozen=True)
class Params:
    mode: int = 5
    brightness: int = 0
    gain_q8_8: int = 256
    threshold: int = 64
    sharp_q8_8: int = 256
    filter_enable: int = 1
    knee_out: int = 200
    soft_q8_8: int = 128
    noise_floor: int = 2
    detail_limit: int = 32
    dark_thr: int = 48
    light_thr: int = 208
    roi_enable: int = 0
    roi_x: int = 0
    roi_y: int = 0
    roi_width: int = 0
    roi_height: int = 0
    discard_startup_frame: int = 0

    def validate(self, width, height):
        values = asdict(self)
        if any(type(v) is not int for v in (width, height, *values.values())):
            raise ValueError("geometry and parameters must be integers")
        if not (4 <= width <= MAX_WIDTH and width % 2 == 0 and 3 <= height <= MAX_HEIGHT):
            raise ValueError(f"even width 4..{MAX_WIDTH} and height 3..{MAX_HEIGHT} required")
        ranges = {"mode": (0, 5), "brightness": (-255, 255),
            "gain_q8_8": (0, 1024), "sharp_q8_8": (0, 1024),
            "filter_enable": (0, 1), "soft_q8_8": (0, 256),
            "roi_enable": (0, 1), "discard_startup_frame": (0, 0)}
        for name in ("threshold", "knee_out", "noise_floor", "detail_limit",
                     "dark_thr", "light_thr"):
            ranges[name] = (0, 255)
        for name in ("roi_x", "roi_y", "roi_width", "roi_height"):
            ranges[name] = (0, MAX_WIDTH)
        for name, (low, high) in ranges.items():
            if not low <= values[name] <= high:
                raise ValueError(f"{name} outside {low}..{high}")
        if self.roi_enable and not (self.roi_width >= 3 and self.roi_height >= 3
                and self.roi_x + self.roi_width <= width
                and self.roi_y + self.roi_height <= height):
            raise ValueError("ROI must be inside frame and at least 3x3")


def unpack(payload, width, height):
    Params().validate(width, height)
    data = memoryview(payload)
    if data.nbytes != width * height * 2:
        raise ValueError("YUYV payload length mismatch")
    return np.frombuffer(data, dtype=np.uint8).reshape(height, width, 2).copy()


def pack(y, chroma):
    y, chroma = np.asarray(y), np.asarray(chroma)
    if y.dtype != np.uint8 or chroma.dtype != np.uint8 or y.ndim != 2 or y.shape != chroma.shape:
        raise ValueError("same-shape HxW uint8 Y and alternating U/V required")
    Params().validate(y.shape[1], y.shape[0])
    return np.stack((y, chroma), axis=2).tobytes()


def _away_shift(value, shift):
    return np.sign(value) * ((np.abs(value) + (1 << (shift - 1))) >> shift)


def _process(y, p):
    """Compute a fully padded rectangle independently of streaming implementation."""
    padded = np.pad(y.astype(np.int32), 1, mode="edge")
    h, w = y.shape
    samples = [[padded[r:r+h, c:c+w] for c in range(3)] for r in range(3)]
    a, b, c, d, e, f, g, hh, i = [v for row in samples for v in row]
    if p.mode == 0:
        return y.copy()
    if p.mode == 1:
        grad = np.minimum(255, np.abs(c+2*f+i-a-2*d-g) + np.abs(g+2*hh+i-a-2*b-c))
        return np.where(grad > p.threshold, 255, 0).astype(np.uint8)
    smooth = (a+2*b+c+2*d+4*e+2*f+g+2*hh+i+8) // 16
    if p.mode == 2:
        return smooth.astype(np.uint8)
    base = e
    if p.mode in (4, 5) and p.filter_enable:
        base = smooth
        if p.mode == 5:
            sigma = min(32, max(1, p.noise_floor))
            total = np.zeros_like(e)
            spatial = ((1, 2, 1), (2, 0, 2), (1, 2, 1))
            for row in range(3):
                for col in range(3):
                    delta = samples[row][col] - e
                    diff = np.abs(delta)
                    weight = np.where(diff <= sigma, 4, np.where(diff <= 2*sigma, 2,
                                      np.where(diff <= 3*sigma, 1, 0)))
                    total += spatial[row][col] * weight * delta
            base = e + _away_shift(total, 6)
    mapped = (p.gain_q8_8 * base + 128) // 256 + p.brightness
    mapped = np.where(mapped > p.knee_out,
        p.knee_out + (np.maximum(mapped-p.knee_out, 0) * p.soft_q8_8) // 256, mapped)
    mapped = np.clip(mapped, 0, 255)
    if p.mode == 3:
        return mapped.astype(np.uint8)
    gate = p.noise_floor
    if p.mode == 5 and p.filter_enable:
        gate = max(gate, 2 * min(32, max(1, p.noise_floor)))
    detail = e - base
    detail = np.where(np.abs(detail) < gate, 0, detail)
    detail = np.clip(detail, -p.detail_limit, p.detail_limit)
    weight = np.full_like(base, 256)
    weight = np.where(base < p.dark_thr, weight * (base+1) // (p.dark_thr+1), weight)
    # Safe denominator at light_thr=255: high condition is false for all uint8 Y.
    weight = np.where(base > p.light_thr, weight * (256-base) // (256-p.light_thr), weight)
    product = weight * p.sharp_q8_8 * detail
    correction = np.sign(product) * (np.abs(product) // 65536)
    return np.clip((base if p.mode == 4 else mapped) + correction, 0, 255).astype(np.uint8)


def enhance(payload, width, height, params=Params()):
    params.validate(width, height)
    frame = unpack(payload, width, height)
    y = frame[:, :, 0]
    if params.roi_enable:
        x, yy, w, h = params.roi_x, params.roi_y, params.roi_width, params.roi_height
        frame[yy:yy+h, x:x+w, 0] = _process(y[yy:yy+h, x:x+w].copy(), params)
    else:
        processed = _process(y.copy(), params)
        # Match the legacy no-ROI one-pixel bypass convention, also for brightness.
        frame[1:-1, 1:-1, 0] = processed[1:-1, 1:-1]
    return frame.tobytes()
