"""YUYV422 v4 fixed-rule luma/chroma spatial filter, independent of video selection.

Only adaptive+filter_enable changes v3. UV uses pair-space, never interleaved
byte neighbours. A strictly isolated impulse is replaced only when its eight
neighbours agree; connected thin lines and edges keep supporting neighbours.
This is not temporal denoising or semantic recognition.
"""
from dataclasses import dataclass,replace
import numpy as np
import reference_v3_frozen as v3

TOP="video_enhance_yuyv422_v4_split_core"
PIXEL_FORMAT="YUYV422_BT709_FULL_YUV_V4_SPLIT"


@dataclass(frozen=True)
class Params(v3.Params):
    noise_floor_uv: int = 2
    # Below 255 (enhance IP 1.2): mode 4 luma is limited to the 3x3 input range
    # +/- this many levels (halo control), and mode 5 adds the 5x5 detail term
    # of _sharpen_mode5 under the same limit. 255: the earlier V4 output.
    overshoot: int = 255
    # Enhance IP 1.4, mode 5: chroma follows the luma tone curve by this share
    # (Q8, 0 = off, 256 = full); see _chroma_gain.
    chroma_q8: int = 0
    # Enhance IP 1.5, modes 4/5: mid-scale local contrast on the enhanced output,
    # packed a | core<<8 | T<<16 | limit<<24 (a in 1/64; 0 = off); see _clarity.
    clarity: int = 0

    def validate(self,width,height):
        super().validate(width,height)
        for name in ("noise_floor_uv","overshoot"):
            value=getattr(self,name)
            if type(value) is not int or not 0<=value<=255:
                raise ValueError(f"{name} must be an integer in 0..255")
        if type(self.chroma_q8) is not int or not 0<=self.chroma_q8<=256:
            raise ValueError("chroma_q8 must be an integer in 0..256")
        if type(self.clarity) is not int or not 0<=self.clarity<=0xffffffff or (self.clarity&255 and not self.clarity>>16&255):
            raise ValueError("clarity must be a 32-bit word with T >= 1 when the strength is not 0")


PARAMETER_ORDER=v3.PARAMETER_ORDER+("noise_floor_uv","overshoot","chroma_q8","clarity")
MODES=v3.MODES
SPATIAL=((1,2,1),(2,0,2),(1,2,1))


def _windows(values):
    h,w=values.shape
    padded=np.pad(values.astype(np.int32),1,mode="edge")
    return [[padded[row:row+h,col:col+w] for col in range(3)] for row in range(3)]


def _neighbours(window):
    return [window[row][col] for row in range(3) for col in range(3) if (row,col)!=(1,1)]


def _impulse_center(window,sigma):
    center=window[1][1]
    neighbours=np.stack(_neighbours(window))
    low,high=neighbours.min(axis=0),neighbours.max(axis=0)
    trimmed=(neighbours.sum(axis=0)-low-high+3)//6
    supported=np.any(np.abs(neighbours-center)<=2*sigma,axis=0)
    impulse=(~supported)&(high-low<=2*sigma)&(np.abs(center-trimmed)>=max(24,4*sigma))
    return np.where(impulse,trimmed,center),impulse


def _range_weight(distance,sigma):
    return np.where(distance<=sigma,4,np.where(distance<=2*sigma,2,
                    np.where(distance<=3*sigma,1,0)))


def _round64(value):
    return np.sign(value)*((np.abs(value)+32)>>6)


