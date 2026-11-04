"""PC image controls mapped onto the existing enhance-IP 1.5 parameters.

Automatic statistics run first. A frozen control snapshot is applied afterwards
and travels with that frame, including when the network is several frames ahead.
This module changes neither the transport quality nor the FPGA protocol.
"""
from dataclasses import asdict, dataclass, fields
import json
import os
from pathlib import Path
import tempfile
import threading
import time


PRESETS = {'auto': '全自动', 'natural': '自然', 'balanced': '均衡', 'enhanced': '增强'}
CONTROL_LABELS = {
    'brightness': '亮度', 'denoise': '降噪', 'sharpen': '锐化',
    'clarity': '清晰度', 'color_preservation': '色彩保留',
}
CONTROL_RANGES = {name: ((-32, 32) if name == 'brightness' else (0, 100))
                  for name in CONTROL_LABELS}


@dataclass(frozen=True)
class ImageControls:
    preset: str = 'auto'
    # None follows the selected preset and automatic scene analysis.
    brightness: int | None = None
    denoise: int | None = None
    sharpen: int | None = None
    clarity: int | None = None
    color_preservation: int | None = None

    def __post_init__(self):
        if not isinstance(self.preset, str) or self.preset not in PRESETS:
            raise ValueError('未知画质预设')
        for name, (low, high) in CONTROL_RANGES.items():
            value = getattr(self, name)
            if value is not None and (type(value) is not int or not low <= value <= high):
                raise ValueError(f'{CONTROL_LABELS[name]}须为 {low} 至 {high} 的整数')

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        if not isinstance(data, dict) or set(data) - {f.name for f in fields(cls)}:
            raise ValueError('画质配置包含不支持的字段')
        return cls(**data)


class LiveImageControls:
    """The worker never reads a Tk variable; immutable snapshots cross threads.

    Every update gets a revision number and its time (time.perf_counter), so the
    worker can report when a change reached the first processed and displayed frame.
    """
    def __init__(self, settings=None):
        self._lock = threading.Lock()
        self._settings = settings or ImageControls()
        self._revision, self._changed_at = 0, None

    def snapshot(self):
        with self._lock:
            return self._settings

    def revision_snapshot(self):
        """(settings, revision, perf_counter time of that revision or None)."""
        with self._lock:
            return self._settings, self._revision, self._changed_at

    def update(self, settings):
        if not isinstance(settings, ImageControls):
            raise TypeError('ImageControls required')
        with self._lock:
            if settings != self._settings:
                self._settings = settings
                self._revision += 1
                self._changed_at = time.perf_counter()


def controls_snapshot(controls):
    if controls is None:
        return ImageControls()
    result = controls.snapshot() if isinstance(controls, LiveImageControls) else controls
    if not isinstance(result, ImageControls):
        raise TypeError('image_controls must be ImageControls or LiveImageControls')
    return result


def available_controls(mode, automatic=False):
    if automatic and mode == 5:
        return set(CONTROL_LABELS)
    return {3: {'brightness'}, 4: {'sharpen', 'clarity'},
            5: set(CONTROL_LABELS)}.get(mode, set())


