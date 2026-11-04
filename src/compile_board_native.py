"""Compile this project's ARM data plane in an owned temp dir; no MMIO."""
from pathlib import Path
import base64,hashlib,io,json,sys,zipfile
ROOT=Path(__file__).resolve().parent
from board_control import execute
files=['native/'+n for n in ('y50_native.cpp','y50_native.h','build_native.py','codec_exports.cpp','wire_hash.h')]
files += [p.relative_to(ROOT).as_posix() for p in (ROOT/'native/vendor').rglob('*') if p.is_file()]
buf=io.BytesIO()
with zipfile.ZipFile(buf,'w',zipfile.ZIP_DEFLATED) as z:
    for name in files:z.write(ROOT/name,name)
encoded=base64.b64encode(buf.getvalue()).decode()
code='''from pathlib import Path
import base64,hashlib,io,json,subprocess,tempfile,shutil,zipfile
root=Path(tempfile.mkdtemp(prefix='p4_native_build_')).resolve()
assert root.parent==Path(tempfile.gettempdir()).resolve() and root.name.startswith('p4_native_build_')
try:
    data=base64.b64decode(PAYLOAD)
    assert hashlib.sha256(data).hexdigest()==DIGEST
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        assert all((root/n).resolve().is_relative_to(root) for n in z.namelist())
        z.extractall(root)
    p=subprocess.run(['python3',str(root/'native/build_native.py')],capture_output=True,text=True,timeout=120)
    if p.returncode:raise RuntimeError((p.stdout+p.stderr)[-6000:])
    lib=(root/'native/liby50_native.so').read_bytes()
    result=dict(status='COMPILED_ARM_ONLY',sha256=hashlib.sha256(lib).hexdigest(),library_b64=base64.b64encode(lib).decode(),log=p.stdout+p.stderr)
finally:
    assert root.parent==Path(tempfile.gettempdir()).resolve() and root.name.startswith('p4_native_build_')
    shutil.rmtree(root)
result['owned_build_directory_removed']=not root.exists()
print('__REVIEW_RESULT__='+json.dumps(result),flush=True)
'''.replace('PAYLOAD',repr(encoded)).replace('DIGEST',repr(hashlib.sha256(buf.getvalue()).hexdigest()))
r=execute(code,145)
lib=base64.b64decode(r.pop('library_b64'))
assert hashlib.sha256(lib).hexdigest()==r['sha256']
(ROOT/'native/liby50_native.so').write_bytes(lib)
r['sources']={n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in files}
(ROOT/'evidence/arm_compile.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps({k:v for k,v in r.items() if k not in ('sources','log')}))
