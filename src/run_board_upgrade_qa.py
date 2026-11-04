"""Actual-board pixel, ownership and codec regressions with owned cleanup."""
from pathlib import Path
import json,subprocess,sys
ROOT=Path(__file__).resolve().parent
from board_link import ManagedBoard

def main():
    board=ManagedBoard();report=dict(status='RUNNING',commands=[])
    try:
        report['start']=board.start()
        commands=[['verify_board.py','--out','evidence/pixels_v3_lz4.json'],
                  ['verify_transport_board.py','--out','evidence/transport_v3.json']]
        for args in commands:
            with (ROOT/'evidence'/(Path(args[0]).stem+'.log')).open('w',encoding='utf-8') as log:
                p=subprocess.run([sys.executable,*args],cwd=ROOT,stdout=log,stderr=subprocess.STDOUT,timeout=240)
            report['commands'].append(dict(command=args,exit_code=p.returncode))
            if p.returncode:raise RuntimeError('Board regression failed: '+args[0])
        report['status']='PASS'
    except BaseException as exc:
        report.update(status='FAIL',error=str(exc));raise
    finally:
        report['cleanup']=board.stop()
        (ROOT/'evidence/board_regression.json').write_text(json.dumps(report,indent=2),encoding='utf-8')

if __name__=='__main__':main()
