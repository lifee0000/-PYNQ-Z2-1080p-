"""Inert native checksum equivalence/throughput check on ARM; no hardware MMIO."""
from pathlib import Path
import base64,hashlib,json,sys
ROOT=Path(__file__).resolve().parent
from board_control import execute
data=(ROOT/'native/liby50_native.so').read_bytes()
code='''from pathlib import Path
import base64,ctypes as C,hashlib,json,random,tempfile,time,shutil
root=Path(tempfile.mkdtemp(prefix='p4_hash_check_')).resolve()
assert root.parent==Path(tempfile.gettempdir()).resolve()
try:
    data=base64.b64decode(PAYLOAD);assert hashlib.sha256(data).hexdigest()==DIGEST
    target=root/'codec.so';target.write_bytes(data);lib=C.CDLL(str(target))
    lib.XXH32.argtypes=[C.c_void_p,C.c_size_t,C.c_uint32];lib.XXH32.restype=C.c_uint32
    lib.p4_xxh32.argtypes=[C.c_void_p,C.c_int];lib.p4_xxh32.restype=C.c_uint32
    lib.p4_hash_neon.argtypes=[];lib.p4_hash_neon.restype=C.c_int
    rng=random.Random(20261024);raw=rng.randbytes(1843232);sample=C.create_string_buffer(raw)
    checked=0
    for offset in range(16):
        for length in list(range(1,130))+[255,256,257,4095,4096,4097,65535,1843200]:
            ptr=C.byref(sample,offset)
            assert lib.XXH32(ptr,length,0)==lib.p4_xxh32(ptr,length),(offset,length)
            checked+=1
    times={}
    for name in ('XXH32','p4_xxh32'):
        begin=time.perf_counter()
        for _ in range(40):
            if name=='XXH32':value=lib.XXH32(sample,1843200,0)
            else:value=lib.p4_xxh32(sample,1843200)
        times[name]=(time.perf_counter()-begin)/40*1000
    result=dict(status='PASS',evidence_kind='PHYSICAL_ARM_ONLY_NO_MMIO',checks=checked,
        bitexact_to_unmodified_upstream=True,neon_enabled=bool(lib.p4_hash_neon()),
        timing_ms_720p=times,library_sha256=DIGEST)
finally:
    assert root.parent==Path(tempfile.gettempdir()).resolve() and root.name.startswith('p4_hash_check_')
    shutil.rmtree(root)
result['owned_temporary_files_removed']=not root.exists()
print('__REVIEW_RESULT__='+json.dumps(result),flush=True)
'''.replace('PAYLOAD',repr(base64.b64encode(data).decode())).replace('DIGEST',repr(hashlib.sha256(data).hexdigest()))
r=execute(code,60)
(ROOT/'evidence/arm_hash.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(r))