def apply_controls(parameters, settings, *, automatic=False):
    """Return new parameters; manual values always win over auto/preset values.

Brightness is an offset to the automatic tone. Other manual knobs are absolute:
denoise 0..100 -> floor 0..12, sharpen -> gain 0..4, clarity -> 0..0.75.
Colour preservation blends the luma-following chroma correction, not saturation.
Only an automatic mode choice may be promoted to mode 5 for its extra controls.
"""
    p = dict(parameters)
    if settings == ImageControls():
        return p
    if automatic and p['mode'] == 4 and (
            settings.denoise is not None or settings.color_preservation is not None
            or settings.brightness not in (None, 0)):
        # Mode 4's noise floor is only a sharpening gate. Promotion must not
        # mistake it for the integrated mode's denoise policy or carry the
        # upscaled-USM gain into unguarded mode-5 grain. Explicit knobs below
        # may still override these conservative defaults, including denoise=0.
        floor = max(2, p['noise_floor'])
        p.update(mode=5, detail_limit=24, filter_enable=1, noise_floor=floor,
                 noise_floor_uv=max(2, p['noise_floor_uv']), overshoot=1,
                 sharp_q8_8=min(p['sharp_q8_8'], 384 if floor >= 3 else 512), chroma_q8=256)
    active = available_controls(p['mode'])
    if not active:
        return p
    if 'sharpen' in active and (settings.preset != 'auto' or settings.sharpen is not None):
        # Current hardware's guarded 5x5 path; retain its halo and colour limits.
        p.update(overshoot=1, detail_limit=min(p['detail_limit'], 24))
        scale = {'auto': 100, 'natural': 60, 'balanced': 85, 'enhanced': 100}[settings.preset]
        p['sharp_q8_8'] = min(1024, (p['sharp_q8_8'] * scale + 50) // 100)
    if 'clarity' in active and settings.preset != 'auto':
        # Natural disables clarity. Balanced halves the existing IP-1.5 strength;
        # enhanced uses it unchanged. The default auto path is byte-for-byte intact.
        # Automatic zero may be an intentional low-key/highlight guard. A
        # preset scales that decision; only an explicit clarity knob overrides
        # it. Fixed modes still need a default profile to start from.
        word = p['clarity'] if automatic else p['clarity'] or ((8 << 24) | (24 << 16) | (6 << 8) | 28)
        scale = {'natural': 0, 'balanced': 50, 'enhanced': 100}[settings.preset]
        strength = ((word & 255) * scale + 50) // 100
        p['clarity'] = (word & 0xffffff00) | strength if strength else 0
    if 'brightness' in active and settings.brightness is not None:
        p['brightness'] = max(-255, min(255, p['brightness'] + settings.brightness))
    if 'denoise' in active and settings.denoise is not None:
        floor = (settings.denoise * 12 + 50) // 100
        p.update(noise_floor=floor, noise_floor_uv=min(floor, 8), filter_enable=int(floor > 0))
    if 'sharpen' in active and settings.sharpen is not None:
        p['sharp_q8_8'] = (settings.sharpen * 1024 + 50) // 100
    if 'clarity' in active and settings.clarity is not None:
        strength = (settings.clarity * 48 + 50) // 100
        core = min(24, max(6, p['noise_floor'] * 2))
        p['clarity'] = strength | (core << 8) | (24 << 16) | (8 << 24) if strength else 0
    if 'color_preservation' in active and settings.color_preservation is not None:
        p['chroma_q8'] = (settings.color_preservation * 256 + 50) // 100
    return p


def default_profile_path():
    override = os.environ.get('PYNQ_VIDEO_SETTINGS_PATH')
    if override:
        return Path(override)
    return Path(os.environ.get('LOCALAPPDATA', str(Path.home() / '.config'))) / 'PYNQVideoV4' / 'image_controls.json'


def save_profile(path, settings):
    """Atomically save image controls only; no IP, password or transport setting."""
    path = Path(path)
    data = json.dumps({'schema': 1, 'image_controls': settings.to_dict()}, indent=2, ensure_ascii=False)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent,
                                         prefix='.' + path.name, suffix='.tmp', delete=False) as stream:
            name = stream.name
            stream.write(data)
        os.replace(name, path)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def load_profile(path):
    path = Path(path)
    if path.stat().st_size > 16384:
        raise ValueError('画质配置文件过大')
    data = json.loads(path.read_text(encoding='utf-8-sig'))
    if not isinstance(data, dict) or set(data) != {'schema', 'image_controls'} or type(data['schema']) is not int or data['schema'] != 1:
        raise ValueError('不支持的画质配置格式')
    return ImageControls.from_dict(data['image_controls'])
