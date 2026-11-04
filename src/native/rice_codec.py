"""P6 transport: parallel PC Rice03 encode, Rice02 return decode, up to 1920x1080.

This module performs no exposure, denoise, sharpening or other enhancement.
"""
import ctypes as C
from pathlib import Path
import platform,threading
MAX_RAW_BYTES=1920*1080*2
# Largest packet allocation (1080p, incl. the P6TANS02 row index); p6_rice_wire_capacity gives the per-geometry bound.
MAX_WIRE_BYTES=4181864
# ABI 5: return packets are P6TANS02 (FPGA tANS encoder), decoded by p6_rice_decode version 2.
ABI=5
# Rice03 input bands: one per FPGA slice decoder, reported by the board as decoder_bands.
BANDS=(3,4)
_LIB=None
_LOCK=threading.Lock()
_LOCAL=threading.local()

def _lib():
    global _LIB
    if _LIB is None:
        with _LOCK:
            if _LIB is None:
                name='y50_native.dll' if platform.system()=='Windows' else 'liby50_native.so'
                lib=C.CDLL(str(Path(__file__).resolve().with_name(name)))
                lib.p6_rice_codec_abi.restype=C.c_int
                if lib.p6_rice_codec_abi()!=ABI:raise RuntimeError('P6 codec ABI mismatch')
                lib.p6_rice_wire_capacity.argtypes=[C.c_int,C.c_int];lib.p6_rice_wire_capacity.restype=C.c_uint
                lib.p4_xxh32.argtypes=[C.c_void_p,C.c_int];lib.p4_xxh32.restype=C.c_uint32
                lib.p6_rice03_encode.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_int,C.c_int,C.c_int,C.c_int]
                lib.p6_rice03_encode.restype=C.c_int
                lib.p6_rice03_encode_near.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_int,C.c_uint,C.c_int,C.c_int,C.c_int,C.c_int]
                lib.p6_rice03_encode_near.restype=C.c_int
                lib.p6_rice_decode.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_int,C.c_int]
                lib.p6_rice_decode.restype=C.c_int
                _LIB=lib
    return _LIB

def _data(value,maximum):
    if not isinstance(value,(bytes,bytearray,memoryview)):raise TypeError('byte payload required')
    value=value if isinstance(value,bytes) else bytes(value)
    if not 1<=len(value)<=maximum:raise ValueError('P6 payload length')
    return value

def _buffer(name,size):
    b=getattr(_LOCAL,name,None)
    if b is None or len(b)<size:b=C.create_string_buffer(size);setattr(_LOCAL,name,b)
    return b

def checksum(raw):
    raw=_data(raw,MAX_RAW_BYTES)
    return int(_lib().p4_xxh32(C.c_char_p(raw),len(raw)))

def wire_capacity(width,height):
    n=int(_lib().p6_rice_wire_capacity(width,height))
    if not n:raise ValueError('Rice03 requires width a multiple of 128 and at most 1920x1080')
    return n

# Rice03 method 3: layout 2 (full-resolution luma, zero groups), the format of
# the layout-2 FPGA decoders; 1 is layout 1 and is used only for comparison.
METHOD=3

def adaptive_encode(raw,width,height,near_shift=0,bands=3,method=METHOD):
    raw=_data(raw,MAX_RAW_BYTES)
    if type(width)is not int or type(height)is not int or len(raw)!=width*height*2:raise ValueError('Rice03 PC encoder requires a complete YUYV frame')
    lib=_lib()
    dst=_buffer('encoded',wire_capacity(width,height))
    if type(near_shift)is not int or not 0<=near_shift<=3:raise ValueError('near_shift must be 0..3')
    if bands not in BANDS:raise ValueError('Rice03 band count must be 3 or 4')
    if method not in (1,3):raise ValueError('Rice03 method must be 1 or 3')
    n=lib.p6_rice03_encode_near(C.c_char_p(raw),len(raw),dst,len(dst),near_shift,width,height,bands,method)
    if n<=0:raise RuntimeError('P6 Rice03 encoder failed: '+str(n))
    if n>=len(raw):return raw,0,checksum(raw)
    wire=C.string_at(dst,n)
    return wire,3,checksum(wire)

def decode(wire,flags,raw_size,expected):
    if type(flags)is not int or flags not in (0,2,3):raise ValueError('P6 codec flags')
    if type(raw_size)is not int or not 1<=raw_size<=MAX_RAW_BYTES:raise ValueError('P6 raw size')
    if type(expected)is not int or not 0<=expected<=0xffffffff:raise ValueError('P6 checksum')
    wire=_data(wire,MAX_WIRE_BYTES)
    if flags and len(wire)>=raw_size:raise ValueError('Rice wire payload must be smaller than raw; otherwise use raw fallback')
    lib=_lib()
    if flags==0:
        if len(wire)!=raw_size or int(lib.p4_xxh32(C.c_char_p(wire),len(wire)))!=expected:raise ValueError('P6 raw size/checksum mismatch')
        return wire
    if checksum(wire)!=expected:raise ValueError('P6 wire checksum mismatch')
    dst=_buffer('decoded',raw_size)
    n=lib.p6_rice_decode(C.c_char_p(wire),len(wire),dst,len(dst),flags)
    if n!=raw_size:raise ValueError('P6 decoded size mismatch')
    return C.string_at(dst,n)
