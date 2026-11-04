"""Bounded integer auto-exposure controller; PC experiment, no board access.

One policy applies to every frame. It does not identify faces, materials or
intentional grain. Parameters fit the existing mode-5 register interface.
Histogram/peak measurements and temporal decisions execute on the PC.
"""
import numpy as np

AUTO_POLICY = 'histogram-gamut-v4-p0-observed-noise'
COLOR_MATRIX = 'BT709_FULL_Q16_YUYV_PAIR_ROUND'
MAX_HISTOGRAM_SAMPLES = 65536
MAX_NOISE_PATCHES = 64
KNEES = (208,176,144,112,80,64,48,32,16,0)


def luminance(rgb):
    image = np.asarray(rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3:
        raise ValueError('uint8 HxWx3 RGB required')
    wide = image.astype(np.int32)
    return ((13933*wide[...,0]+46871*wide[...,1]+4732*wide[...,2]+32768)>>16).astype(np.uint8)


def _crop(rgb, rect):
    image = np.asarray(rgb)
    if image.dtype != np.uint8 or image.ndim != 3 or image.shape[2] != 3 or not image.size:
        raise ValueError('nonempty uint8 HxWx3 RGB required')
    if rect is None:
        return image
    if len(rect)!=4 or any(isinstance(x,(bool,np.bool_)) or
            not isinstance(x,(int,np.integer)) for x in rect):
        raise ValueError('integer content ROI required')
    x,y,w,h = map(int,rect)
    if x<0 or y<0 or w<1 or h<1 or x+w>image.shape[1] or y+h>image.shape[0]:
        raise ValueError('ROI outside image')
    return image[y:y+h,x:x+w]


def _percentile(hist, rank, denominator=1000):
    n = int(sum(hist))
    if n<=0:
        return 0
    target = max(1,(n*rank+denominator-1)//denominator)
    return int(np.searchsorted(np.cumsum(hist,dtype=np.int64),target))


def _empty_noise_channel():
    return dict(sigma_q8=None,confidence_q8=0,accepted_patches=0,
        status='insufficient-evidence',gaussian=dict(sigma_q8=None,confidence_q8=0),
        impulse=dict(candidate_count=0,sampled_centres=0,confidence_q8=0,
            interpretation='ambiguous-isolated-events',used_for_filter=False),
        compression=dict(confidence_q8=0,blocking_confidence_q8=0,ringing_or_texture_confidence_q8=0,status='insufficient-evidence',
            interpretation='grid-discontinuity-candidate',used_for_filter=False),
        saturated_fraction_q8=0)


def _estimate_patch_grid(gray, origins=None, horizontal_scale=1):
    """Estimate observed channel noise, never a pre-clipping sensor sigma.

    Mean brightness does not reject dark/highlight patches. Nearly censored
    patches remain unknown; a zero MAD alone cannot prove they are noise free.
    Sparse outliers and codec-like grid jumps are diagnostics only: a single
    frame cannot distinguish them from real lights, text or tiled objects.
    """
    p = gray.astype(np.int32)
    count = p.shape[1]*p.shape[2]
    mean = (p.sum(axis=(1,2),dtype=np.int64)+count//2)//count
    centred = p-mean[:,None,None]
    energy = (centred*centred).sum(axis=(1,2),dtype=np.int64)
    covariance_h = np.abs((centred[:,:,:-1]*centred[:,:,1:]).sum(axis=(1,2),dtype=np.int64))
    covariance_v = np.abs((centred[:,:-1,:]*centred[:,1:,:]).sum(axis=(1,2),dtype=np.int64))
    blocks = (p[:,:-1,:-1]+p[:,:-1,1:]+p[:,1:,:-1]+p[:,1:,1:]+2)//4
    bcount = blocks.shape[1]*blocks.shape[2]
    bmean = (blocks.sum(axis=(1,2),dtype=np.int64)+bcount//2)//bcount
    benergy = ((blocks-bmean[:,None,None])**2).sum(axis=(1,2),dtype=np.int64)
    saturated = ((p==0)|(p==255)).sum(axis=(1,2))
    good = (energy<=count*24*24)&(saturated*10<count*9)
    good &= (energy==0)|(np.maximum(covariance_h,covariance_v)*100<=energy*45)
    good &= benergy<=bcount*9*9
    used = int(np.count_nonzero(good))
    result = _empty_noise_channel()
    result.update(accepted_patches=used,
        saturated_fraction_q8=(int(saturated.sum())*256+p.size//2)//p.size)
    high = (p[:,:-2,:-2]-2*p[:,:-2,1:-1]+p[:,:-2,2:]-2*p[:,1:-1,:-2]
        +4*p[:,1:-1,1:-1]-2*p[:,1:-1,2:]+p[:,2:,:-2]-2*p[:,2:,1:-1]+p[:,2:,2:])
    if used>=4:
        values = np.abs(high[good]).ravel()
        median = int(np.partition(values,len(values)//2)[len(values)//2])
        sigma = (median*65536+518)//1036
        confidence = min(256,used*32)
        # Quantisation/censoring invalidates the ordinary Gaussian calibration.
        # Retain a useful observed residual scale with reduced evidence score.
        if np.any(saturated[good]):
            confidence = min(192,confidence)
        result.update(sigma_q8=sigma,confidence_q8=confidence,
            status='observed-flat' if sigma==0 else 'observed-stochastic-residual')
        result['gaussian'] = dict(sigma_q8=sigma,confidence_q8=confidence,
            calibration='highpass-MAD-observed-domain',censoring_corrected=False)
    elif np.all(saturated*10>=count*9):
        result['status'] = 'clipped-unidentifiable'

    neighbours = np.stack([p[:,dy:dy+p.shape[1]-2,dx:dx+p.shape[2]-2]
        for dy in range(3) for dx in range(3) if (dy,dx)!=(1,1)])
    local_min,local_max = neighbours.min(axis=0),neighbours.max(axis=0)
    centre = p[:,1:-1,1:-1]
    isolated = (local_max-local_min<=4)&((centre<local_min-12)|(centre>local_max+12))
    events = int(isolated.sum())
    occupied = int(np.count_nonzero(isolated.any(axis=(1,2))))
    result['impulse'].update(candidate_count=events,sampled_centres=int(centre.size),
        confidence_q8=min(256,occupied*32,events*16))
    if events and result['sigma_q8']==0:
        result['status'] = 'flat-background-with-ambiguous-isolated-events'
    # Negative lag-two correlation records oscillation, also produced by real
    # fine textures. It is an ambiguity score, never a codec classification.
    lag2_h = (centred[:,:,:-2]*centred[:,:,2:]).sum(axis=(1,2),dtype=np.int64)
    lag2_v = (centred[:,:-2,:]*centred[:,2:,:]).sum(axis=(1,2),dtype=np.int64)
    oscillating = (energy>0)&(np.minimum(lag2_h,lag2_v)*100 < -energy*35)
    ringing = min(256,int(oscillating.sum())*16)
    result['compression'].update(ringing_or_texture_confidence_q8=ringing)
    if origins is not None:
        # Each plane uses native sample coordinates; UV has half the horizontal
        # resolution. Positions retain the original image's 8-pixel phase.
        oy = np.asarray([y for y,x in origins])[:,None,None]
        ox = np.asarray([x for y,x in origins])[:,None,None]
        dh,dv = np.abs(np.diff(p,axis=2)),np.abs(np.diff(p,axis=1))
        hm = np.broadcast_to(((ox+np.arange(p.shape[2]-1)[None,None,:]+1)*horizontal_scale)%8==0,dh.shape)
        vm = np.broadcast_to((oy+np.arange(p.shape[1]-1)[None,:,None]+1)%8==0,dv.shape)
        border = np.concatenate((dh[hm],dv[vm]))
        interior = np.concatenate((dh[~hm],dv[~vm]))
        confidence = 0
        border_q8 = interior_q8 = 0
        if border.size and interior.size:
            border_q8 = (int(border.sum())*256+border.size//2)//border.size
            interior_q8 = (int(interior.sum())*256+interior.size//2)//interior.size
            if border_q8>=interior_q8*2+2*256:
                confidence = min(256,len(p)*16,(border_q8-interior_q8)//4)
        result['compression'].update(confidence_q8=max(confidence,ringing),
            blocking_confidence_q8=confidence,
            status='ambiguous-artifact-or-texture' if confidence or ringing else 'no-detected-signature',
            boundary_difference_q8=border_q8,interior_difference_q8=interior_q8,
            sampled_boundary_pairs=int(border.size),codec_identity_known=False)
    return result


def _summarize_noise(estimates, sampled_patches):
    valid = [(row['sigma_q8'],row['confidence_q8']) for row in estimates.values()
             if row['sigma_q8'] is not None and row['confidence_q8']>=128]
    filtering = max(valid,default=(None,0),key=lambda item:-1 if item[0] is None else item[0])
    uv_valid = [(estimates[key]['sigma_q8'],estimates[key]['confidence_q8']) for key in ('u','v')
        if estimates[key]['sigma_q8'] is not None and estimates[key]['confidence_q8']>=128]
    uv = max(uv_valid,default=(None,0),key=lambda item:-1 if item[0] is None else item[0])
    return dict(sigma_q8=estimates['y']['sigma_q8'],confidence_q8=estimates['y']['confidence_q8'],
        accepted_patches=estimates['y']['accepted_patches'],
        y_sigma_q8=estimates['y']['sigma_q8'],u_sigma_q8=estimates['u']['sigma_q8'],
        v_sigma_q8=estimates['v']['sigma_q8'],channels=estimates,
        uv_sigma_q8=uv[0],uv_confidence_q8=uv[1],
        filter_sigma_q8=filtering[0],filter_confidence_q8=filtering[1],
        sampled_patches=sampled_patches,native_pixels=sampled_patches*144,color_matrix=COLOR_MATRIX,
        observation_domain='quantized-clipped-channel-observations',
        evidence_scores_are_probabilities=False,spatial_sampling_only=True)


def _noise(region, origin_x=0, origin_y=0):
    h,w = region.shape[:2]
    side = 12
    ys = np.unique(np.linspace(0,h-side,min(8,h//side),dtype=int)) if h>=side else []
    xs = np.unique(np.linspace(0,w-side,min(8,w//side),dtype=int)) if w>=side else []
    # Skip incomplete pairs at either ROI edge, including odd-X ROIs.
    xs = [int(x+((x+origin_x)&1)) for x in xs if x+((x+origin_x)&1)+side<=w]
    starts = [(int(y),x) for y in ys for x in xs]
    patches = [region[y:y+side,x:x+side] for y,x in starts]
    estimates = {name:_empty_noise_channel() for name in ('y','u','v')}
    if patches:
        rgb = np.stack(patches).astype(np.int32)
        r,g,b = (rgb[:,:,:,i] for i in range(3))
        yy = ((13933*r+46871*g+4732*b+32768)>>16).astype(np.uint8)
        uu = np.clip(((-7509*r-25259*g+32768*b+32768)>>16)+128,0,255).astype(np.uint16)
        vv = np.clip(((32768*r-29763*g-3005*b+32768)>>16)+128,0,255).astype(np.uint16)
        uu = ((uu[:,:,0::2]+uu[:,:,1::2]+1)//2).astype(np.uint8)
        vv = ((vv[:,:,0::2]+vv[:,:,1::2]+1)//2).astype(np.uint8)
        for key,plane in (('y',yy),('u',uu),('v',vv)):
            scale = 1 if key=='y' else 2
            origins = [(y+origin_y,(x+origin_x)//scale) for y,x in starts]
            estimates[key] = _estimate_patch_grid(plane,origins,scale)
    return _summarize_noise(estimates,len(patches))


def analyze_v4(rgb, content_rect=None, max_samples=MAX_HISTOGRAM_SAMPLES):
    """One bounded RGB scan, then 256 bins per candidate; never full-frame LUT scans."""
    region = _crop(rgb,content_rect)
    if isinstance(max_samples,bool) or not isinstance(max_samples,(int,np.integer)) or not 1<=max_samples<=MAX_HISTOGRAM_SAMPLES:
        raise ValueError('sample budget must be an integer in 1..65536')
    step = 1
    while ((region.shape[0]+step-1)//step)*((region.shape[1]+step-1)//step)>max_samples:
        step+=1
    sample = region[::step,::step]
    y = luminance(sample).ravel()
    hist = np.bincount(y,minlength=256)
    # Predict headroom in the actual pair-decoded YUYV colour space. Chroma
    # sharing can change RGB peaks even before enhancement; source RGB peaks
    # alone would miss this. Only bounded sampled pixels and mates are read.
    full = np.asarray(rgb)
    x0,y0 = (0,0) if content_rect is None else (int(content_rect[0]),int(content_rect[1]))
    rows = y0+np.arange(0,region.shape[0],step)
    cols = x0+np.arange(0,region.shape[1],step)
    mates = full[rows[:,None],np.minimum(cols^1,full.shape[1]-1)[None,:]].astype(np.int32)
    source = sample.astype(np.int32)
    def chroma(values,coeff):
        return np.clip(((values[...,0]*coeff[0]+values[...,1]*coeff[1]+values[...,2]*coeff[2]+32768)>>16)+128,0,255)
    u = (chroma(source,(-7509,-25259,32768))+chroma(mates,(-7509,-25259,32768))+1)//2-128
    v = (chroma(source,(32768,-29763,-3005))+chroma(mates,(32768,-29763,-3005))+1)//2-128
    sy = y.reshape(sample.shape[:2]).astype(np.int32)
    decoded_peak = np.clip(np.maximum.reduce((sy+((103206*v+32768)>>16),
        sy-((12276*u+30679*v+32768)>>16),sy+((121609*u+32768)>>16))),0,255)
    peak = np.zeros(256,np.uint16)
    np.maximum.at(peak,y,decoded_peak.ravel())
    total = int(hist.sum())
    shadow = hist.copy();shadow[:16]=0;shadow[96:]=0
    stats = dict(histogram=hist.tolist(),max_rgb_by_luma=peak.tolist(),
        sample_count=total,sample_step=step,region_pixels=int(region.shape[0]*region.shape[1]),
        mean_q8=(int(np.dot(hist,np.arange(256,dtype=np.int64)))*256+total//2)//total,
        dark_ratio_q8=(int(hist[:32].sum())*256+total//2)//total,
        shadow_ratio_q8=(int(shadow.sum())*256+total//2)//total,
        shadow_median=_percentile(shadow,500),
        white_ratio_q8=(int(hist[250:].sum())*256+total//2)//total,
        color_matrix=COLOR_MATRIX,gamut_guard_space='PAIR_RECONSTRUCTED_RGB',
        rgb_positions_read_upper_bound=2*total,
        quantiles={key:_percentile(hist,q) for key,q in
            (('p001',1),('p01',10),('p05',50),('p10',100),('p25',250),
             ('p50',500),('p75',750),('p90',900),('p95',950),('p99',990),('p999',999))})
    return stats,_noise(region,x0,y0)


def analyze_yuyv_v4(payload, width, height, content_rect=None, max_samples=MAX_HISTOGRAM_SAMPLES,*,_native=True):
    """Analyze an already-packed BT709 full-range YUYV frame without RGB repacking.

    Y histogram, pair-reconstructed RGB peaks and native Y/UV noise positions
    are exactly those of ``analyze_v4(original_rgb)`` after the frozen pack.
    No full RGB reconstruction and no second RGB->YUYV conversion occurs.
    """
    if (type(width) is not int or type(height) is not int or width<2 or width%2 or height<1):
        raise ValueError('positive height and even YUYV width required')
    if isinstance(max_samples,bool) or not isinstance(max_samples,(int,np.integer)) or not 1<=max_samples<=MAX_HISTOGRAM_SAMPLES:
        raise ValueError('sample budget must be an integer in 1..65536')
    view = memoryview(payload)
    if not view.c_contiguous or view.nbytes!=width*height*2:
        raise ValueError('contiguous complete YUYV frame required')
    raw = np.frombuffer(view,dtype=np.uint8).reshape(height,width,2)
    if content_rect is None:
        x0,y0,w,h = 0,0,width,height
    else:
        if len(content_rect)!=4 or any(isinstance(x,(bool,np.bool_)) or
                not isinstance(x,(int,np.integer)) for x in content_rect):
            raise ValueError('integer content ROI required')
        x0,y0,w,h = map(int,content_rect)
        if x0<0 or y0<0 or w<1 or h<1 or x0+w>width or y0+h>height:
            raise ValueError('ROI outside image')
    step = 1
    while ((h+step-1)//step)*((w+step-1)//step)>max_samples:
        step+=1
    rows = y0+np.arange(0,h,step)
    cols = x0+np.arange(0,w,step)
    yplane = raw[:,:,0]
    uplane,vplane = raw[:,0::2,1],raw[:,1::2,1]
    measured=None
    if _native:
        from native_pixels_bridge import histogram
        measured=histogram(view,width,height,x0,y0,w,h,step)
    if measured is not None:hist,peak=measured
    else:
        sy = yplane[rows[:,None],cols[None,:]].astype(np.int32)
        u = uplane[rows[:,None],(cols//2)[None,:]].astype(np.int32)-128
        v = vplane[rows[:,None],(cols//2)[None,:]].astype(np.int32)-128
        peak_rgb = np.clip(np.maximum.reduce((sy+((103206*v+32768)>>16),
            sy-((12276*u+30679*v+32768)>>16),sy+((121609*u+32768)>>16))),0,255)
        hist = np.bincount(sy.ravel(),minlength=256)
        peak = np.zeros(256,np.uint16)
        np.maximum.at(peak,sy.ravel(),peak_rgb.ravel())
    total = int(hist.sum())
    shadow = hist.copy();shadow[:16]=0;shadow[96:]=0
    stats = dict(histogram=hist.tolist(),max_rgb_by_luma=peak.tolist(),
        sample_count=total,sample_step=step,region_pixels=w*h,
        mean_q8=(int(np.dot(hist,np.arange(256,dtype=np.int64)))*256+total//2)//total,
        dark_ratio_q8=(int(hist[:32].sum())*256+total//2)//total,
        shadow_ratio_q8=(int(shadow.sum())*256+total//2)//total,
        shadow_median=_percentile(shadow,500),
        white_ratio_q8=(int(hist[250:].sum())*256+total//2)//total,
        color_matrix=COLOR_MATRIX,gamut_guard_space='PAIR_RECONSTRUCTED_RGB',
        rgb_positions_read_upper_bound=0,yuyv_positions_read_upper_bound=total,
        quantiles={key:_percentile(hist,q) for key,q in
            (('p001',1),('p01',10),('p05',50),('p10',100),('p25',250),
             ('p50',500),('p75',750),('p90',900),('p95',950),('p99',990),('p999',999))})
    side = 12
    ys = np.unique(np.linspace(0,h-side,min(8,h//side),dtype=int)) if h>=side else []
    xs = np.unique(np.linspace(0,w-side,min(8,w//side),dtype=int)) if w>=side else []
    xs = [int(x+((x+x0)&1)) for x in xs if x+((x+x0)&1)+side<=w]
    starts = [(y0+int(y),x0+x) for y in ys for x in xs]
    estimates = {name:_empty_noise_channel() for name in ('y','u','v')}
    if starts:
        pr = np.array([y for y,x in starts])[:,None,None]+np.arange(12)[None,:,None]
        pc = np.array([x for y,x in starts])[:,None,None]+np.arange(12)[None,None,:]
        uvpc = np.array([x//2 for y,x in starts])[:,None,None]+np.arange(6)[None,None,:]
        for name,patches in (('y',yplane[pr,pc]),('u',uplane[pr,uvpc]),('v',vplane[pr,uvpc])):
            scale = 1 if name=='y' else 2
            origins = [(y,x//scale) for y,x in starts]
            estimates[name] = _estimate_patch_grid(patches,origins,scale)
    noise = _summarize_noise(estimates,len(starts))
    return stats,noise


def tone_lut(gain_q8_8, knee_out, soft_q8_8):
    y = np.arange(256,dtype=np.int32)
    mapped = (y*int(gain_q8_8)+128)>>8
    return np.clip(np.where(mapped>knee_out,
        knee_out+((mapped-knee_out)*int(soft_q8_8))//256,mapped),0,255)


def noise_gain_cap(sigma_q8):
    """Continuous integer ceiling; no 384/320 discontinuity at sigma=4."""
    if sigma_q8 is None:
        return 384
    s = max(0,int(sigma_q8))
    if s<=2*256:
        return 384
    if s<=6*256:
        return 384-((s-2*256)*64+512)//1024
    if s<=12*256:
        return 320-((s-6*256)*32+768)//1536
    return max(256,288-((s-12*256)*32+1024)//2048)


def _target_gain(stats, noise):
    median = stats['quantiles']['p50']
    if median<=12 and stats['dark_ratio_q8']>=218:
        return 256,'black-level-protection'
    if median<96:
        level,target = max(24,median),96
        reason = 'global-underexposure'
    elif stats['shadow_ratio_q8']>=26 and 16<=stats['shadow_median']<80:
        level,target = max(24,stats['shadow_median']),80
        reason = 'measured-shadow-region'
    else:
        return 256,'normal-exposure'
    return min(noise_gain_cap(noise.get('sigma_q8')),
        max(256,(target*256+level//2)//level)),reason


def _select_curve(stats, gain, fixed_gain=False):
    """At most 41 LUTs x 256 bins, with an explicit identity candidate.

    Peak-by-luma is a conservative upper bound for the sampled RGB pixels.
    This is a sampling guard, not a guarantee for unobserved full-frame peaks.
    """
    gains = [int(gain)] if fixed_gain else sorted({int(gain),
        256+(gain-256)*3//4,256+(gain-256)//2,256+(gain-256)//4},reverse=True)
    definitions = [(256,224,256)]
    for g in gains:
        if g<=256:
            continue
        white = (g*255+128)>>8
        for knee in KNEES:
            soft = min(256,max(1,((255-knee)*256)//max(1,white-knee)))
            definitions.append((g,knee,soft))
    gs = np.array([p[0] for p in definitions],np.int32)[:,None]
    ks = np.array([p[1] for p in definitions],np.int32)[:,None]
    ss = np.array([p[2] for p in definitions],np.int32)[:,None]
    y = np.arange(256,dtype=np.int32)[None,:]
    mapped = (gs*y+128)>>8
    curves = np.clip(np.where(mapped>ks,ks+((mapped-ks)*ss)//256,mapped),0,255)
    hist = np.asarray(stats['histogram'],np.int64)
    peaks = np.asarray(stats['max_rgb_by_luma'],np.int32)
    delta = curves-y
    occupied = hist>0
    # Already-saturated bins cannot gain further. Other bins retain 2 codes
    # of headroom; no sampled near-saturated colour may newly clip to 255.
    allowed = np.maximum(peaks,253)
    unsafe = ((peaks[None,:]+delta)>allowed[None,:]) & occupied[None,:]
    safe = ~np.any(unsafe,axis=1)
    safe &= np.all((delta>=-2) | ~occupied[None,:],axis=1)
    safe &= (curves[:,0]==0)&(curves[:,-1]>=253)
    shadow_weights = hist.copy();shadow_weights[:16]=0;shadow_weights[96:]=0
    scores = np.sum(np.minimum(delta,32)*shadow_weights[None,:],axis=1)
    scores = np.where(safe,scores,-(1<<40))
    # Preserve a safe sub-code gain ramp even when quantisation temporarily
    # makes the pixel score tie identity. Otherwise a 256->257 ramp stalls.
    priority = scores*1024+gs[:,0]
    best = int(np.argmax(priority))
    g,k,s = definitions[best]
    return dict(gain_q8_8=g,knee_out=k,soft_q8_8=s),dict(
        curve_candidates=len(definitions),sampled_peak_constraint=True,
        sampled_predicted_new_clipping_bins=int(np.count_nonzero(unsafe[best])),
        shadow_lift_score=int(scores[best]),identity_fallback=best==0,
        sampled_guard_only=True)


def suggest_v4(stats, noise=None):
    noise = noise or {}
    # A reliable UV estimate must never legitimise an unreliable Y estimate,
    # nor vice versa. Discard untrusted channel values before gain/floor use.
    sigma = noise.get('sigma_q8')
    if sigma is None or noise.get('confidence_q8',0)<128:
        sigma = None
    uv_sigma = noise.get('uv_sigma_q8')
    if uv_sigma is None or noise.get('uv_confidence_q8',0)<128:
        uv_sigma = None
    target,reason = _target_gain(stats,dict(sigma_q8=sigma))
    curve,guard = _select_curve(stats,target)
    known = [value for value in (sigma,uv_sigma) if value is not None]
    enabled = int(bool(known) and max(known)>=2*256)
    def floor(sigma):
        return 0 if sigma is None or sigma<320 else min(32,max(1,(int(sigma)*3+511)//512))
    result = dict(brightness=0,sharp_q8_8=256,filter_enable=enabled,
        noise_floor=floor(sigma),noise_floor_uv=floor(uv_sigma),detail_limit=255,
        dark_thr=48,light_thr=208,**curve)
    return result,dict(policy=AUTO_POLICY,decision=reason,
        requested_gain_q8_8=target,noise_gain_ceiling=noise_gain_cap(sigma),**guard)


def adapt_legacy_parameters(parameters):
    """Explicit syntax-only adapter; never silently discard active UV controls.

    This cannot turn a v3 core into the v4 split algorithm. It only exposes
    representable register dictionaries for controlled compatibility tests.
    """
    p = dict(parameters)
    if 'noise_floor_uv' not in p:
        raise ValueError('v4 split parameter noise_floor_uv is required')
    if p['noise_floor_uv']!=0:
        raise ValueError('legacy parameters cannot express active UV denoising')
    if p.get('filter_enable') and p.get('noise_floor')==0:
        raise ValueError('legacy core cannot express independent Y bypass')
    p.pop('noise_floor_uv')
    return p


class ExposureControllerV4:
    """Integer PTS smoothing, conservative RGB guard, and weak-noise holding."""
    def __init__(self, exposure_tau_ms=1200,noise_tau_ms=700,filter_dwell_ms=400,unknown_hold_ms=1500):
        for value in (exposure_tau_ms,noise_tau_ms,filter_dwell_ms,unknown_hold_ms):
            if isinstance(value,bool) or not isinstance(value,int) or value<0:
                raise ValueError('nonnegative integer controller timing required')
        self.exposure_tau_ms,self.noise_tau_ms,self.filter_dwell_ms = exposure_tau_ms,noise_tau_ms,filter_dwell_ms
        self.unknown_hold_ms = unknown_hold_ms
        self.last_y_valid_ms = self.last_uv_valid_ms = None
        self.last_ms = None
        self.last_stats = None
        self.sigma_q16 = None
        self.uv_sigma_q16 = None
        self.gain_q16 = None
        self.filter = None
        self.pending = self.pending_since = None
        self.last_confidence = 0
        self.last_uv_confidence = 0

    def reset(self):
        self.__init__(self.exposure_tau_ms,self.noise_tau_ms,self.filter_dwell_ms,self.unknown_hold_ms)

    @staticmethod
    def _noise_input(noise):
        noise = dict(noise or {})
        s,c = noise.get('sigma_q8'),noise.get('confidence_q8',0)
        if (isinstance(c,(bool,np.bool_)) or not isinstance(c,(int,np.integer)) or not 0<=c<=256 or
                (s is not None and (isinstance(s,(bool,np.bool_)) or
                 not isinstance(s,(int,np.integer)) or not 0<=s<=255*256))):
            raise ValueError('noise must have bounded integer Q8 sigma/confidence')
        return noise,s,c,s is not None and c>=128

    def update(self, pts_ms, stats, noise=None):
        if isinstance(pts_ms,bool) or not isinstance(pts_ms,int) or pts_ms<0 or (self.last_ms is not None and pts_ms<self.last_ms):
            raise ValueError('monotonic nonnegative integer video milliseconds required')
        measurement,raw_sigma,confidence,valid = self._noise_input(noise)
        _,raw_uv_sigma,uv_confidence,uv_valid = self._noise_input(dict(
            sigma_q8=measurement.get('uv_sigma_q8'),
            confidence_q8=measurement.get('uv_confidence_q8',0)))
        filter_valid = valid or uv_valid
        cut = self.last_stats is None
        distance = 0
        if self.last_stats is not None:
            old = self.last_stats
            a,b = stats['sample_count'],old['sample_count']
            distance = sum(abs(x*b-y*a) for x,y in zip(stats['histogram'],old['histogram']))*128//(a*b)
            q,p = stats['quantiles'],old['quantiles']
            cut = distance>=96 and (abs(q['p50']-p['p50'])>=24 or abs(q['p95']-p['p95'])>=40)
        dt = 0 if self.last_ms is None else pts_ms-self.last_ms
        # Same-scene uncertainty holds history. A detected cut invalidates
        # absent channel measurements: old-scene noise must not filter a new,
        # unmeasured texture. Valid channels restart from the new measurement.
        if cut and not valid:
            self.sigma_q16=None
            self.last_confidence=0
        if cut and not uv_valid:
            self.uv_sigma_q16=None
            self.last_uv_confidence=0
        expired = (not valid and self.sigma_q16 is not None and
            self.last_y_valid_ms is not None and pts_ms-self.last_y_valid_ms>=self.unknown_hold_ms)
        uv_expired = (not uv_valid and self.uv_sigma_q16 is not None and
            self.last_uv_valid_ms is not None and pts_ms-self.last_uv_valid_ms>=self.unknown_hold_ms)
        if expired:
            self.sigma_q16=None
            self.last_confidence=0
        if uv_expired:
            self.uv_sigma_q16=None
            self.last_uv_confidence=0
        held = not valid and self.sigma_q16 is not None
        uv_held = not uv_valid and self.uv_sigma_q16 is not None
        filter_held = not filter_valid and (self.uv_sigma_q16 is not None or self.sigma_q16 is not None)
        if valid:
            self.last_y_valid_ms=pts_ms
            target = int(raw_sigma)*256
            if self.sigma_q16 is None or cut:
                self.sigma_q16 = target
            else:
                tau = 150 if target>self.sigma_q16 else self.noise_tau_ms
                alpha = 256 if tau==0 else min(256,(dt*confidence)//(tau+dt))
                self.sigma_q16 += ((target-self.sigma_q16)*alpha+128)//256
            self.last_confidence = int(confidence)
        if uv_valid:
            self.last_uv_valid_ms=pts_ms
            target = int(raw_uv_sigma)*256
            if self.uv_sigma_q16 is None or cut:
                self.uv_sigma_q16 = target
            else:
                tau = 150 if target>self.uv_sigma_q16 else self.noise_tau_ms
                alpha = 256 if tau==0 else min(256,(dt*uv_confidence)//(tau+dt))
                self.uv_sigma_q16 += ((target-self.uv_sigma_q16)*alpha+128)//256
            self.last_uv_confidence = int(uv_confidence)
        effective = {} if self.sigma_q16 is None else dict(
            sigma_q8=(self.sigma_q16+128)//256,confidence_q8=self.last_confidence)
        if self.uv_sigma_q16 is not None:
            effective.update(uv_sigma_q8=(self.uv_sigma_q16+128)//256,
                uv_confidence_q8=self.last_uv_confidence)
        available = [(effective.get('sigma_q8'),effective.get('confidence_q8',0)),
                     (effective.get('uv_sigma_q8'),effective.get('uv_confidence_q8',0))]
        present = [entry for entry in available if entry[0] is not None]
        if present:
            fs,fc = max(present,key=lambda entry:entry[0])
            effective.update(filter_sigma_q8=fs,filter_confidence_q8=fc)
        suggested,reason = suggest_v4(stats,effective)
        target_gain = suggested['gain_q8_8']*256
        if self.gain_q16 is None or cut:
            self.gain_q16 = target_gain
        else:
            # Tiny target variations are absorbed before exposure ramps. A
            # large protective reduction is immediate; RGB guard is checked
            # again after smoothing, so stale gain cannot bypass protection.
            difference = target_gain-self.gain_q16
            if difference<-(4*256):
                self.gain_q16 = target_gain
            elif difference>4*256:
                alpha = 256 if self.exposure_tau_ms==0 else min(256,(dt*256)//(self.exposure_tau_ms+dt))
                self.gain_q16 += (difference*alpha+128)//256
        applied_gain = (self.gain_q16+128)//256
        curve,guard = _select_curve(stats,applied_gain,fixed_gain=True)
        if curve['gain_q8_8']<applied_gain:
            self.gain_q16 = curve['gain_q8_8']*256
        suggested.update(curve)
        sigma = effective.get('filter_sigma_q8',effective.get('sigma_q8'))
        if self.filter is None or cut or not present:
            self.filter = int(sigma is not None and sigma>=512)
            self.pending=self.pending_since=None
        elif filter_valid:
            desired = int(sigma>320 if self.filter else sigma>=512)
            if desired==self.filter:
                self.pending=self.pending_since=None
            else:
                if desired!=self.pending:
                    self.pending,self.pending_since=desired,pts_ms
                if pts_ms-self.pending_since>=self.filter_dwell_ms:
                    self.filter=desired
                    self.pending=self.pending_since=None
        else:
            self.pending=self.pending_since=None
        suggested['filter_enable']=self.filter
        record = dict(policy=AUTO_POLICY,pts_ms=pts_ms,scene_reset=cut,
            histogram_distance_q8=distance,noise=measurement,effective_noise=effective,
            noise_held=held,uv_noise_held=uv_held,filter_noise_held=filter_held,
            noise_history_expired=bool(expired),uv_noise_history_expired=bool(uv_expired),
            unknown_hold_ms=self.unknown_hold_ms,
            reason=reason,applied_guard=guard,applied=dict(suggested),
            execution='pc-statistics-controller',statistics=stats)
        self.last_ms=pts_ms
        self.last_stats=dict(stats,histogram=list(stats['histogram']),quantiles=dict(stats['quantiles']))
        return suggested,record
