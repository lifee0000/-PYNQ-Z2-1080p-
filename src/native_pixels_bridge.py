"""Own every native format buffer through the call; native module has no image filter."""
from pathlib import Path
import ctypes as C
import os
import numpy as np

_root=Path(__file__).resolve().parent
_path=_root/'native_pixels'/('p4_pixels.dll' if os.name=='nt' else 'libp4_pixels.so')
_lib=None
if _path.is_file():
    _lib=C.CDLL(str(_path))
    _lib.p4_pixels_abi.restype=C.c_uint
    if _lib.p4_pixels_abi()!=1:raise RuntimeError('Native pixel ABI mismatch')
    for name in ('p4_pack','p4_unpack'):
        f=getattr(_lib,name)
        f.argtypes=[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t,C.c_uint,C.c_uint]
        f.restype=C.c_int

BACKEND='NATIVE_Q16_FORMAT_ONLY' if _lib is not None else 'NUMPY_Q16_FORMAT_ONLY'
AVAILABLE=_lib is not None
STATISTICS_AVAILABLE=_lib is not None and hasattr(_lib,'p6_yuyv_histogram')
if STATISTICS_AVAILABLE:
    _lib.p6_yuyv_histogram.argtypes=[C.c_void_p,C.c_size_t]+[C.c_uint]*7+[C.c_void_p,C.c_size_t,C.c_void_p,C.c_size_t]
    _lib.p6_yuyv_histogram.restype=C.c_int

def histogram(payload,width,height,x0,y0,w,h,step):
    if not STATISTICS_AVAILABLE or width>16384 or height>16384:return None
    raw=np.frombuffer(payload,np.uint8);hist=np.empty(256,np.uint32);peak=np.empty(256,np.uint16)
    result=_lib.p6_yuyv_histogram(raw.ctypes.data,raw.nbytes,width,height,x0,y0,w,h,step,hist.ctypes.data,256,peak.ctypes.data,256)
    if result:raise ValueError('Native statistics rejected buffers: '+str(result))
    return hist.astype(np.int64),peak

def pack(a):
    a=np.ascontiguousarray(a);h,w=a.shape[:2];out=np.empty((h,w,2),np.uint8)
    result=_lib.p4_pack(a.ctypes.data,a.nbytes,out.ctypes.data,out.nbytes,w,h)
    if result:raise ValueError('Native pack rejected buffers: '+str(result))
    return out.tobytes()

def unpack(payload,w,h):
    frame=np.frombuffer(payload,np.uint8)
    if frame.nbytes!=w*h*2:raise ValueError('complete YUYV payload required')
    out=np.empty((h,w,3),np.uint8)
    result=_lib.p4_unpack(frame.ctypes.data,frame.nbytes,out.ctypes.data,out.nbytes,w,h)
    if result:raise ValueError('Native unpack rejected buffers: '+str(result))
    return out
