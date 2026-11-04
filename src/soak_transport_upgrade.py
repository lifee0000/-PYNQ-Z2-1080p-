"""Five-minute bounded physical regression, alternating raw/compressible scenes."""
from pathlib import Path
from dataclasses import asdict
import hashlib,json,sys,time
import numpy as np
ROOT=Path(__file__).resolve().parent;out=ROOT/'evidence/soak_300s'
out.mkdir(parents=True,exist_ok=True)
sys.path.insert(0,str(ROOT/'native'))
from board_link import ManagedBoard
from protocol import Session,Frame,status
from reference import Params,enhance
from identity import load_identity
target=out/'soak.json';trace=out/'frames.jsonl'
assert not target.exists() and not trace.exists()
p=Params(mode=5,noise_floor=12,noise_floor_uv=12,knee_out=255,soft_q8_8=256,
    roi_enable=1,roi_x=8,roi_y=8,roi_width=1264,roi_height=704)
rng=np.random.default_rng(20261024);fixtures=[]
for i in range(5):
    raw=np.empty((720,1280,2),np.uint8)
    raw[:,:,0]=np.clip(64+i*24+rng.normal(0,7,(720,1280)),0,255)
    raw[:,:,1]=np.clip(128+rng.normal(0,8,(720,1280)),0,255)
    if i==1:
        raw[:150,:,:]=[16,128];raw[570:,:,:]=[16,128];raw[:,:320,:]=[16,128];raw[:,960:,:]=[16,128]
    if i==2:raw[:,:,:]=[90,128]
    if i==4:raw[:,::2,:]=[50,120];raw[:,1::2,:]=[180,136]
    data=raw.tobytes();fixtures.append((data,enhance(data,1280,720,p)))
record=dict(status='RUNNING',evidence_kind='PHYSICAL_FPGA_MIXED_CODEC_STABILITY',target_seconds=300,
    identity=load_identity(ROOT),frames=0,scope='Full distinct 720p frames with unique border tags. Network+FPGA, no video codecs.',
    checkpoints=[])
b=ManagedBoard();expected={};seen=set();begin=None
try:
    record['startup']=b.start();begin=time.perf_counter();deadline=begin+300
    def stream():
        i=0
        while time.perf_counter()<deadline:
            data,golden=fixtures[i%5];tag=i.to_bytes(8,'little')
            expected[i]=hashlib.sha256(tag+golden[8:]).hexdigest()
            yield Frame(i,i,tag+data[8:],asdict(p));i+=1
    with trace.open('x',encoding='utf-8') as log,Session(width=1280,height=720,expected_identity=record['identity'],max_inflight=3,timeout=15) as s:
        for item in s.exchange(stream()):
            digest=hashlib.sha256(item.payload).hexdigest()
            assert digest==expected.pop(item.frame_id) and digest not in seen
            assert item.frame_id==record['frames'] and item.pts==item.frame_id
            assert item.completed_frames==1 and not item.stream_errors
            assert item.payload[:8]==item.frame_id.to_bytes(8,'little')
            seen.add(digest);record['frames']+=1
            log.write(json.dumps(dict(id=item.frame_id,sha256=digest,dma_ns=item.dma_ns))+'\n')
            if record['frames']%300==0:
                elapsed=time.perf_counter()-begin
                record['checkpoints'].append(dict(frames=record['frames'],seconds=elapsed,fps=record['frames']/elapsed))
                target.write_text(json.dumps(record,indent=2),encoding='utf-8');log.flush()
                print(json.dumps(record['checkpoints'][-1]),flush=True)
        record['transport']=s.transport_metrics;record['summary']=s.summary
    elapsed=time.perf_counter()-begin
    assert elapsed>=300 and not expected
    record.update(status='PASS',seconds=elapsed,unique_hashes=len(seen),fps=len(seen)/elapsed)
except BaseException as exc:
    record.update(status='FAIL',error=str(exc));raise
finally:
    record['cleanup']=b.stop()
    if record['cleanup']['status']!='STOPPED_DMA_HALTED_CORE_RESET':record['status']='FAIL'
    target.write_text(json.dumps(record,indent=2),encoding='utf-8')
    print(json.dumps({k:record.get(k) for k in ('status','frames','seconds','fps','cleanup')}),flush=True)
