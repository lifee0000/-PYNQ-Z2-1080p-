"""Reproducible offline P0 tests and synthetic truth metrics; no hardware access."""
import argparse
import io
import json
from pathlib import Path
import time
import unittest

import exposure_v4
import test_exposure_v4


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    suite = unittest.defaultTestLoader.loadTestsFromModule(test_exposure_v4)
    stream = io.StringIO()
    start = time.perf_counter()
    result = unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    report = dict(schema=1,policy=exposure_v4.AUTO_POLICY,execution='CPU reference and PC controller only',
        tests_run=result.testsRun,passed=result.wasSuccessful(),
        elapsed_seconds=round(time.perf_counter()-start,6),
        metrics=test_exposure_v4.METRICS,
        limits=[
            'This evaluation does not build BIT/HWH or executables or establish physical-board throughput.',
            'Sigma describes sampled quantized/clipped observations, not recovered sensor noise.',
            'Confidence fields are bounded evidence scores, not calibrated probabilities.',
            'Isolated lights and impulse noise, and codec artifacts and textures, are ambiguous in one frame.',
            'Impulse/compression candidates do not independently enable filtering.',
            'No ground-truth PSNR claim is made for real recorded video.',
            'Sampling can miss small or unsampled image regions.'],
        unittest_log=stream.getvalue())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(stream.getvalue(),end='')
    print(str(args.output.resolve()))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':
    raise SystemExit(main())
