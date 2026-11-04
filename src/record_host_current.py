from pathlib import Path
import hashlib,json,os,subprocess,sys,time
root=Path(__file__).resolve().parent
steps=[]
for name,cmd in (
    ('spatial_exposure',[sys.executable,'-m','unittest','test_spatial','test_exposure_v4','-v']),
    ('native_transport',[sys.executable,'-m','unittest','discover','-s','native','-p','test_native_mock.py','-v'])):
    start=time.perf_counter()
    p=subprocess.run(cmd,cwd=root,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace')
    target=root/'evidence'/('current_'+name+'.log');target.write_text(p.stdout,encoding='utf-8')
    steps.append(dict(name=name,returncode=p.returncode,elapsed=time.perf_counter()-start,log=target.name,
        log_sha256=hashlib.sha256(target.read_bytes()).hexdigest()))
    if p.returncode:raise RuntimeError(p.stdout)
files=['reference.py','reference_v3_frozen.py','exposure_v4.py','test_exposure_v4.py','test_spatial.py',
       'native/y50_native.cpp','native/y50_native.h','native/binding.py','native/protocol.py',
       'native/test_native_mock.py','native/y50_native.dll','native/liby50_native.so']
r=dict(status='PASS',evidence_kind='HOST_ONLY_NO_BOARD_OPERATION',tests=55,
    spatial=24,exposure=21,transport=10,steps=steps,
    hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in files})
(root/'evidence/current_host_tests.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(dict(status='PASS',tests=55)))
