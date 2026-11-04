"""Qualify one frozen native candidate; actual board owner always cleaned."""
from pathlib import Path
import json,subprocess,sys,time
ROOT=Path(__file__).resolve().parent
from board_link import ManagedBoard
from benchmark_wire_upgrade import prepare,run
cases=prepare();b=ManagedBoard();record=dict(status='RUNNING',checks=[])
try:
    record['start']=b.start()
    for script,name in (('verify_board.py','pixels_v3_lz4.json'),('verify_transport_board.py','transport_v3.json')):
        with (ROOT/'evidence'/(script+'.log')).open('w',encoding='utf-8') as log:
            p=subprocess.run([sys.executable,script,'--out','evidence/'+name],cwd=ROOT,
                stdout=log,stderr=subprocess.STDOUT,timeout=240)
        record['checks'].append(dict(script=script,returncode=p.returncode))
        assert p.returncode==0,script
    record['benchmark']=run(cases)['status']
    record['status']='PASS'
finally:
    record['cleanup']=b.stop()
    (ROOT/'evidence/qualification_board.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
