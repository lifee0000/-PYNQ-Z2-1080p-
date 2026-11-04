"""Lossless LZ4 blocks with XXH32 (seed 0), ABI 1.

The library is loaded only when a codec operation is requested. Importing this
module is therefore safe on a board where only the C server supplies the codec.
No enhancement, lossy conversion, networking, or hardware access occurs here.
Output bytes own their storage; thread-local scratch buffers never escape.
"""
import ctypes as C
import operator
from pathlib import Path
import platform
import threading

MAX_RAW_BYTES = 1920 * 1080 * 2  # 1080p FPGA build maximum
FLAG_RAW = 0
FLAG_LZ4 = 1
_LIBRARY = None
_LOAD_LOCK = threading.Lock()
_LOCAL = threading.local()


def _library():
    global _LIBRARY
    if _LIBRARY is None:
        with _LOAD_LOCK:
            if _LIBRARY is None:
                name = "p4_codec.dll" if platform.system() == "Windows" else "libp4_codec.so"
                path = Path(__file__).resolve().with_name(name)
                try:
                    lib = C.CDLL(str(path))
                except OSError as exc:
                    raise RuntimeError(f"Lossless codec library unavailable: {path}. Run native/build_codec.py.") from exc
                for name in ("p4_codec_version", "p4_lz4_version"):
                    getattr(lib, name).argtypes = []
                    getattr(lib, name).restype = C.c_int
                lib.p4_lz4_worthwhile.argtypes=[C.c_void_p,C.c_int]
                lib.p4_lz4_worthwhile.restype=C.c_int
                if lib.p4_codec_version() != 1:
                    raise RuntimeError("Lossless codec ABI mismatch (expected ABI 1)")
                if lib.p4_lz4_version() != 11000:
                    raise RuntimeError("Lossless codec requires bundled LZ4 v1.10.0")
                lib.p4_lz4_compress_bound.argtypes = [C.c_int]
                lib.p4_lz4_compress_bound.restype = C.c_int
                for name in ("p4_lz4_compress", "p4_lz4_decompress"):
                    getattr(lib, name).argtypes = [C.c_void_p, C.c_void_p, C.c_int, C.c_int]
                    getattr(lib, name).restype = C.c_int
                lib.p4_xxh32.argtypes = [C.c_void_p, C.c_int]
                lib.p4_xxh32.restype = C.c_uint32
                _LIBRARY = lib
    return _LIBRARY


def _integer(value, name, lo, hi):
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer, not bool")
    try:
        value = operator.index(value)
    except TypeError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if not lo <= value <= hi:
        raise ValueError(f"{name} outside [{lo}, {hi}]")
    return value


def _payload(data, maximum):
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise TypeError("payload must be bytes, bytearray, or memoryview")
    # Snapshot mutable input before ctypes releases the GIL. Immutable bytes are
    # passed directly to C without an extra input copy.
    data = data if isinstance(data, bytes) else bytes(data)
    if not 1 <= len(data) <= maximum:
        raise ValueError(f"payload length outside [1, {maximum}]")
    return data


def _buffer(name, capacity):
    buffer = getattr(_LOCAL, name, None)
    if buffer is None or len(buffer) < capacity:
        buffer = C.create_string_buffer(capacity)
        setattr(_LOCAL, name, buffer)
    return buffer


def checksum(data):
    """Return XXH32(seed=0) of uncompressed data (integrity, not authentication)."""
    data = _payload(data, MAX_RAW_BYTES)
    return int(_library().p4_xxh32(C.c_char_p(data), len(data)))


def encode(data):
    """Return (immutable wire bytes, flags 0/1, raw XXH32).

    LZ4 is retained only when its size is at most floor(7 * raw_size / 8).
    Less compressible inputs use exact raw bytes with the same checksum.
    """
    data = _payload(data, MAX_RAW_BYTES)
    lib = _library()
    raw_checksum = int(lib.p4_xxh32(C.c_char_p(data), len(data)))
    bound = lib.p4_lz4_compress_bound(len(data))
    out = _buffer("encoded", bound)
    n = lib.p4_lz4_compress(C.c_char_p(data), out, len(data), bound)
    if n <= 0:
        raise RuntimeError("LZ4 compression failed with bounded output storage")
    if n <= (len(data) * 7) // 8:
        return C.string_at(out, n), FLAG_LZ4, raw_checksum
    return data, FLAG_RAW, raw_checksum

def adaptive_encode(data):
    """Skip costly whole-frame compression when spread-out samples predict <2x."""
    data=_payload(data,MAX_RAW_BYTES)
    lib=_library()
    if not lib.p4_lz4_worthwhile(C.c_char_p(data),len(data)):
        return data,FLAG_RAW,int(lib.p4_xxh32(C.c_char_p(data),len(data)))
    return encode(data)


def decode(wire, flags, raw_size, checksum):
    """Validate framing, decompress within raw_size, and verify raw XXH32.

    Malformed LZ4 blocks, truncation, unexpected lengths, unknown flags and
    checksum mismatches raise ValueError. This does not accept LZ4 frame format.
    """
    flags = _integer(flags, "flags", 0, 1)
    raw_size = _integer(raw_size, "raw_size", 1, MAX_RAW_BYTES)
    expected = _integer(checksum, "checksum", 0, 0xffffffff)
    lib = _library()
    maximum = raw_size if flags == FLAG_RAW else lib.p4_lz4_compress_bound(raw_size)
    wire = _payload(wire, maximum)
    if flags == FLAG_RAW:
        if len(wire) != raw_size:
            raise ValueError("raw payload length does not match declared raw_size")
        actual = int(lib.p4_xxh32(C.c_char_p(wire), len(wire)))
        if actual != expected:
            raise ValueError("raw payload XXH32 mismatch")
        return wire
    out = _buffer("decoded", raw_size)
    n = lib.p4_lz4_decompress(C.c_char_p(wire), out, len(wire), raw_size)
    if n != raw_size:
        raise ValueError(f"invalid LZ4 block or decompressed length (got {n}, expected {raw_size})")
    if int(lib.p4_xxh32(out, n)) != expected:
        raise ValueError("decompressed payload XXH32 mismatch")
    return C.string_at(out, n)


def codec_info():
    lib = _library()
    return {"abi": lib.p4_codec_version(), "lz4_version": lib.p4_lz4_version(),
            "checksum": "XXH32 seed=0", "max_raw_bytes": MAX_RAW_BYTES,
            "compressed_retention": "compressed_size <= floor(raw_size*7/8)"}
