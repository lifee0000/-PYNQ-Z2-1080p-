"""Acceptance oracle only. The application never calls this CPU reference."""
import ctypes as C
from native import rice_codec as codec
from reference import Params,enhance
def reconstructed_input(raw,shift,width,height,bands=3):
    wire,flag,digest=codec.adaptive_encode(raw,width,height,shift,bands)
    return codec.decode(wire,flag,len(raw),digest)
def returned_output(core,shift,width,height):
    # The board returns raw (unquantised) pixels whenever the encoder's packet is
    # not smaller than the frame, so the size decision uses the P6TANS02 model
    # of encoder IP 5.0; its reconstruction equals the Rice02 one.
    if not shift:return core
    lib=codec._lib();lib.p6_tans02_encode.argtypes=[C.c_void_p,C.c_int,C.c_void_p,C.c_int,C.c_uint,C.c_int,C.c_int]
    lib.p6_tans02_encode.restype=C.c_int
    wire=C.create_string_buffer(codec.wire_capacity(width,height))
    n=lib.p6_tans02_encode(C.c_char_p(core),len(core),wire,len(wire),shift,width,height)
    if n<=0:raise RuntimeError('Near reference encoder failed')
    if n>=len(core):return core
    packet=C.string_at(wire,n)
    return codec.decode(packet,2,len(core),codec.checksum(packet))
def expected(raw,shift,params,width=1920,height=1080,bands=3):
    # Near-lossless reconstruction depends on band boundaries: use the board's count.
    inp=reconstructed_input(raw,shift,width,height,bands)
    core=enhance(inp,width,height,Params(**params))
    return returned_output(core,shift,width,height)
