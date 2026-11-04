"""PC-side manifest reader. Never loads a library or an FPGA overlay."""
from pathlib import Path
import hashlib,json
from native.binding import ABI
from native.protocol import VERSION

def load_identity(root):
    root=Path(root).resolve();path=root/'native_yuyv.experimental.json'
    m=json.loads(path.read_text(encoding='utf-8'))
    if (m.get('schema')!=2 or m.get('native_abi')!=ABI or m.get('protocol_version')!=VERSION or m.get('state')!='EXPERIMENTAL_UNQUALIFIED' or
            m.get('top')!='video_enhance_yuyv422_v4_split_core' or
            m.get('pixel_format')!='YUYV422_BT709_FULL_YUV_V4_SPLIT'):
        raise ValueError('Unsupported V4 build identity')
    def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
    for name,expected in m['files'].items():
        p=(root/name).resolve()
        if not p.is_relative_to(root) or not p.is_file() or digest(p)!=expected:
            raise ValueError('Build file mismatch: '+name)
    return dict(manifest_sha256=digest(path),qualification=m['state'],top=m['top'],pixel_format=m['pixel_format'],
        **{name:digest(root/m[key]) for name,key in (
            ('bit_sha256','bit_file'),('hwh_sha256','hwh_file'),
            ('register_sha256','register_file'),('native_sha256','native_library'))})
