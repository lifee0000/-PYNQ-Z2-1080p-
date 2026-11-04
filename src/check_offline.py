"""Run reproducible software checks without loading an overlay or contacting a board."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('evidence/offline_checks'))
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    groups = [('software', root, ['test_spatial', 'test_exposure_v4', 'test_pixels', 'test_native_pixels', 'test_offline_video'])]
    # The delivered .so targets ARM32. Only the Windows mock DLL can run on a
    # normal Windows PC; never attempt to load the ARM artifact on another CPU.
    if os.name == 'nt':
        groups.append(('transport_mock', root/'native', ['test_native_mock','test_wire_v3','test_codec']))
    report = dict(schema=1, backend='SOFTWARE_CHECKS_ONLY',
                  hardware_validation='NOT_PERFORMED_NO_BOARD', groups=[])
    for name, cwd, modules in groups:
        begin = time.perf_counter()
        with (folder/(name+'.log')).open('w', encoding='utf-8') as log:
            result = subprocess.run([sys.executable, '-m', 'unittest', '-v', *modules],
                                    cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        report['groups'].append(dict(name=name, returncode=result.returncode,
                                    elapsed_seconds=time.perf_counter()-begin,
                                    log=name+'.log'))
    report['status'] = 'PASS' if all(g['returncode']==0 for g in report['groups']) else 'FAIL'
    (folder/'summary.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report['status']=='PASS' else 1)


if __name__ == '__main__':
    main()
