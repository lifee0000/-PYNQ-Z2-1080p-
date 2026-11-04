"""Frozen BT.709 full-range Q16 RGB/YUYV conversion; not image enhancement.

Packing reuses two local int32 planes. Preview decoding uses small immutable
tables and computes each shared chroma term once per pair. Both paths retain
the original rounding, per-pixel chroma clipping and rounded pair averaging.
"""
import numpy as np
import native_pixels_bridge as _native
from geometry import MAX_WIDTH, MAX_HEIGHT

FORMAT_BACKEND=_native.BACKEND


_FORWARD = ((13933, 46871, 4732), (-7509, -25259, 32768),
            (32768, -29763, -3005))


def _preview_tables():
    levels = np.arange(256, dtype=np.int32)
    chroma = levels - 128
    red = np.clip(levels[:, None] + ((103206*chroma[None, :]+32768) >> 16),
                  0, 255).astype(np.uint8)
    blue = np.clip(levels[:, None] + ((121609*chroma[None, :]+32768) >> 16),
                   0, 255).astype(np.uint8)
    green = ((12276*chroma[:, None]+30679*chroma[None, :]+32768) >> 16).astype(np.int16)
    for table in (red, blue, green):
        table.flags.writeable = False
    return red, blue, green


# 256 KiB total; no full-frame table or mutable shared frame workspace.
_RED, _BLUE, _GREEN = _preview_tables()


def _geometry(w, h):
    if (isinstance(w, (bool, np.bool_)) or isinstance(h, (bool, np.bool_))
            or not isinstance(w, (int, np.integer))
            or not isinstance(h, (int, np.integer))
            or not (4 <= w <= MAX_WIDTH and w % 2 == 0 and 3 <= h <= MAX_HEIGHT)):
        raise ValueError(f'even width 4..{MAX_WIDTH} and height 3..{MAX_HEIGHT} required')
    return int(w), int(h)


def pack_rgb_numpy(rgb):
    a = np.asarray(rgb)
    if a.dtype != np.uint8 or a.ndim != 3 or a.shape[2] != 3:
        raise ValueError('HxWx3 uint8 RGB required')
    h, w = a.shape[:2]
    _geometry(w, h)
    r, g, b = (a[:, :, i] for i in range(3))
    raw = np.empty((h, w, 2), np.uint8)
    plane = np.empty((h, w), np.int32)
    scratch = np.empty_like(plane)
    for component, (cr, cg, cb) in enumerate(_FORWARD):
        np.multiply(r, cr, out=plane, dtype=np.int32)
        np.multiply(g, cg, out=scratch, dtype=np.int32)
        np.add(plane, scratch, out=plane)
        np.multiply(b, cb, out=scratch, dtype=np.int32)
        np.add(plane, scratch, out=plane)
        np.add(plane, 32768, out=plane)
        np.right_shift(plane, 16, out=plane)
        if component:
            np.add(plane, 128, out=plane)
        np.clip(plane, 0, 255, out=plane)
        if component:
            pair = plane[:, 0::2]
            np.add(pair, plane[:, 1::2], out=pair)
            np.add(pair, 1, out=pair)
            np.right_shift(pair, 1, out=pair)
            raw[:, component-1::2, 1] = pair
        else:
            raw[:, :, 0] = plane
    return raw.tobytes()


def unpack_rgb_numpy(payload, w, h):
    w, h = _geometry(w, h)
    try:
        frame = np.frombuffer(payload, np.uint8)
    except (TypeError, ValueError, BufferError) as exc:
        raise ValueError('complete contiguous YUYV byte buffer required') from exc
    if frame.size != w*h*2:
        raise ValueError('complete YUYV payload required')
    frame = frame.reshape(h, w, 2)
    y, u, v = frame[:, :, 0], frame[:, 0::2, 1], frame[:, 1::2, 1]
    result = np.empty((h, w, 3), np.uint8)
    green = _GREEN[u, v]
    for offset in (0, 1):
        yy = y[:, offset::2]
        result[:, offset::2, 0] = _RED[yy, v]
        result[:, offset::2, 1] = np.clip(yy-green, 0, 255)
        result[:, offset::2, 2] = _BLUE[yy, u]
    return result

def pack_rgb(rgb):
    a=np.asarray(rgb)
    if a.dtype!=np.uint8 or a.ndim!=3 or a.shape[2]!=3:
        raise ValueError('HxWx3 uint8 RGB required')
    h,w=a.shape[:2];_geometry(w,h)
    return _native.pack(a) if _native.AVAILABLE else pack_rgb_numpy(a)

def unpack_rgb(payload,w,h):
    w,h=_geometry(w,h)
    if not _native.AVAILABLE:return unpack_rgb_numpy(payload,w,h)
    try:return _native.unpack(payload,w,h)
    except (TypeError,ValueError,BufferError) as exc:raise ValueError('complete contiguous YUYV byte buffer required') from exc