def _tone(values,p):
    mapped=(p.gain_q8_8*values+128)//256+p.brightness
    mapped=np.where(mapped>p.knee_out,p.knee_out+
        (np.maximum(mapped-p.knee_out,0)*p.soft_q8_8)//256,mapped)
    return np.clip(mapped,0,255)


def _colour_ceiling(source):
    """Highest luma that keeps every RGB channel <= 255 with the pixel's input chroma (enhance IP 1.3).

    Same rounding as the frozen BT.709 full-range unpack (pixels.py): R = Y+r(V),
    B = Y+b(U), G = Y-g(U,V). Sharpening may raise luma only up to this level, so
    it cannot clip a saturated colour (Tokyo's orange signs lost up to 7 levels
    of red on their edges).
    """
    u=source[:,0::2,1].astype(np.int32)-128;v=source[:,1::2,1].astype(np.int32)-128
    r=(103206*v+32768)>>16;b=(121609*u+32768)>>16;g=(12276*u+30679*v+32768)>>16
    return np.repeat(255-np.maximum(np.maximum(r,b),np.maximum(-g,0)),2,axis=1)


CHROMA_Y0=16
CHROMA_KMAX=512
INV_Y=tuple((1<<16)//max(i,CHROMA_Y0) for i in range(256))
INV_C=tuple((1<<16)//max(i,1) for i in range(256))


def _scale_chroma(values,k):
    c=values.astype(np.int64)-128;s=c*k
    return np.clip(128+np.sign(s)*((np.abs(s)+128)>>8),0,255).astype(np.uint8)


def _chroma_gain(source,frame,p):
    """Enhance IP 1.4: U/V follow the luma tone curve so a luma gain keeps saturation.

    The split core maps only luma through gain/knee; with gain 1.5 every colour
    lost about a quarter of its saturation (night sky teal-grey, foliage grey).
    Per chroma pair, from the input pair: y = pair luma, yo = tone[y],
    kl = yo/max(y,16) (Q8, ROM 1/y), k = min(kl, 2); above 1, k is capped so
    the pair's RGB stays in range at luma yo: (255-yo)/cpos and yo/cneg (ROM 1/c),
    cpos/cneg the most positive/negative of the R, G, B chroma offsets
    (colour-ceiling rounding), and not below 1. k' = 1 + chroma_q8/256*(k-1)
    scales U/V about 128 on the pairs the chroma path owns (not the frame's
    border pairs; inside the ROI only complete pairs). Returns the input with
    its chroma scaled the same way, for the luma colour ceiling. Mode 5 only.
    """
    if p.mode!=5 or not p.chroma_q8:
        return source
    y=source[:,:,0].astype(np.int64)
    pair=(y[:,0::2]+y[:,1::2]+1)//2
    u0=source[:,0::2,1].astype(np.int64)-128;v0=source[:,1::2,1].astype(np.int64)-128
    r=(103206*v0+32768)>>16;b=(121609*u0+32768)>>16;g=-((12276*u0+30679*v0+32768)>>16)
    cpos=np.maximum(np.maximum(r,b),np.maximum(g,0));cneg=np.maximum(np.maximum(-r,-b),np.maximum(-g,0))
    yo=_tone(pair,p).astype(np.int64)
    inv_y=np.array(INV_Y,np.int64);inv_c=np.array(INV_C,np.int64)
    k=np.minimum((yo*inv_y[pair]+128)>>8,CHROMA_KMAX)
    khi=np.where(cpos>0,((255-yo)*inv_c[np.minimum(cpos,255)])>>8,CHROMA_KMAX)
    klo=np.where(cneg>0,(yo*inv_c[np.minimum(cneg,255)])>>8,CHROMA_KMAX)
    k=np.where(k>256,np.maximum(256,np.minimum(k,np.minimum(khi,klo))),k)
    k=256+((p.chroma_q8*(k-256)+128)>>8)
    if p.roi_enable:
        first,last=(p.roi_x+1)//2,(p.roi_x+p.roi_width)//2
        rows,pairs=slice(p.roi_y,p.roi_y+p.roi_height),slice(first,last)
    else:
        rows,pairs=slice(1,-1),slice(1,-1)
    ceiling=source.copy()
    for col in (0,1):
        plane=frame[:,col::2,1]
        plane[rows,pairs]=_scale_chroma(plane[rows,pairs],k[rows,pairs])
        ceiling[:,col::2,1]=_scale_chroma(source[:,col::2,1],k)
    return ceiling


def _limit_overshoot(source,frame,p):
    """Clamp processed mode 4 luma to the 3x3 input range +/- overshoot.

    Same pixels as the core processes: the ROI (neighbours clamped to it) or,
    without ROI, every pixel but the one-pixel frame border. Mode 5's own detail
    term never passes its gate (the bilateral base is within 0.75 sigma of the
    pixel, under the 2 sigma gate); its sharpening is _sharpen_mode5.
    """
    if p.overshoot>=255 or p.mode!=4:
        return
    y=source[:,:,0]
    if p.roi_enable:
        region=(slice(p.roi_y,p.roi_y+p.roi_height),slice(p.roi_x,p.roi_x+p.roi_width))
        window=_windows(y[region])
        crop=lambda b:b
    else:
        region=(slice(1,-1),slice(1,-1))
        window=_windows(y)
        crop=lambda b:b[region]
    stack=np.stack([v for row in window for v in row])
    low,high=crop(stack.min(axis=0)),crop(stack.max(axis=0))
    out=frame[region+(0,)].astype(np.int32)
    out=np.clip(np.clip(out,low-p.overshoot,high+p.overshoot),0,255)
    # Colour ceiling (IP 1.3): above the unsharpened value, luma stops where a channel would clip.
    a,b,c=window[0];d,e,f=window[1];g,hh,i=window[2]
    base=crop((a+2*b+c+2*d+4*e+2*f+g+2*hh+i+8)>>4 if p.filter_enable else e)
    frame[region+(0,)]=np.minimum(out,np.maximum(_colour_ceiling(source)[region],base))


def _g5(values):
    """5x5 binomial [1 4 6 4 1]^2/256, rounded; the border rows/columns are unused."""
    k=(1,4,6,4,1);padded=np.pad(values.astype(np.int32),2,mode="edge");h,w=values.shape
    rows=sum(k[i]*padded[:,i:i+w] for i in range(5))
    return (sum(k[i]*rows[i:i+h] for i in range(5))+128)>>8


def _sharpen_mode5(source,frame,p):
    """Mode 5 detail term (enhance IP 1.2), only while overshoot < 255.

    Mode 5's own detail term never passes its gate, so native footage got no
    sharpening. Here, with b the bilateral-denoised pixel (the input pixel when
    the filter or the noise floor is off) and g the 5x5 binomial of the input:
    d = b - g, soft-cored by sigma = clamp(noise_floor, 1, 32), clipped to
    +/-detail_limit, added after the tone curve with the dark/light weight and
    sharp_q8_8, then limited to the toned 3x3 input range +/- overshoot. The
    term is zero where the 5x5 window leaves the ROI/frame; there the output is
    the earlier tone[b].
    """
    if p.mode!=5 or p.overshoot>=255:
        return
    y=source[:,:,0]
    if p.roi_enable:
        region=(slice(p.roi_y,p.roi_y+p.roi_height),slice(p.roi_x,p.roi_x+p.roi_width));inner=region
    else:
        region=(slice(None),slice(None));inner=(slice(1,-1),slice(1,-1))
    values=y[region].astype(np.int32);window=_windows(values)
    sigma=min(32,max(1,p.noise_floor))
    if p.filter_enable and p.noise_floor:
        center,_=_impulse_center(window,sigma)
        total=np.zeros_like(center)
        for row in range(3):
            for col in range(3):
                if SPATIAL[row][col]:
                    delta=window[row][col]-center
                    total+=SPATIAL[row][col]*_range_weight(np.abs(delta),sigma)*delta
        base=center+_round64(total)
    else:
        base=values
    d=base-_g5(values)
    d=np.clip(np.sign(d)*np.maximum(np.abs(d)-sigma,0),-p.detail_limit,p.detail_limit)
    edge=np.zeros_like(d,dtype=bool);edge[2:-2,2:-2]=True
    d=np.where(edge,d,0)
    weight=np.full_like(base,256)
    weight=np.where(base<p.dark_thr,weight*(base+1)//(p.dark_thr+1),weight)
    weight=np.where(base>p.light_thr,weight*(256-base)//(256-p.light_thr),weight)
    product=weight*p.sharp_q8_8*d
    out=np.clip(_tone(base,p)+np.sign(product)*(np.abs(product)//65536),0,255)
    stack=np.stack([v for row in window for v in row])
    out=np.clip(np.clip(out,_tone(stack.min(axis=0),p)-p.overshoot,_tone(stack.max(axis=0),p)+p.overshoot),0,255)
    out=np.minimum(out,np.maximum(_colour_ceiling(source)[region],_tone(base,p)))
    target=frame[region+(0,)]
    if p.roi_enable:
        target[:,:]=out
    else:
        target[1:-1,1:-1]=out[1:-1,1:-1]


def _luma(y,p):
    if p.noise_floor==0:
        # Split-v4 only: 0 disables Y denoising, exposure still maps the original Y.
        return v3._process(y,replace(p,mode=3))
    window=_windows(y)
    sigma=min(32,max(1,p.noise_floor))
    center,_=_impulse_center(window,sigma)
    total=np.zeros_like(center)
    for row in range(3):
        for col in range(3):
            if SPATIAL[row][col]:
                delta=window[row][col]-center
                total+=SPATIAL[row][col]*_range_weight(np.abs(delta),sigma)*delta
    base=center+_round64(total)
    mapped=_tone(base,p)
    detail=np.where(np.abs(center-base)<max(p.noise_floor,2*sigma),0,center-base)
    detail=np.clip(detail,-p.detail_limit,p.detail_limit)
    weight=np.full_like(base,256)
    weight=np.where(base<p.dark_thr,weight*(base+1)//(p.dark_thr+1),weight)
    weight=np.where(base>p.light_thr,weight*(256-base)//(256-p.light_thr),weight)
    product=weight*p.sharp_q8_8*detail
    correction=np.sign(product)*(np.abs(product)//65536)
    return np.clip(mapped+correction,0,255).astype(np.uint8)


def _chroma(u,v,pair_y,p):
    if p.noise_floor_uv==0:
        return u.copy(),v.copy()
    wu,wv,wy=(_windows(values) for values in (u,v,pair_y))
    sigma=min(32,max(1,p.noise_floor_uv))
    cu,cv=wu[1][1],wv[1][1]
    nu,nv,ny=(np.stack(_neighbours(win)) for win in (wu,wv,wy))
    low_u,high_u=nu.min(axis=0),nu.max(axis=0)
    low_v,high_v=nv.min(axis=0),nv.max(axis=0)
    trimmed_u=(nu.sum(axis=0)-low_u-high_u+3)//6
    trimmed_v=(nv.sum(axis=0)-low_v-high_v+3)//6
    support=np.any(np.maximum(np.abs(nu-cu),np.abs(nv-cv))<=2*sigma,axis=0)
    flat_y=np.all(np.abs(ny-wy[1][1])<=2*sigma,axis=0)
    impulse=(~support)&flat_y&(high_u-low_u<=2*sigma)&(high_v-low_v<=2*sigma)&(
        np.maximum(np.abs(cu-trimmed_u),np.abs(cv-trimmed_v))>=max(24,4*sigma))
    cu,cv=np.where(impulse,trimmed_u,cu),np.where(impulse,trimmed_v,cv)
    total_u,total_v=np.zeros_like(cu),np.zeros_like(cv)
    for row in range(3):
        for col in range(3):
            spatial=SPATIAL[row][col]
            if not spatial:
                continue
            du,dv=wu[row][col]-cu,wv[row][col]-cv
            distance=np.maximum(np.abs(du),np.abs(dv))
            weight=_range_weight(distance,sigma)*spatial
            weight=np.where(np.abs(wy[row][col]-wy[1][1])<=2*sigma,weight,0)
            total_u+=weight*du;total_v+=weight*dv
    return (np.clip(cu+_round64(total_u),0,255).astype(np.uint8),
            np.clip(cv+_round64(total_v),0,255).astype(np.uint8))


def _enhance_core(payload,width,height,params):
    if params.mode!=5 or not params.filter_enable:
        result=v3.enhance(payload,width,height,params)
        if (params.overshoot>=255 or params.mode not in (4,5)) and not (params.mode==5 and params.chroma_q8):
            return result
        frame=v3.unpack(result,width,height);source=v3.unpack(payload,width,height)
        _limit_overshoot(source,frame,params)
        _sharpen_mode5(_chroma_gain(source,frame,params),frame,params)
        return frame.tobytes()
    frame=v3.unpack(payload,width,height)
    source=frame.copy()
    y=source[:,:,0]
    if params.roi_enable:
        x,yy,w,h=params.roi_x,params.roi_y,params.roi_width,params.roi_height
        frame[yy:yy+h,x:x+w,0]=_luma(y[yy:yy+h,x:x+w],params)
        # Only complete pairs strictly inside ROI may change chroma; partial pairs
        # preserve both U/V bytes so pixels outside the ROI cannot be recoloured.
        first_pair=(x+1)//2;last_pair=(x+w)//2
        row_start,row_end=yy,yy+h
        u=source[row_start:row_end,2*first_pair:2*last_pair:2,1]
        v=source[row_start:row_end,2*first_pair+1:2*last_pair:2,1]
        pair_y=((y[row_start:row_end,2*first_pair:2*last_pair:2].astype(np.int32)+
                 y[row_start:row_end,2*first_pair+1:2*last_pair:2].astype(np.int32)+1)//2)
        out_u,out_v=_chroma(u,v,pair_y,params)
        frame[row_start:row_end,2*first_pair:2*last_pair:2,1]=out_u
        frame[row_start:row_end,2*first_pair+1:2*last_pair:2,1]=out_v
    else:
        frame[1:-1,1:-1,0]=_luma(y,params)[1:-1,1:-1]
        pair_y=(y[:,0::2].astype(np.int32)+y[:,1::2].astype(np.int32)+1)//2
        out_u,out_v=_chroma(source[:,0::2,1],source[:,1::2,1],pair_y,params)
        # Keep the first and last chroma pair, and top/bottom row, like Y borders.
        frame[1:-1,2:-2:2,1]=out_u[1:-1,1:-1]
        frame[1:-1,3:-2:2,1]=out_v[1:-1,1:-1]
    _sharpen_mode5(_chroma_gain(source,frame,params),frame,params)
    return frame.tobytes()


def _clarity_table(clarity):
    """|d| -> boost: coring, a tent edge weight (rises to T, back to 0 at 3T) and the limit; no divider."""
    a,core,t,limit=clarity&255,clarity>>8&255,clarity>>16&255,clarity>>24&255
    xc=np.maximum(np.arange(256)-core,0).astype(np.int64)
    tent=np.where(xc<=t,xc,np.where(xc<3*t,(3*t-xc)>>1,0))
    return np.minimum((a*tent+32)>>6,limit)


# The clarity stage's dark/light weight: the core's weight table at the thresholds
# auto always sends (dark 48, light 208), fixed in a ROM (no divider in that stage).
_index=np.arange(256,dtype=np.int64)
CLARITY_WEIGHT=np.where(_index<48,256*(_index+1)//49,np.where(_index>208,256*(256-_index)//48,256))


def _box15(values):
    padded=np.pad(values.astype(np.int64),7,mode="edge");c=padded.cumsum(0).cumsum(1);c=np.pad(c,((1,0),(1,0)))
    return c[15:,15:]-c[:-15,15:]-c[15:,:-15]+c[:-15,:-15]


def _clarity(out,width,height,p):
    """Enhance IP 1.5 clarity stage: mid-scale local contrast on the enhanced output.

    The core's output looked almost unchanged on ordinary scenes; a band-pass
    boost of structure at ~15 pixels (darktable "local contrast"-like, edge
    weighted) gives depth without grain or halos. For each luma pixel Yo whose
    15x15 window lies inside the frame/ROI (modes 4 and 5, clarity != 0):
    d = 3x3 binomial(Yo) - ((15x15 sum)*291+32768)>>16; b = sign(d)*tab[|d|],
    tab[x] = min(limit, (a*tent(xc)+32)>>6), xc = max(x-core,0), tent = xc up to
    T, (3T-xc)>>1 up to 3T, then 0; b *= CLARITY_WEIGHT[Yo]/256 (dark 48 /
    light 208 ramps, rounded half up in magnitude); a raised pixel stops at max(Yo, min(colour ceiling of the
    output chroma, 252)), so clarity never creates new clipping. Chroma is
    passed through.
    """
    if not p.clarity or not p.clarity&255 or p.mode not in (4,5):
        return out
    frame=v3.unpack(out,width,height).copy()
    region=((slice(p.roi_y,p.roi_y+p.roi_height),slice(p.roi_x,p.roi_x+p.roi_width)) if p.roi_enable
            else (slice(None),slice(None)))
    yo=frame[region+(0,)].astype(np.int64)
    a,b,c=(w for w in _windows(yo)[0]);d,e,f=(w for w in _windows(yo)[1]);g,h,i=(w for w in _windows(yo)[2])
    s3=(a+2*b+c+2*d+4*e+2*f+g+2*h+i+8)>>4
    detail=s3-((_box15(yo)*291+32768)>>16)
    boost=np.sign(detail)*_clarity_table(p.clarity)[np.minimum(np.abs(detail),255)]
    product=boost*CLARITY_WEIGHT[yo]
    boost=np.sign(product)*((np.abs(product)+128)>>8)
    inside=np.zeros_like(boost,dtype=bool);inside[7:-7,7:-7]=True
    boost=np.where(inside,boost,0)
    raised=np.clip(yo+boost,0,255)
    ceiling=_colour_ceiling(frame)[region]
    raised=np.where(boost>0,np.minimum(raised,np.maximum(np.minimum(ceiling,252),yo)),raised)
    frame[region+(0,)]=raised
    return frame.tobytes()


def enhance(payload,width,height,params=Params()):
    params.validate(width,height)
    return _clarity(_enhance_core(payload,width,height,params),width,height,params)


pack=v3.pack
unpack=v3.unpack
