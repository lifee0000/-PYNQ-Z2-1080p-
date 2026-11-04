"""Seal a normal Windows-compatible ZIP and independently hash every member."""
from pathlib import Path
from zipfile import ZipFile,ZIP_DEFLATED
import hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1];dest=WS/'P4_UP'
archive=WS/'PYNQ_V4_UPGRADED_20261024.zip'
assert not archive.exists()
assert json.loads((dest/'evidence/upgrade_20261024/final_board_state.json').read_text())['status']=='STOPPED_DMA_HALTED_CORE_RESET'
assert json.loads((dest/'evidence/upgrade_20261024/full_videos.json').read_text())['status']=='PASS'
assert json.loads((dest/'QUALIFICATION.json').read_text())['target_720p50']=='NOT_ACHIEVED'
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        while block:=f.read(1024*1024):h.update(block)
    return h.hexdigest()
prior=WS/'PYNQ_V4_NETWORK_VERIFIED_20261023.zip'
assert sha(prior)=='4aca8049a72a5a6146a0dbf9a84875eb93225f6ee2d65c09664302837e0946c3','Prior sealed archive changed'
files={}
for p in sorted(dest.rglob('*')):
    if not p.is_file() or p==dest/'MANIFEST.json':continue
    rel=p.relative_to(dest).as_posix();assert not p.is_symlink() and len(rel)<=210,rel
    files[rel]=dict(bytes=p.stat().st_size,sha256=sha(p))
(dest/'MANIFEST.json').write_text(json.dumps(dict(schema=1,files=files,entry='START.cmd',
    original_uploads_changed=False,prior_sealed_archive_unchanged=True,target_720p50='NOT_ACHIEVED',
    compression='ZIP Deflate, no ZIP64',report='REPORT_CN.md'),indent=2,ensure_ascii=False),encoding='utf-8')
subprocess.run([sys.executable,str(dest/'verify_package.py')],check=True)
start=time.perf_counter()
with ZipFile(archive,'x',ZIP_DEFLATED,compresslevel=6,allowZip64=False) as z:
    for p in sorted(dest.rglob('*')):
        if p.is_file():z.write(p,'P4_UP/'+p.relative_to(dest).as_posix())
with ZipFile(archive) as z:
    assert z.testzip() is None
    assert len(z.infolist())==len(files)+1==len(set(z.namelist()))
    assert all(not info.flag_bits&1 and info.compress_type==ZIP_DEFLATED for info in z.infolist())
    for name,item in files.items():
        h=hashlib.sha256()
        with z.open('P4_UP/'+name) as f:
            while block:=f.read(1024*1024):h.update(block)
        assert h.hexdigest()==item['sha256'],name
record=dict(status='PASS',archive=str(archive),bytes=archive.stat().st_size,sha256=sha(archive),
    files=len(files)+1,all_crc_pass=True,all_member_sha256_pass=True,zip64=False,encrypted=False,
    max_member_path=max(len('P4_UP/'+name) for name in files),prior_archive_unchanged=True,seconds=time.perf_counter()-start)
(WS/'PYNQ_V4_UPGRADED_20261024.sha256').write_text(record['sha256']+'  '+archive.name+'\n',encoding='ascii')
(ROOT/'release_seal.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
print(json.dumps(record,ensure_ascii=False),flush=True)
