"""Reproducible PC conversion/statistics benchmark; never contacts a board.

The frozen NumPy functions below are the delivered V4 conversion equations
before the workspace optimization. They remain independent parity oracles.
Only converter calls are compared for speed; auto analysis is a current-only
measurement because its policy/diagnostics can evolve independently.
"""
import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from pathlib import Path

import numpy as np

from pixels import pack_rgb, unpack_rgb


SEED = 20261023
ROOT = Path(__file__).resolve().parent


def frozen_pack_rgb(a):
    """Original full-frame int32 implementation, before scratch reuse."""
    h, w = a.shape[:2]
    r, g, b = (a[:, :, i].astype(np.int32) for i in range(3))
    def plane(c, offset=0):
        return np.clip(((r*c[0]+g*c[1]+b*c[2]+32768) >> 16)+offset,
                       0, 255).astype(np.uint8)
    y = plane((13933, 46871, 4732))
    u = plane((-7509, -25259, 32768), 128)
    v = plane((32768, -29763, -3005), 128)
    raw = np.empty((h, w, 2), np.uint8)
    raw[:, :, 0] = y
    for c, offset in ((u, 0), (v, 1)):
        raw[:, offset::2, 1] = (c[:, 0::2].astype(np.uint16)+c[:, 1::2]+1)//2
    return raw.tobytes()


def frozen_unpack_rgb(payload, w, h):
    """Original quality_fixtures.rgb equations, including nearest pair UV."""
    frame = np.frombuffer(payload, np.uint8).reshape(h, w, 2)
    y = frame[:, :, 0].astype(np.int32)
    u = np.repeat(frame[:, 0::2, 1].astype(np.int32)-128, 2, axis=1)
    v = np.repeat(frame[:, 1::2, 1].astype(np.int32)-128, 2, axis=1)
    r = y+((103206*v+32768) >> 16)
    g = y-((12276*u+30679*v+32768) >> 16)
    b = y+((121609*u+32768) >> 16)
    return np.clip(np.stack((r, g, b), -1), 0, 255).astype(np.uint8)


