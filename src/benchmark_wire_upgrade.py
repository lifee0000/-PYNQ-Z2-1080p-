"""Compare identical distinct real-video frames in raw/LZ4 physical FPGA modes."""
from pathlib import Path
from dataclasses import asdict
import hashlib,json,sys,time
import av,numpy as np
from PIL import Image,ImageOps
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1]
PROJECT=ROOT.parent if (ROOT.parent/'public_sources').is_dir() else WS/'P4_NET'
sys.path.insert(0,str(ROOT/'native'))
from protocol import Session,Frame,status
from reference import Params,enhance
from pixels import pack_rgb
from identity import load_identity

def sha(data):return hashlib.sha256(data).hexdigest()
def prepare():
    sources={
        'people':PROJECT/'public_sources/FourPeople.webm',
        'camera':PROJECT/'results/ea697d1ba8f9facf781e3a79aa58e50a.mp4',
        'particles':PROJECT/'results/71b470630b1ee765c2d445ac93fc3a3a.mp4'}
    # File names in delivered sources may differ; find by exact original basename.
    for name,p in list(sources.items()):
        if not p.exists():
            matches=list((PROJECT/'results').rglob(p.name))
            if len(matches)!=1:raise FileNotFoundError(p)
            sources[name]=matches[0]
    settings=asdict(Params(mode=5,noise_floor=12,noise_floor_uv=12,knee_out=255,soft_q8_8=256))
    cases=[]
    for name,path in sources.items():
        frames=[]
        with av.open(str(path)) as source:
            for i,f in enumerate(source.decode(video=0)):
                if i%5:continue
                rgb=f.to_ndarray(format='rgb24')
                if rgb.shape[:2]!=(720,1280):
                    fit=ImageOps.contain(Image.fromarray(rgb),(1280,720),Image.Resampling.LANCZOS)
                    canvas=Image.new('RGB',(1280,720));canvas.paste(fit,((1280-fit.width)//2,(720-fit.height)//2));rgb=np.asarray(canvas)
                raw=pack_rgb(rgb)
                frames.append((raw,sha(enhance(raw,1280,720,Params(**settings)))))
                if len(frames)==20:break
        cases.append((name,path,frames,settings))
    return cases

def run(cases):
    identity=load_identity(ROOT);results=[]
    dest=ROOT/'evidence/wire_benchmark.json'
    report=dict(status='RUNNING',evidence_kind='PHYSICAL_FPGA',identity=identity,rows=results,
        scope='720p distinct video frames, fixed same parameters; includes transport/checksum/FPGA, excludes decode and encode. Raw and LZ4 use identical inputs.',
        hardware_pixel_formula_changed=False)
    for rep in range(3):
        for name,path,frames,settings in cases:
            for window in (1,3):
                for codec in (('raw','lz4') if rep%2==0 else ('lz4','raw')):
                    limit=time.monotonic()+5
                    while status()['state']!='IDLE':
                        if time.monotonic()>limit:raise TimeoutError('owner not idle')
                        time.sleep(.01)
                    before=status();begin=time.perf_counter();observed=[]
                    with Session(width=1280,height=720,expected_identity=identity,max_inflight=window,wire_codec=codec) as s:
                        def stream():
                            for i,(raw,_) in enumerate(frames):yield Frame(i,i,raw,settings)
                        for output in s.exchange(stream()):
                            digest=sha(output.payload)
                            assert digest==frames[output.frame_id][1] and output.completed_frames==1 and not output.stream_errors
                            observed.append(dict(id=output.frame_id,sha256=digest,dma_ns=output.dma_ns))
                        metrics=s.transport_metrics;after=s.summary
                    elapsed=time.perf_counter()-begin
                    row=dict(name=name,source=str(path),rep=rep,window=window,codec=codec,frames=len(observed),
                        seconds=elapsed,fps=len(observed)/elapsed,exact=True,transport=metrics,raw_frames=observed,
                        before=before,after=after)
                    results.append(row);dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
                    print(json.dumps({k:row[k] for k in ('name','rep','window','codec','frames','fps')}),flush=True)
    report['status']='PASS';dest.write_text(json.dumps(report,indent=2),encoding='utf-8')
    return report

if __name__=='__main__':
    from board_link import ManagedBoard
    cases=prepare();b=ManagedBoard();result={}
    try:
        result['start']=b.start();run(cases);result['status']='PASS'
    finally:
        result['cleanup']=b.stop()
        (ROOT/'evidence/benchmark_lifecycle.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
