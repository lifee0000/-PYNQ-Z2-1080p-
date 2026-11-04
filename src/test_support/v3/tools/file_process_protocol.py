"""Wire protocol and shared validation for the board-side file processor.

This module is deliberately free of any pynq/NumPy import so the framing and
parameter rules can be unit tested on a host.  The network framing is:

    b"PZV1" + JSON length (u32 BE) + image length (u32 BE) + UTF-8 JSON + image

The first image format is 1280x720 RGB8, exactly 2,764,800 bytes.
"""
import json
import struct


MAGIC = b"PZV1"
HEADER_LENGTH = 12
MAX_JSON_LENGTH = 64 * 1024
DEFAULT_WIDTH = 1280
DEFAULT_HEIGHT = 720
CHANNELS = 3
FRAME_SIZE = DEFAULT_WIDTH * DEFAULT_HEIGHT * CHANNELS
MAX_IMAGE_LENGTH = FRAME_SIZE
PARAMETER_VERSION = 2
ALGORITHM_REVISION = 'enhance-v3-range-denoise'

PARAMETER_RANGES = {
    "mode": (0, 5),
    "brightness": (-255, 255),
    "gain_q8_8": (0, 1024),
    "threshold": (0, 255),
    "sharp_q8_8": (0, 1024),
    "filter_enable": (0, 1),
    "knee_out": (0, 255),
    "soft_q8_8": (0, 256),
    "noise_floor": (0, 255),
    "detail_limit": (0, 255),
    "dark_thr": (0, 255),
    "light_thr": (0, 255),
    "roi_enable": (0, 1),
    "roi_x": (0, 1277), "roi_y": (0, 717),
    "roi_width": (3, 1280), "roi_height": (3, 720),
}
DEFAULT_PARAMETERS = {
    "mode": 0,
    "brightness": 0,
    "gain_q8_8": 256,
    "threshold": 64,
    "sharp_q8_8": 256,
    "filter_enable": 1,
    "knee_out": 200, "soft_q8_8": 128,
    "noise_floor": 2, "detail_limit": 32,
    "dark_thr": 48, "light_thr": 208,
    "roi_enable": 0, "roi_x": 0, "roi_y": 0,
    "roi_width": 1280, "roi_height": 720,
}


class ProtocolError(ValueError):
    """Raised when a peer sends a malformed or over-long message."""


def encode_message(payload, image=b""):
    """Serialize one JSON payload plus optional image bytes."""
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(json_bytes) > MAX_JSON_LENGTH:
        raise ProtocolError("JSON payload exceeds 64 KiB")
    if len(image) > MAX_IMAGE_LENGTH:
        raise ProtocolError("image payload exceeds the configured maximum")
    return MAGIC + struct.pack(">II", len(json_bytes), len(image)) + json_bytes + image


def encode_header(payload, image_length):
    """Serialize only the fixed header plus JSON, without copying image bytes.

    Callers send the returned header and then stream the image separately, so
    a 2.7 MB frame is never concatenated into a single temporary blob.
    """
    if (isinstance(image_length, bool) or not isinstance(image_length, int)
            or not 0 <= image_length <= MAX_IMAGE_LENGTH):
        raise ProtocolError("image payload exceeds the configured maximum")
    json_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(json_bytes) > MAX_JSON_LENGTH:
        raise ProtocolError("JSON payload exceeds 64 KiB")
    return MAGIC + struct.pack(">II", len(json_bytes), image_length) + json_bytes


