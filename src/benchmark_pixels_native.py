"""Compare native format conversion with the delivered NumPy implementation.

No board or image enhancement is involved. Every timed result is hashed after
timing against the independent frozen equations; variants alternate order.
"""
from pathlib import Path
import argparse,hashlib,json,platform,statistics,time
import numpy as np
from benchmark_pc import _fixtures,frozen_pack_rgb,frozen_unpack_rgb
from pixels import pack_rgb,unpack_rgb,pack_rgb_numpy,unpack_rgb_numpy,FORMAT_BACKEND

def benchmark(repeats=20):
    if not 1 <= repeats <= 100:raise ValueError('repeats 1..100 required')
    if FORMAT_BACKEND!='NATIVE_Q16_FORMAT_ONLY':raise RuntimeError('Build native pixels first')
    cases=_fixtures(1280,720,3,20261023)
    payloads=[frozen_pack_rgb(a) for _,a in cases]
    report=dict(status='PASS',evidence_kind='PC_FORMAT_CONVERSION_ONLY',
        backend=FORMAT_BACKEND,board_contacted=False,claim_50fps=False,
        geometry=[1280,720],repeats=repeats,platform=platform.platform(),
        stages={},exact_byte_parity=True,hashes_outside_timed_region=True)
    for stage,funcs,oracle,args in (
        ('pack',(pack_rgb_numpy,pack_rgb),frozen_pack_rgb,[(a,) for _,a in cases]),
        ('unpack',(unpack_rgb_numpy,unpack_rgb),frozen_unpack_rgb,[(b,1280,720) for b in payloads])):
        golden=[hashlib.sha256(oracle(*a)).hexdigest() for a in args]
        samples=[[],[]]
        for _ in range(3):
            for f in funcs:
                for a in args:f(*a)
        for iteration in range(repeats):
            for i in ((0,1) if iteration%2==0 else (1,0)):
                for a,digest in zip(args,golden):
                    start=time.perf_counter();value=funcs[i](*a);elapsed=time.perf_counter()-start
                    if hashlib.sha256(value).hexdigest()!=digest:raise AssertionError(stage+' parity')
                    samples[i].append(elapsed*1000)
        data=[dict(median_ms=statistics.median(x),p95_ms=float(np.percentile(x,95)),
                   samples=len(x)) for x in samples]
        report['stages'][stage]=dict(numpy=data[0],native=data[1],
            speedup=data[0]['median_ms']/data[1]['median_ms'],golden_sha256=golden)
    root=Path(__file__).resolve().parent
    report['source_sha256']={name:hashlib.sha256((root/name).read_bytes()).hexdigest()
        for name in ('pixels.py','native_pixels_bridge.py','native_pixels/pixels_native.cpp',
                     'native_pixels/p4_pixels.dll','benchmark_pixels_native.py')}
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--json',type=Path,required=True)
    p.add_argument('--repeats',type=int,default=20);a=p.parse_args();r=benchmark(a.repeats)
    a.json.parent.mkdir(parents=True,exist_ok=True)
    a.json.write_text(json.dumps(r,indent=2),encoding='utf-8')
    print(json.dumps(r),flush=True)
