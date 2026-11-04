"""Read-only final idle snapshot. Never reads HLS AXI-Lite while reset."""
from pathlib import Path
import json,sys
ROOT=Path(__file__).resolve().parent
from board_control import execute
code='''from pathlib import Path
import json,socket,tempfile
from pynq import MMIO
programs=[]
for p in Path('/proc').iterdir():
    if not p.name.isdigit():continue
    try:
        cmd=(p/'cmdline').read_bytes().split(b'\\0')
        if any(b'native/board_bootstrap.py' in arg or b'tools/run_video_' in arg for arg in cmd):
            programs.append(dict(pid=int(p.name),command=[a.decode(errors='replace') for a in cmd if a]))
    except (OSError,ProcessLookupError):pass
temporary=[]
for prefix in ('pynq_v4_session_','p4_native_build_','p4_hash_check_'):
    temporary.extend(str(p) for p in Path(tempfile.gettempdir()).glob(prefix+'*'))
v=MMIO(0x43000000,0x10000);g=MMIO(0x41270000,0x1000)
registers=dict(mm2s_control=v.read(0),mm2s_status=v.read(4),s2mm_control=v.read(0x30),s2mm_status=v.read(0x34))
reset=g.read(0)
assert not programs and not temporary,(programs,temporary)
assert not registers['mm2s_control']&1 and not registers['s2mm_control']&1
assert registers['mm2s_status']&1 and registers['s2mm_status']&1 and reset==0
ports={}
for port in (5010,5012):
    try:
        with socket.create_connection(('192.168.2.99',port),.4):ports[str(port)]='OPEN'
    except OSError:ports[str(port)]='CLOSED'
assert all(value=='CLOSED' for value in ports.values())
print('__REVIEW_RESULT__='+json.dumps(dict(status='STOPPED_DMA_HALTED_CORE_RESET',
    active_processing_programs=programs,temporary_runtime_directories=temporary,
    registers=registers,reset_gpio=reset,ports=ports,linux_jupyter='RUNNING',
    bitstream_configuration='RETAINED_PROCESSING_RESET')),flush=True)
'''
r=execute(code,35)
(ROOT/'evidence/final_board_state.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(r))