def decode_message(data):
    """Decode one complete message.  Raises ProtocolError on a malformed one."""
    if len(data) < HEADER_LENGTH:
        raise ProtocolError("message shorter than the 12 byte header")
    if data[:4] != MAGIC:
        raise ProtocolError("bad magic prefix")
    json_len, image_len = struct.unpack(">II", data[4:HEADER_LENGTH])
    if json_len > MAX_JSON_LENGTH:
        raise ProtocolError("JSON payload exceeds 64 KiB")
    if image_len > MAX_IMAGE_LENGTH:
        raise ProtocolError("image payload exceeds the configured maximum")
    if len(data) != HEADER_LENGTH + json_len + image_len:
        raise ProtocolError("message length does not match its header")
    try:
        payload = json.loads(data[HEADER_LENGTH:HEADER_LENGTH + json_len].decode("utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ProtocolError('invalid UTF-8 JSON') from exc
    if not isinstance(payload,dict):
        raise ProtocolError('JSON payload must be an object')
    image = data[HEADER_LENGTH + json_len:HEADER_LENGTH + json_len + image_len]
    return payload, image


class MessageReader:
    """Incremental decoder that handles partial reads and sticky packets."""

    def __init__(self, max_json_length=MAX_JSON_LENGTH, max_image_length=MAX_IMAGE_LENGTH):
        self._max_json_length = max_json_length
        self._max_image_length = max_image_length
        # One full frame plus slack for a sticky control message.  The buffer
        # is preallocated so recv_into can land socket bytes without a chunk
        # copy, and grows only if a peer exceeds the expected geometry.
        self._capacity = HEADER_LENGTH + max_json_length + max_image_length + 65536
        self._buffer = bytearray(self._capacity)
        self._filled = 0

    def _grow(self, extra):
        if self._filled + extra <= len(self._buffer):
            return
        new_size = max(self._filled + extra, len(self._buffer) * 2)
        grown = bytearray(new_size)
        grown[:self._filled] = self._buffer[:self._filled]
        self._buffer = grown
        self._capacity = new_size

    def feed(self, data):
        data = bytes(data)
        self._grow(len(data))
        self._buffer[self._filled:self._filled + len(data)] = data
        self._filled += len(data)

    def receive_view(self, max_bytes):
        """Return a writable memoryview for recv_into; call commit after."""
        self._grow(max_bytes)
        return memoryview(self._buffer)[self._filled:self._filled + max_bytes]

    def commit(self, count):
        if count < 0 or self._filled + count > len(self._buffer):
            raise ProtocolError("receive commit exceeds buffer bounds")
        self._filled += count

    def complete_length(self):
        """Return the byte length of the next complete message, or None.

        Splitting this from ``next_message`` lets the service measure receive
        time separately from JSON/image parsing time.
        """
        if self._filled < HEADER_LENGTH:
            return None
        if self._buffer[:4] != MAGIC:
            raise ProtocolError("bad magic prefix")
        json_len, image_len = struct.unpack(">II", self._buffer[4:HEADER_LENGTH])
        if json_len > self._max_json_length:
            raise ProtocolError("JSON payload exceeds 64 KiB")
        if image_len > self._max_image_length:
            raise ProtocolError("image payload exceeds the configured maximum")
        total = HEADER_LENGTH + json_len + image_len
        return total if self._filled >= total else None

    def next_message(self):
        """Return (payload, image) or None until a full message is buffered."""
        total = self.complete_length()
        if total is None:
            return None
        json_len, image_len = struct.unpack(">II", self._buffer[4:HEADER_LENGTH])
        try:
            payload = json.loads(
                bytes(memoryview(self._buffer)[HEADER_LENGTH:HEADER_LENGTH + json_len]).decode("utf-8"))
        except (ValueError, UnicodeError) as exc:
            raise ProtocolError("invalid UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ProtocolError("JSON payload must be an object")
        # One copy detaches the image from the reusable receive buffer.  The
        # old path built an intermediate full-frame bytes and sliced it again.
        image = bytes(memoryview(self._buffer)[HEADER_LENGTH + json_len:total])
        remaining = self._filled - total
        if remaining:
            self._buffer[:remaining] = self._buffer[total:self._filled]
        self._filled = remaining
        return payload, image


def normalize_parameters(parameters):
    """Validate and return a complete parameter dict, filling defaults."""
    if not isinstance(parameters, dict):
        raise ValueError("parameters must be an object")
    normalized = dict(DEFAULT_PARAMETERS)
    unknown = set(parameters) - set(PARAMETER_RANGES)
    if unknown:
        raise ValueError(f"unknown parameters: {sorted(unknown)}")
    for name, (lower, upper) in PARAMETER_RANGES.items():
        if name in parameters:
            value = parameters[name]
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{name} must be an integer")
            if not lower <= value <= upper:
                raise ValueError(f"{name} must be {lower}..{upper}")
            normalized[name] = value
    if normalized['roi_enable'] and (normalized['roi_x'] + normalized['roi_width'] > DEFAULT_WIDTH
                                    or normalized['roi_y'] + normalized['roi_height'] > DEFAULT_HEIGHT):
        raise ValueError('ROI must be inside the 1280x720 frame')
    return normalized


def reference_parameters(parameters):
    """Translate the wire contract to the independent NumPy v2 API."""
    result = normalize_parameters(parameters)
    mode = result.pop('mode')
    rect = tuple(result.pop(key) for key in ('roi_x', 'roi_y', 'roi_width', 'roi_height'))
    enabled = result.pop('roi_enable')
    result['content_rect'] = rect if enabled else None
    names = ('original', 'sobel', 'gaussian', 'brightness', 'sharpen', 'adaptive')
    return names[mode], result


def normalize_frame(frame_id, image, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Check one RGB8 frame size and return it as bytes."""
    if not isinstance(image, (bytes, bytearray)):
        raise ValueError("image must be bytes")
    image = bytes(image)
    if width != DEFAULT_WIDTH or height != DEFAULT_HEIGHT:
        raise ValueError("first version supports only 1280x720")
    if len(image) != FRAME_SIZE:
        raise ValueError(f"image must be {FRAME_SIZE} bytes, got {len(image)}")
    if isinstance(frame_id, bool) or not isinstance(frame_id, int) or frame_id < 0:
        raise ValueError("frame_id must be a non-negative integer")
    return image