def _json_value(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


def _sha(value):
    if isinstance(value, (bytes, bytearray, np.ndarray)):
        return hashlib.sha256(value).hexdigest()
    data = json.dumps(value, sort_keys=True, separators=(',', ':'),
                      default=_json_value).encode('utf-8')
    return hashlib.sha256(data).hexdigest()


def _summary(samples):
    return dict(samples=len(samples), median_ms=statistics.median(samples)*1000,
                p95_ms=float(np.percentile(samples, 95))*1000,
                min_ms=min(samples)*1000, max_ms=max(samples)*1000)


def _fixtures(width, height, count, seed):
    rng = np.random.default_rng(seed)
    cases = []
    for index in range(count):
        if index % 3 == 0:
            image = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
            kind = 'uniform_random_rgb'
        elif index % 3 == 1:
            # Stochastic patches exercise accepted-noise analysis as well as
            # the rejected textured patches in the uniform-random fixture.
            image = np.clip(rng.normal(96, 6, (height, width, 3)).round(),
                            0, 255).astype(np.uint8)
            kind = 'gray_gaussian_sigma6_rgb'
        else:
            x = np.linspace(0, 255, width).round().astype(np.uint8)
            image = np.empty((height, width, 3), np.uint8)
            image[:, :, 0] = x
            image[:, :, 1] = x[::-1]
            image[:, :, 2] = ((np.arange(height)[:, None] % 2)*255).astype(np.uint8)
            kind = 'gradient_saturated_rows_rgb'
        cases.append((f'{index:02}_{kind}', image))
    return cases


def benchmark(width=1280, height=720, repeats=5, warmup=2, frames=3,
              seed=SEED, include_auto=True):
    if (type(width) is not int or type(height) is not int
            or not (4 <= width <= 1280 and width % 2 == 0 and 3 <= height <= 720)):
        raise ValueError('even width 4..1280, height 3..720 required')
    for name, value, low, high in (('repeats', repeats, 1, 100),
                                  ('warmup', warmup, 0, 20), ('frames', frames, 1, 8)):
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{name} must be an integer in {low}..{high}')
    if type(seed) is not int or seed < 0:
        raise ValueError('seed must be a nonnegative integer')
    cases = _fixtures(width, height, frames, seed)
    report = dict(schema=1, status='PASS', evidence_kind='PC_CPU_BENCHMARK_ONLY',
        board_contacted=False, claim_50fps=False,
        limitations='Stage timings exclude video I/O, network, DMA and FPGA processing.',
        python=sys.version, numpy=np.__version__, platform=platform.platform(),
        processor=platform.processor(), seed=seed, geometry=[width, height],
        repeats=repeats, warmup=warmup, fixture_count=frames,
        timing_clock='time.perf_counter', hashes_outside_timed_region=True,
        stages={}, fixtures=[])
    payloads = [frozen_pack_rgb(image) for _, image in cases]
    for (name, image), payload in zip(cases, payloads):
        report['fixtures'].append(dict(name=name, rgb_sha256=_sha(image),
            yuyv_sha256=_sha(payload), payload_bytes=len(payload)))
    for name, functions, arguments in (
            ('pack_rgb', (frozen_pack_rgb, pack_rgb), [(image,) for _, image in cases]),
            ('unpack_rgb', (frozen_unpack_rgb, unpack_rgb),
             [(payload, width, height) for payload in payloads])):
        expected = [_sha(functions[0](*args)) for args in arguments]
        for args, digest in zip(arguments, expected):
            if _sha(functions[1](*args)) != digest:
                raise AssertionError(name+' initial byte parity failure')
        for _ in range(warmup):
            for function in functions:
                for args in arguments:
                    function(*args)
        samples = [[], []]
        # Alternate order to reduce fixed ordering effects. Hash every result
        # after its measured call, including all timed repetitions.
        for repeat in range(repeats):
            for variant in ((0, 1) if repeat % 2 == 0 else (1, 0)):
                for args, digest in zip(arguments, expected):
                    start = time.perf_counter()
                    result = functions[variant](*args)
                    elapsed = time.perf_counter()-start
                    if _sha(result) != digest:
                        raise AssertionError(name+' timed byte parity failure')
                    samples[variant].append(elapsed)
        baseline, optimized = (_summary(values) for values in samples)
        report['stages'][name] = dict(baseline=baseline, optimized=optimized,
            speedup=baseline['median_ms']/optimized['median_ms'],
            exact_byte_parity=True, baseline_sha256=expected, optimized_sha256=expected)
    if include_auto:
        from exposure_v4 import AUTO_POLICY, analyze_yuyv_v4
        samples = []
        digests = []
        diagnostics = []
        for payload in payloads:
            result = analyze_yuyv_v4(payload, width, height)
            digests.append(_sha(result))
            diagnostics.append(result[1])
        for _ in range(warmup):
            for payload in payloads:
                analyze_yuyv_v4(payload, width, height)
        for _ in range(repeats):
            for payload, digest in zip(payloads, digests):
                start = time.perf_counter()
                result = analyze_yuyv_v4(payload, width, height)
                elapsed = time.perf_counter()-start
                if _sha(result) != digest:
                    raise AssertionError('auto analysis repeated-result mismatch')
                samples.append(elapsed)
        report['stages']['auto_analysis'] = dict(current=_summary(samples),
            policy=AUTO_POLICY, deterministic=True, sha256=digests,
            noise_diagnostics=diagnostics, comparison='CURRENT_ONLY')
    report['source_sha256'] = {name: hashlib.sha256((ROOT/name).read_bytes()).hexdigest()
        for name in ('pixels.py', 'benchmark_pc.py', 'exposure_v4.py')}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--width', type=int, default=1280)
    parser.add_argument('--height', type=int, default=720)
    parser.add_argument('--repeats', type=int, default=5)
    parser.add_argument('--warmup', type=int, default=2)
    parser.add_argument('--frames', type=int, default=3)
    parser.add_argument('--seed', type=int, default=SEED)
    parser.add_argument('--skip-auto', action='store_true')
    parser.add_argument('--json', type=Path, help='Optional JSON report path')
    args = parser.parse_args()
    try:
        report = benchmark(args.width, args.height, args.repeats, args.warmup,
                           args.frames, args.seed, not args.skip_auto)
    except ValueError as exc:
        parser.error(str(exc))
    serialized = json.dumps(report, indent=2, ensure_ascii=False, default=_json_value)+'\n'
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(serialized, encoding='utf-8')
    print(serialized, end='')


if __name__ == '__main__':
    main()
