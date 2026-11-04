from pathlib import Path
import hashlib,json,shutil
ROOT=Path(__file__).resolve().parent;dst=ROOT/'experiments/v3_full_compress'
assert not dst.exists();dst.mkdir(parents=True)
frozen=ROOT/'Windows_App/PYNQVideoV4/_internal'
manifest=json.loads((frozen/'native_yuyv.experimental.json').read_text())
for name,digest in manifest['files'].items():
    p=frozen/name
    assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,name
    target=dst/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,target)
shutil.copy2(frozen/'native_yuyv.experimental.json',dst/'native_yuyv.experimental.json')
for name in ('wire_benchmark.json','benchmark_lifecycle.json','board_regression.json','pixels_v3_lz4.json','transport_v3.json','arm_compile.json'):
    p=ROOT/'evidence'/name
    if p.is_file():shutil.copy2(p,dst/name)
print('Preserved full-compression candidate measurements and compiled-source identity')
