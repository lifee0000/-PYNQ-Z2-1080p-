"""Package the matched ARM runtime for app-owned temporary deployment."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json
from identity import load_identity

root=Path(__file__).resolve().parent
identity=load_identity(root)
manifest=json.loads((root/'native_yuyv.experimental.json').read_text())
names=set(manifest['files'])|{'native_yuyv.experimental.json','native/lease_guard.py'}
target=root/'board_runtime.zip'
with ZipFile(target,'w',ZIP_DEFLATED,allowZip64=False) as z:
    for name in sorted(names):z.write(root/name,name)
record=dict(schema=1,identity=identity,archive_sha256=hashlib.sha256(target.read_bytes()).hexdigest(),
    files={n:hashlib.sha256((root/n).read_bytes()).hexdigest() for n in sorted(names)},
    deployment='APP_OWNED_TEMPORARY_NO_BOOT_SERVICE',idle_lease_seconds=120)
(root/'board_runtime.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(dict(status='PACKAGED_MATCHED_RUNTIME',sha256=record['archive_sha256'])))
