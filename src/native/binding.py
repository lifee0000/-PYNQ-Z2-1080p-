"""ctypes ABI and lifetime owner. No pynq import needed for host mock tests."""
import ctypes as C
import json
from pathlib import Path

CACHE_OP = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_uint32, C.c_uint32)


class Config(C.Structure):
    _fields_ = [(name, C.c_uint32) for name in (
        "abi", "slot_count", "max_width", "max_height", "port", "mock_backend",
        "dma_timeout_ms", "socket_timeout_ms", "mock_delay_us", "cacheable")]
    _fields_ += [(name, C.c_void_p) for name in ("vdma", "core", "reset_gpio")]
    _fields_ += [(name, C.c_uint32) for name in ("vdma_bytes", "core_bytes", "gpio_bytes")]
    _fields_ += [("parameter_offsets", C.c_uint32 * 24),
                 ("frame_count_offset", C.c_uint32), ("stream_errors_offset", C.c_uint32),
                 ("input", C.c_void_p * 6), ("output", C.c_void_p * 6),
                 ("input_physical", C.c_uint64 * 6), ("output_physical", C.c_uint64 * 6),
                 ("capacity_bytes", C.c_uint64), ("cache_op", CACHE_OP),
                 ("cache_user", C.c_void_p), ("identity_json", C.c_char_p),
                 ("bind_ipv4", C.c_char_p),
                 ("decoder", C.c_void_p*4),("encoder", C.c_void_p),
                 ("codec_mmio_bytes", C.c_uint32),
                 ("wire_input", C.c_void_p*6),("wire_output", C.c_void_p*6),
                 ("wire_input_physical", C.c_uint64*6),("wire_output_physical", C.c_uint64*6),
                 ("wire_capacity_bytes", C.c_uint64), ("decoder_count", C.c_uint32)]


class Native:
    def __init__(self, library, config, keepalive=()):
        self.library = C.CDLL(str(Path(library).resolve()))
        self.library.y50_config_size.restype = C.c_size_t
        if self.library.y50_config_size() != C.sizeof(Config):
            raise RuntimeError("native/Python Config ABI size mismatch")
        self.library.y50_start.argtypes = [C.POINTER(Config), C.c_char_p, C.c_size_t]
        self.library.y50_start.restype = C.c_void_p
        self.library.y50_stop.argtypes = [C.c_void_p]
        self.library.y50_stop.restype = C.c_int
        self.library.y50_destroy.argtypes = [C.c_void_p]
        self.library.y50_destroy.restype = C.c_int
        self.library.y50_status.argtypes = [C.c_void_p, C.c_char_p, C.c_size_t]
        self.library.y50_status.restype = C.c_int
        self.config, self.keepalive = config, keepalive
        error = C.create_string_buffer(2048)
        self.handle = self.library.y50_start(C.byref(config), error, len(error))
        if not self.handle:
            raise RuntimeError(error.value.decode("utf-8", "replace"))

    def status(self):
        data = C.create_string_buffer(131072)
        if self.library.y50_status(self.handle, data, len(data)):
            raise RuntimeError("native status failed")
        return json.loads(data.value)

    def stop(self):
        if self.handle and self.library.y50_stop(self.handle):
            raise RuntimeError("UNSAFE_DMA: retain CMA buffers and MMIO; reboot board before release")

    def close(self):
        if self.handle:
            if self.library.y50_destroy(self.handle):
                raise RuntimeError("UNSAFE_DMA: native refused destruction; keep all allocations alive")
            self.handle = None


ABI = 10


def wire_capacity(width, height):
    """Packet allocation for a Rice/P6TANS02 geometry; same rule as p6_rice_wire_capacity."""
    return (20 + 64 + (height * (width // 32) * 516 + 7) // 8 + 16 + 2 * height + 7) & ~7


def mock(library, width=1920, height=1080, delay_us=0, timeout_ms=2000, bands=3):
    size = width * height * 2
    packet = wire_capacity(width, height)
    buffers = [C.create_string_buffer(size) for _ in range(12)] + [C.create_string_buffer(packet) for _ in range(12)]
    cfg = Config(abi=ABI, slot_count=6, max_width=width, max_height=height,
                 capacity_bytes=size, mock_backend=1, dma_timeout_ms=2000,
                 socket_timeout_ms=timeout_ms, mock_delay_us=delay_us,
                 identity_json=b'{"state":"MOCK_TRANSPORT_ONLY"}', bind_ipv4=b"127.0.0.1",
                 codec_mmio_bytes=0x100,wire_capacity_bytes=packet,decoder_count=bands)
    for i in range(6):
        cfg.input[i], cfg.output[i] = C.addressof(buffers[i]), C.addressof(buffers[i+6])
        cfg.wire_input[i],cfg.wire_output[i]=C.addressof(buffers[i+12]),C.addressof(buffers[i+18])
    return Native(library, cfg, buffers)
