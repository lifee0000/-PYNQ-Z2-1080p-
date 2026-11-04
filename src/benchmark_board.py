"""Count distinct complete physical 720p payloads; report elapsed wire+DMA time."""
from pathlib import Path
from dataclasses import asdict
import argparse,hashlib,json,sys,time,socket
import numpy as np
ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'native'))
from protocol import Session,Frame,status
from identity import load_identity
from reference import Params,enhance

def main():
    a=argparse.ArgumentParser();a.add_argument('--frames',type=int,default=100)
    a.add_argument('--out',type=Path,required=True);a.add_argument('--inflight',type=int,default=3)
    a.add_argument('--mode',type=int,choices=(0,5),default=5)
    a.add_argument('--nodelay',action='store_true');args=a.parse_args()
    identity=load_identity(ROOT);rng=np.random.default_rng(20261023)
    raw=np.empty((720,1280,2),np.uint8)
    raw[:,:,0]=np.clip(96+rng.normal(0,6,(720,1280)),0,255)
    raw[:,:,1]=np.clip(128+rng.normal(0,7,(720,1280)),0,255)
    # Both denoisers operate on a 1264x704 ROI. Unique 64-bit frame tags live
    # outside it; their unchanged return independently detects stale frames.
    p=Params(mode=args.mode,noise_floor=10,noise_floor_uv=10,knee_out=255,soft_q8_8=256,
        roi_enable=1,roi_x=8,roi_y=8,roi_width=1264,roi_height=704)
    payload=raw.tobytes();golden=enhance(payload,1280,720,p)
    before=status();expected={};rows=[]
    def frames():
        for i in range(args.frames):
            tag=i.to_bytes(8,'little')
            inp=tag+payload[8:];out=tag+golden[8:]
            expected[i]=hashlib.sha256(out).hexdigest()
            yield Frame(i,i,inp,asdict(p),1,50)
    start=time.perf_counter()
    report=dict(schema=1,status='RUNNING',evidence_kind='PHYSICAL_720P_YUYV_WIRE_AND_DMA_BENCHMARK',
        mode=args.mode,roi=[8,8,1264,704],frames_requested=args.frames,max_inflight=args.inflight,
        identity=identity,before=before,frames=rows,client_tcp_nodelay=args.nodelay)
    try:
        with Session(width=1280,height=720,expected_identity=identity,max_inflight=args.inflight) as session:
            if args.nodelay:session.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            for out in session.exchange(frames()):
                actual=hashlib.sha256(out.payload).hexdigest()
                if actual!=expected.pop(out.frame_id) or out.completed_frames!=1 or out.stream_errors:
                    raise RuntimeError('Distinct frame/reference/counter mismatch')
                rows.append(dict(frame_id=out.frame_id,pts=out.pts,output_sha256=actual,dma_ns=out.dma_ns))
        elapsed=time.perf_counter()-start
        report.update(status='PASS',elapsed_seconds=elapsed,frames_completed=len(rows),
            measured_fps=len(rows)/elapsed,mean_dma_ms=float(np.mean([r['dma_ns'] for r in rows]))/1e6,
            payload_bytes_each_direction=args.frames*1843200,
            mbps_each_direction=args.frames*1843200*8/elapsed/1e6,
            unique_output_sha256=len(set(r['output_sha256'] for r in rows)),
            measurement_scope='Includes connection, PC per-frame hash, network and FPGA. Excludes decoder/encoder and precomputed golden.',
            raw_golden_exact=True,claim_complete_video_50fps=False,after=status())
    except BaseException as exc:report.update(status='FAIL',error=str(exc));raise
    finally:args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ('status','frames_completed','measured_fps','mean_dma_ms','mbps_each_direction')}),flush=True)

if __name__=='__main__':main()
