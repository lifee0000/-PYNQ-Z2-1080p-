"""Known clean synthetic YUYV fixtures; fixed rules and seed for every run.

No user material is opened. These fixtures isolate algorithm mechanisms and
cannot establish real camera quality, actual FPGA output or file frame rate.
"""
import numpy as np

SEED=20261023

def yuyv(y,u=None,v=None):
    y=np.asarray(y,dtype=np.uint8);h,w=y.shape
    if w%2:raise ValueError('even width required')
    u=np.full((h,w//2),128,np.uint8) if u is None else np.asarray(u,dtype=np.uint8)
    v=np.full((h,w//2),128,np.uint8) if v is None else np.asarray(v,dtype=np.uint8)
    if u.shape!=(h,w//2) or v.shape!=u.shape:raise ValueError('pair chroma shape')
    data=np.empty((h,w,2),np.uint8);data[:,:,0]=y
    data[:,0::2,1]=u;data[:,1::2,1]=v
    return data

def noisy(clean,rng,sy=0,sc=0,impulse=0):
    result=clean.astype(np.int32).copy()
    if sy:result[:,:,0]+=rng.normal(0,sy,result.shape[:2]).round().astype(np.int32)
    if sc:result[:,:,1]+=rng.normal(0,sc,result.shape[:2]).round().astype(np.int32)
    result=np.clip(result,0,255).astype(np.uint8)
    if impulse:
        mask=rng.random(result.shape[:2])<impulse
        result[:,:,0][mask]=rng.choice((0,255),size=mask.sum()).astype(np.uint8)
    return result

def fixtures(h=192,w=320):
    rng=np.random.default_rng(SEED)
    flat=yuyv(np.full((h,w),96,np.uint8))
    clean_edge=flat.copy();clean_edge[:,w//2:,0]=210
    chroma=flat.copy();chroma[:,:w//2,1][:,0::2]=78;chroma[:,w//2:,1][:,0::2]=180
    chroma[:,:w//2,1][:,1::2]=175;chroma[:,w//2:,1][:,1::2]=82
    lines=yuyv(np.full((h,w),32,np.uint8))
    for i in range(20,w-10,23):lines[:,i,0]=235
    checker=yuyv((((np.indices((h,w)).sum(axis=0)&1)*180)+32).astype(np.uint8))
    gradient=yuyv(np.broadcast_to(np.linspace(32,196,w).round().astype(np.uint8),(h,w)).copy())
    return [
        ('luma_gaussian',flat,noisy(flat,rng,sy=8),'noisy'),
        ('chroma_gaussian',flat,noisy(flat,rng,sc=9),'noisy'),
        ('mixed_noise_gradient',gradient,noisy(gradient,rng,sy=6,sc=6),'noisy'),
        ('edge_with_noise',clean_edge,noisy(clean_edge,rng,sy=8,sc=6),'noisy'),
        ('sparse_luma_impulse',flat,noisy(flat,rng,impulse=.004),'impulse'),
        ('clean_thin_lines',lines,lines.copy(),'clean'),
        ('clean_chroma_step',chroma,chroma.copy(),'clean'),
        ('clean_checker',checker,checker.copy(),'clean')]

def rgb(frame):
    """Declared full-range BT.709 nearest-pair preview; no adaptive display."""
    y=frame[:,:,0].astype(np.int32)
    u=np.repeat(frame[:,0::2,1].astype(np.int32)-128,2,axis=1)
    v=np.repeat(frame[:,1::2,1].astype(np.int32)-128,2,axis=1)
    r=y+((103206*v+32768)>>16)
    g=y-((12276*u+30679*v+32768)>>16)
    b=y+((121609*u+32768)>>16)
    return np.clip(np.stack((r,g,b),-1),0,255).astype(np.uint8)

def psnr(a,b):
    error=float(np.mean((np.asarray(a).astype(float)-np.asarray(b).astype(float))**2))
    return 100.0 if error==0 else float(10*np.log10(255**2/error))
