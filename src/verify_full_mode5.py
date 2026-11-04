"""Independent native full720p mode5 proof; never modifies the running HLS TB."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import time
import numpy as np
import reference

ROOT=Path(__file__).resolve().parent


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    out=ROOT/"evidence";out.mkdir(exist_ok=True)
    h,w=720,1280;yy,xx=np.indices((h,w));rng=np.random.default_rng(20261023)
    clean_y=(35+xx*70//(w-1)+yy*20//(h-1)+45*((xx-860)**2+(yy-360)**2<140**2)).astype(np.int32)
    clean_y[(xx%91==0)&(yy>30)&(yy<h-30)]+=35
    y=np.clip(clean_y+rng.normal(0,3,(h,w)).round().astype(np.int32),0,255).astype(np.uint8)
    chroma=np.empty((h,w),np.uint8)
    chroma[:,0::2]=np.where(xx[:,0::2]<640,105,172)
    chroma[:,1::2]=np.where(xx[:,1::2]<640,162,94)
    chroma=np.clip(chroma.astype(np.int32)+rng.normal(0,5,(h,w)).round().astype(np.int32),0,255).astype(np.uint8)
    params=reference.Params(mode=5,noise_floor=6,noise_floor_uv=10,gain_q8_8=320,brightness=5,
        knee_out=224,soft_q8_8=128,sharp_q8_8=256,detail_limit=32)
    raw=reference.pack(y,chroma);golden=reference.enhance(raw,w,h,params)
    (out/"full_mode5_input.bin").write_bytes(raw);(out/"full_mode5_golden.bin").write_bytes(golden)
    fields=dict(width=w,height=h,**asdict(params));ordered=[fields[name] for name in reference.PARAMETER_ORDER]
    (out/"full_mode5_config.h").write_text("static const int full_mode5_params[]={"+
        ",".join(map(str,ordered))+"};\n",encoding="ascii")
    commands=[]
    def run(name,argv):
        start=time.perf_counter()
        result=subprocess.run([str(a) for a in argv],cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
            encoding="utf-8",errors="replace",timeout=180)
        log=out/f"{name}.log";log.write_text(result.stdout,encoding="utf-8")
        commands.append(dict(argv=[str(a) for a in argv],returncode=result.returncode,
            elapsed_s=time.perf_counter()-start,log=str(log.relative_to(ROOT))))
        if result.returncode:raise RuntimeError(f"{name} failed: {log}")
        return result.stdout
    compiler=shutil.which("g++") or "C:/msys64/mingw64/bin/g++.exe"
    run("full_mode5_compile",[compiler,"-std=c++17","-O1","-Wno-unknown-pragmas","-I",
        "D:/FPGA/2026.1/Vitis/include","-I","evidence","hls/spatial_v4.cpp","hls/testbench_full_mode5.cpp",
        "-o","evidence/native_full_mode5.exe"])
    stdout=run("full_mode5_native",[out/"native_full_mode5.exe","evidence/full_mode5_input.bin",
        "evidence/full_mode5_golden.bin","evidence/full_mode5_actual.bin"])
    if "SPLIT_V4_FULL_720P_MODE5_EXACT_PASS" not in stdout:raise ValueError("Missing completion")
    actual=(out/"full_mode5_actual.bin").read_bytes()
    if actual!=golden:raise ValueError("Actual output binary differs from golden")
    before=np.frombuffer(raw,np.uint8).reshape(h,w,2);after=np.frombuffer(actual,np.uint8).reshape(h,w,2)
    report=dict(schema=1,status="PASS",evidence_kind="NATIVE_CPP_WITH_VENDOR_TYPES_NOT_RTL_OR_BOARD",
        top=reference.TOP,pixel_format=reference.PIXEL_FORMAT,width=w,height=h,mode=5,seed=20261023,
        params=asdict(params),pixels=w*h,exact_bytes=len(actual),max_error=0,
        changed_y_pixels=int(np.count_nonzero(before[:,:,0]!=after[:,:,0])),
        changed_chroma_bytes=int(np.count_nonzero(before[:,:,1]!=after[:,:,1])),
        no_running_hls_inputs_modified=True,no_board_operations=True,claim_50fps=False,
        note="Native x86 C++ time is not FPGA throughput. This full-mode5 frame was not added to current RTL cosim.",
        commands=commands,sha256={str(p.relative_to(ROOT)):sha(p) for p in
            (ROOT/"reference.py",ROOT/"hls/spatial_v4.cpp",ROOT/"hls/spatial_v4.h",
             ROOT/"hls/testbench_full_mode5.cpp",ROOT/"verify_full_mode5.py",
             out/"full_mode5_config.h",out/"full_mode5_input.bin",out/"full_mode5_golden.bin",out/"full_mode5_actual.bin")})
    (out/"full_mode5_verification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))


if __name__=="__main__":main()
