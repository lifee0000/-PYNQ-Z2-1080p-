"""Offline audit of physical frame hashes, PTS/audio, and synced comparison.

CPU HLS reference is used to CHECK FPGA-return hashes. It never supplies pixels
to the processed MP4. The comparison displays the actual encoded FPGA MP4.
"""
from pathlib import Path
from fractions import Fraction
from itertools import zip_longest
from collections import Counter
import argparse,hashlib,json,time
import av
import numpy as np
from PIL import Image,ImageOps,ImageDraw
from pixels import pack_rgb
from reference import Params,enhance
from identity import load_identity
from exposure_v4 import ExposureControllerV4,analyze_yuyv_v4
from run_video import sha_file

ROOT=Path(__file__).resolve().parent
def sha(data):return hashlib.sha256(data).hexdigest()

def audio_identity(path,normalize=False):
    with av.open(str(path)) as c:
        origin=Fraction(c.streams.video[0].start_time or 0)*c.streams.video[0].time_base if normalize else 0
        if not c.streams.audio:return None
        a=c.streams.audio[0];payload=hashlib.sha256();timing=hashlib.sha256();count=0
        for packet in c.demux(a):
            if not packet.size or packet.dts is None:continue
            data=bytes(packet);payload.update(data)
            record=dict(pts=str(Fraction(packet.pts)*packet.time_base-origin) if packet.pts is not None else None,
                dts=str(Fraction(packet.dts)*packet.time_base-origin),duration=str(Fraction(packet.duration)*packet.time_base),bytes=len(data))
            timing.update(json.dumps(record,sort_keys=True).encode());count+=1
        return dict(codec=a.codec_context.name,sample_rate=a.codec_context.sample_rate,
            channels=a.codec_context.channels,packets=count,payload_sha256=payload.hexdigest(),timing_sha256=timing.hexdigest())

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--no-comparison',action='store_true');args=parser.parse_args()
    output=args.output.resolve();report=json.loads(Path(str(output)+'.json').read_text(encoding='utf-8'))
    source=Path(report['input'])
    if not source.is_file():
        candidates=[output.parent/source.name]
        for parent in list(output.parents)[:3]:
            candidates.extend((parent/source.name,parent/'public_sources'/source.name,parent/'results'/source.name))
        candidates.append(output.parent/'input_original.mp4')
        source=next((p for p in candidates if p.is_file()),candidates[-1])
    trace=Path(str(output)+'.frames.jsonl')
    if not trace.is_file():trace=Path(report['frame_trace'])
    assert report['status']=='PASS' and report['backend']=='FPGA_MMIO'
    assert report['identity']==load_identity(ROOT)
    assert sha_file(source)==report['input_sha256'] and sha_file(output)==report['output_sha256']
    rows=[json.loads(line) for line in trace.read_text(encoding='utf-8').splitlines()]
    begin=time.perf_counter();unchanged=0;filters=Counter();gains=Counter();floors=Counter();raw_samples=0
    stamps=[];actual_stamps=[];total=0
    controller=ExposureControllerV4()
    if not args.no_comparison:
        comparison=output.with_name(output.stem+'_前后对照.mp4')
        if comparison.exists():raise FileExistsError(comparison)
        co=av.open(str(comparison),'w',options={'movflags':'+faststart'})
    else:co=None
    try:
        with av.open(str(source)) as src,av.open(str(output)) as processed:
            vs=src.streams.video[0];origin=Fraction(vs.start_time or 0)*vs.time_base
            if co:
                enc=co.add_stream('libx264',rate=vs.average_rate or vs.guessed_rate)
                enc.width,enc.height=1920,572;enc.pix_fmt='yuv420p'
                enc.time_base=vs.time_base;enc.codec_context.time_base=vs.time_base
                enc.options={'crf':'18','preset':'veryfast','bf':'0'}
            for index,pair in enumerate(zip_longest(src.decode(video=0),processed.decode(video=0))):
                original,actual=pair
                assert original is not None and actual is not None,'Missing or extra output frame'
                row=rows[index];assert row['frame_id']==index
                stamp=Fraction(original.pts)*original.time_base-origin
                actual_stamp=Fraction(actual.pts)*actual.time_base
                assert stamp==actual_stamp==int(row['pts'])*Fraction(row['time_base'])
                stamps.append(str(stamp));actual_stamps.append(str(actual_stamp))
                rgb=original.to_ndarray(format='rgb24');roi=None
                if rgb.shape[:2]!=(720,1280):
                    im=ImageOps.contain(Image.fromarray(rgb),(1280,720),Image.Resampling.LANCZOS)
                    x,y=(1280-im.width)//2,(720-im.height)//2
                    roi=(x,y,im.width,im.height);canvas=Image.new('RGB',(1280,720));canvas.paste(im,(x,y));rgb=np.asarray(canvas)
                raw=pack_rgb(rgb);assert sha(raw)==row['input_sha256']
                p=Params(**row['parameters']);p.validate(1280,720)
                if report['auto_params']:
                    stats,noise=analyze_yuyv_v4(raw,1280,720,roi)
                    values,decision=controller.update(round(stamp*1000),stats,noise)
                    for k,v in values.items():assert row['parameters'][k]==v,(index,k)
                    assert row['auto_decision']==decision,'Recorded policy differs from replay'
                expected=enhance(raw,1280,720,p)
                assert sha(expected)==row['output_sha256'],'FPGA result/reference mismatch at frame '+str(index)
                assert row['hardware_counters']==dict(frame_count=1,stream_errors=0)
                unchanged+=int(raw==expected);filters[p.filter_enable]+=1;gains[p.gain_q8_8]+=1
                floors[(p.noise_floor,p.noise_floor_uv)]+=1
                if index in report['selected_frames']:
                    sample=output.parent/(output.stem+'_frames')/f'{index:04}_fpga.yuyv'
                    assert sample.read_bytes()==expected;raw_samples+=1
                if co:
                    panel=Image.new('RGB',(1920,572))
                    panel.paste(Image.fromarray(rgb).resize((960,540)),(0,32))
                    panel.paste(Image.fromarray(actual.to_ndarray(format='rgb24')).resize((960,540)),(960,32))
                    d=ImageDraw.Draw(panel);d.text((12,9),'SOURCE | FRAME '+str(index),fill='white');d.text((972,9),'V4 ACTUAL FPGA | SAME PTS',fill='white')
                    vf=av.VideoFrame.from_ndarray(np.asarray(panel),format='rgb24');vf.pts=row['pts'];vf.time_base=Fraction(row['time_base'])
                    for packet in enc.encode(vf):co.mux(packet)
                total+=1
                if index%100==0:print(json.dumps(dict(verified=total,elapsed=time.perf_counter()-begin)),flush=True)
            if co:
                for packet in enc.encode(None):co.mux(packet)
        assert total==len(rows)==report['frames']
    finally:
        if co:co.close()
    source_audio=audio_identity(source,True);output_audio=audio_identity(output)
    assert source_audio==output_audio,'Audio packet/timestamp mismatch'
    result=dict(schema=1,status='PASS',evidence_kind='OFFLINE_VERIFICATION_OF_PHYSICAL_FPGA_TRACES',
        video=str(output),frames=total,raw_reference_exact_all_frames=True,automatic_policy_replay_exact=True,
        actual_lossless_raw_samples_verified=raw_samples,raw_yuyv_unchanged_frames=unchanged,
        filter_enable_counts=dict(filters),gain_q8_8_counts=dict(gains),
        noise_floor_y_uv_counts={str(k):v for k,v in floors.items()},
        pts_exact=True,audio_passthrough_exact=True,audio=output_audio,
        processed_video_sha256=sha_file(output),comparison=str(comparison) if co else None,
        comparison_note='Viewing copy is lossy H264; numerical claims use actual returned YUYV hashes.',
        elapsed_seconds=time.perf_counter()-begin)
    output.with_name(output.stem+'_验收.json').write_text(json.dumps(result,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=True),flush=True)

if __name__=='__main__':main()
