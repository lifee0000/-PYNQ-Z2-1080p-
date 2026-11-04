"""Media resize/letterbox and export colour conversion only; all enhancement remains in the FPGA."""
import av
import numpy as np
from geometry import DEFAULT_OUTPUT
# Export colour (2026-11-01): libx264 got rgb24 frames, which swscale converts with
# the BT.601 matrix by default, and the stream carried no colour tags; players assume
# BT.709 for untagged HD video, so the night sky's colours shifted by a mean CIE76
# delta E of 2.99 against the FPGA output (BT.709 export: 1.28; Tokyo 3.59 -> 2.60;
# evidence/mottle_20261101/export_colour.json). Exports now convert with BT.709,
# limited range, and say so in the stream.
AVCOL_BT709, AVCOL_RANGE_MPEG = 1, 1
def tag_bt709(stream):
    cc=stream.codec_context
    cc.colorspace=cc.color_primaries=cc.color_trc=AVCOL_BT709;cc.color_range=AVCOL_RANGE_MPEG
def export_frame(rgb,size=None):
    """yuv420p BT.709 limited-range frame for a tag_bt709 libx264 stream; size resizes (Lanczos)."""
    vf=av.VideoFrame.from_ndarray(rgb,format='rgb24')
    scale=dict(width=size[0],height=size[1],interpolation='LANCZOS') if size and tuple(size)!=(vf.width,vf.height) else {}
    return vf.reformat(format='yuv420p',dst_colorspace='ITU709',dst_color_range=AVCOL_RANGE_MPEG,**scale)
def fit_rgb(frame,width=DEFAULT_OUTPUT[0],height=DEFAULT_OUTPUT[1]):
    if frame.width==width and frame.height==height:
        return frame.to_ndarray(format='rgb24'),None
    ratio=min(width/frame.width,height/frame.height)
    w,h=round(frame.width*ratio),round(frame.height*ratio)
    if min(w,h)<3:raise ValueError('Fitted content must be at least 3x3')
    # swscale combines RGB conversion and Lanczos resize in compiled code.
    fitted=frame.reformat(width=w,height=h,format='rgb24',interpolation='LANCZOS').to_ndarray()
    x,y=(width-w)//2,(height-h)//2
    canvas=np.zeros((height,width,3),np.uint8);canvas[y:y+h,x:x+w]=fitted
    return canvas,(x,y,w,h)
