from pathlib import Path
import hashlib,json,shutil,sys
root=Path(__file__).resolve().parent
name=sys.argv[1];assert name.replace('_','').isalnum()
dest=root/'experiments'/name;assert not dest.exists()
manifest=json.loads((root/'native_yuyv.experimental.json').read_text())
for item,digest in manifest['files'].items():
    p=root/item;assert hashlib.sha256(p.read_bytes()).hexdigest()==digest,item
    t=dest/item;t.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,t)
shutil.copy2(root/'native_yuyv.experimental.json',dest/'native_yuyv.experimental.json')
for n in ('wire_benchmark.json','qualification_board.json','pixels_v3_lz4.json','transport_v3.json','arm_compile.json','arm_hash.json'):
    if (root/'evidence'/n).is_file():shutil.copy2(root/'evidence'/n,dest/n)
print('Preserved '+name)
