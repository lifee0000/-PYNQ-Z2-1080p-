"""Rebuilt EXE + real FPGA + independent full-frame audit of five full clips."""
from pathlib import Path
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1]
PROJECT=ROOT.parent if (ROOT.parent/'public_sources').is_dir() else WS/'P4_NET'
folder=ROOT/'results';folder.mkdir(exist_ok=True)
exe=ROOT/'Windows_App/PYNQVideoV4/PYNQVideoV4.exe'
cases=[('camera',PROJECT/'results/ea697d1ba8f9facf781e3a79aa58e50a.mp4',204,
        PROJECT/'results/camera_FPGA.mp4.frames.jsonl'),
       ('particles',PROJECT/'results/71b470630b1ee765c2d445ac93fc3a3a.mp4',1008,
        PROJECT/'results/particles_FPGA.mp4.frames.jsonl')]
for name in ('FourPeople','Johnny','KristenAndSara'):
    cases.append((name,PROJECT/'public_sources'/(name+'.webm'),601,
        PROJECT/'results/public_validation'/(name+'_FPGA.mp4.frames.jsonl')))
record=dict(status='RUNNING',evidence_kind='NEW_EXE_PHYSICAL_FPGA_FULL_VIDEOS',cases=[],
    exe_sha256=hashlib.sha256(exe.read_bytes()).hexdigest())
path=ROOT/'evidence/full_videos.json'
try:
    selftest=ROOT/'evidence/exe_selftest_current.json'
    subprocess.run([str(exe),'--self-test',str(selftest)],check=True,timeout=60)
    assert json.loads(selftest.read_text())['status']=='PASS'
    for name,source,count,prior in cases:
        target=folder/(name+'_FPGA.mp4');assert not target.exists()
        start=time.perf_counter()
        subprocess.run([str(exe),'--input',str(source),'--output',str(target),'--managed',
            '--pipeline','--wire-codec','lz4','--mode','5'],check=True,timeout=600)
        report=json.loads(Path(str(target)+'.json').read_text(encoding='utf-8'))
        assert report['status']=='PASS' and report['frames']==count and report['backend']=='FPGA_MMIO'
        assert report['board_cleanup']['status']=='STOPPED_DMA_HALTED_CORE_RESET'
        assert not report['board_cleanup']['pending_owned_jupyter_kernels']
        managed_wall=time.perf_counter()-start;audit_begin=time.perf_counter()
        with (ROOT/'evidence'/(name+'_audit.log')).open('w',encoding='utf-8') as log:
            subprocess.run([sys.executable,'-X','utf8',str(ROOT/'verify_video.py'),'--output',str(target)],
                cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,check=True,timeout=600)
        audit=json.loads(target.with_name(target.stem+'_验收.json').read_text(encoding='utf-8'))
        assert audit['status']=='PASS' and audit['raw_reference_exact_all_frames']
        old=[json.loads(s) for s in prior.read_text(encoding='utf-8').splitlines()]
        new=[json.loads(s) for s in Path(str(target)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        assert len(old)==len(new)==count
        keys=('frame_id','pts','time_base','parameters','input_sha256','output_sha256')
        assert all(all(a[k]==b[k] for k in keys) for a,b in zip(old,new)),'Transport upgrade changed pixels or PTS'
        row=dict(name=name,frames=count,processing_fps=report['processing_fps'],
            elapsed_seconds=report['elapsed_seconds'],whole_managed_seconds=managed_wall,
            independent_audit_seconds=time.perf_counter()-audit_begin,
            exact_all_fpga_frames=True,exact_to_previous_release_all_frames=True,
            transport=report['transport_metrics'],video=str(target),comparison=audit['comparison'],
            cleanup=report['board_cleanup'])
        record['cases'].append(row);path.write_text(json.dumps(record,indent=2),encoding='utf-8')
        print(json.dumps({k:row[k] for k in ('name','frames','processing_fps','exact_to_previous_release_all_frames')}),flush=True)
    record['status']='PASS'
except BaseException as exc:
    record.update(status='FAIL',error=str(exc));raise
finally:
    path.write_text(json.dumps(record,indent=2),encoding='utf-8')
