"""Finite idle lease for a single app-owned temporary runtime.

This guardian never accesses MMIO, never force-kills, and never installs a boot
service. Only the verified native bootstrap owns/halts/frees hardware buffers.
"""
from pathlib import Path
import argparse,json,os,signal,sys,tempfile,time,shutil
from protocol import status

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--owner',required=True);p.add_argument('--pid',type=int,required=True)
    p.add_argument('--host',required=True);p.add_argument('--port',type=int,default=5010)
    p.add_argument('--idle-seconds',type=float,default=120);a=p.parse_args()
    root=a.root.resolve()
    if (root.parent!=Path(tempfile.gettempdir()).resolve() or
        root.name!='pynq_v4_session_'+a.owner or root.is_symlink() or
        (root/'.owner').read_text()!=a.owner or not 10<=a.idle_seconds<=600):
        raise ValueError('Invalid temporary runtime lease')
    expected=str(root/'native/board_bootstrap.py').encode()
    last=time.monotonic();last_counts=None;requested=False
    while True:
        try:args=Path('/proc',str(a.pid),'cmdline').read_bytes().split(b'\0')
        except FileNotFoundError:break
        if expected not in args:raise RuntimeError('PID identity changed; refusing to signal or clean')
        try:
            state=status(a.host,a.port,1)
            counts=(state['sessions'],state['received'],state['processed'],state['sent'])
            if counts!=last_counts or state['state']=='OWNED':last=time.monotonic()
            last_counts=counts
            if state['state']=='UNSAFE_DMA':
                # Preserve the live process and CMA; no forced cleanup.
                time.sleep(1);continue
            expired=state['state']=='IDLE' and time.monotonic()-last>=a.idle_seconds
            fault=state['state']=='FAULT_LATCHED'
            if (expired or fault) and not requested:
                os.kill(a.pid,signal.SIGTERM);requested=True
        except (OSError,ConnectionError):
            # Covers a failed startup/listen as well as an abandoned client.
            # SIGTERM invokes bootstrap's own hardware cleanup, never SIGKILL.
            if not requested and time.monotonic()-last>=a.idle_seconds:
                os.kill(a.pid,signal.SIGTERM);requested=True
        # Each poll is a TCP connect plus a status JSON from the service. The
        # lease is >=10 s, so 1 Hz is ample and avoids 4 Hz wakeups on a busy CPU.
        time.sleep(1)
    # Re-resolve and verify the final absolute target immediately before delete.
    if (root.resolve()==root and root.parent==Path(tempfile.gettempdir()).resolve()
            and root.name=='pynq_v4_session_'+a.owner and
            (root/'.owner').read_text()==a.owner):
        shutil.rmtree(root)

if __name__=='__main__':main()
