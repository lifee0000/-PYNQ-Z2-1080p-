"""Compile and record unchanged ARM sources. No PYNQ import or hardware load."""
import hashlib,json,platform,subprocess,sys
from pathlib import Path
root=Path(__file__).resolve().parent;project=root.parent
if platform.machine()!='armv7l':raise SystemExit('Run this script on ARM32 Linux; no Windows substitute is accepted')
def sources():
    return {p.relative_to(project).as_posix():hashlib.sha256(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob('*')) if p.is_file() and (p.suffix in ('.c','.cpp','.h') or p.name=='build_native.py')}
before=sources()
subprocess.run([sys.executable,str(root/'build_native.py')],cwd=root,check=True)
if before!=sources():raise RuntimeError('Sources changed during compilation; do not record or package this library')
record=dict(machine=platform.machine(),source_sha256=before,sources_unchanged_during_build=True,
    native_sha256=hashlib.sha256((root/'liby50_native.so').read_bytes()).hexdigest())
(root/'arm_build.json').write_text(json.dumps(record,indent=2))
print(json.dumps(dict(status='ARM_COMPILED_AND_PROVENANCE_RECORDED_NOT_BOARD_TESTED',native_sha256=record['native_sha256'])))
