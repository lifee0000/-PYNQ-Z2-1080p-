"""Explicit CPU reference runner for V4; never connects to an FPGA.

This exercises the existing integer reference, conversion and auto controller.
It produces software previews and reproducible diagnostics, not board evidence.
The physical FPGA client remains in run_video.py.
"""
from collections import deque
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
import argparse
import hashlib
import json
import os
import threading
import time
import uuid

import av
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from exposure_v4 import AUTO_POLICY, ExposureControllerV4, analyze_yuyv_v4
from geometry import DEFAULT_OUTPUT
from media_frame import export_frame, tag_bt709
from pixels import pack_rgb, unpack_rgb
from reference import PIXEL_FORMAT, Params, enhance
from auto_v5 import AutoOptimizerV5, AUTO_POLICY_V5, detail_profile
from image_controls import controls_snapshot, apply_controls
from signal_curves import apply_curves, plan_roi

ROOT = Path(__file__).resolve().parent
BACKEND = 'SOFTWARE_REFERENCE'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def sha_file(path, cancel=None):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data := stream.read(1024 * 1024):
            if cancel is not None and cancel.is_set():
                raise InterruptedError('Cancelled')
            digest.update(data)
    return digest.hexdigest()


def _timestamp(frame, time_base, origin, previous):
    if frame.pts is None:
        raise ValueError('Missing PTS; refusing to invent frame timing')
    pts = round(Fraction(frame.pts) * (frame.time_base or time_base) / time_base) - origin
    if pts < 0 or (previous is not None and pts <= previous):
        raise ValueError('Nonmonotonic PTS')
    return pts


def _fit(rgb, width, height):
    if rgb.shape[:2] == (height, width):
        return rgb, None
    image = ImageOps.contain(Image.fromarray(rgb), (width, height), Image.Resampling.LANCZOS)
    if image.width < 3 or image.height < 3:
        raise ValueError('Fitted content must be at least 3x3; select a suitable output geometry')
    x, y = (width - image.width) // 2, (height - image.height) // 2
    canvas = Image.new('RGB', (width, height))
    canvas.paste(image, (x, y))
    return np.asarray(canvas), (x, y, image.width, image.height)


def _preview(output, index, source, result, payload):
    folder = output.parent / (output.stem + '_frames')
    folder.mkdir(exist_ok=True)
    Image.fromarray(source).save(folder / f'{index:04}_source.png')
    Image.fromarray(result).save(folder / f'{index:04}_cpu_reference.png')
    (folder / f'{index:04}_cpu_reference.yuyv').write_bytes(payload)
    height, width = source.shape[:2]
    pair = Image.new('RGB', (width * 2, height + 32))
    pair.paste(Image.fromarray(source), (0, 32))
    pair.paste(Image.fromarray(result), (width, 32))
    draw = ImageDraw.Draw(pair)
    draw.text((10, 8), 'SOURCE', fill='white')
    draw.text((width + 10, 8), 'V4 CPU REFERENCE', fill='white')
    pair.save(folder / f'{index:04}_comparison.png')


def process(source, output, *, mode=5, auto=True, width=DEFAULT_OUTPUT[0], height=DEFAULT_OUTPUT[1],
            max_frames=None, cancel=None, notify=lambda kind, data: None,
            selected_frames=(0, 50, 336, 500), auto_policy='v4', image_controls=None,
            preview_detail=False, preview_focus=None, parameter_curves=None, curve_region=None):
    """Render with V4's CPU reference and return a JSON-compatible report.

    ``notify`` matches run_video.process: progress contains frames, elapsed,
    source and result arrays; done contains the report. Existing outputs and
    diagnostics are protected. Runtime failure/cancellation returns a report
    and removes the partial video. Invalid arguments raise ValueError.

    PTS uses the source video time base, normalized by its stream start time.
    Full runs remux the first audio stream without re-encoding. Frame-limited
    runs retain complete audio packets beginning before the final frame end;
    a final packet may therefore extend slightly beyond the video boundary.
    """
    source, output = Path(source).resolve(), Path(output).resolve()
    report_path = Path(str(output) + '.json')
    trace = Path(str(output) + '.frames.jsonl')
    preview_folder = output.parent / (output.stem + '_frames')
    if source == output or any(path.exists() for path in (output, report_path, trace, preview_folder)):
        raise ValueError('Select a new output file; source/output and existing diagnostics cannot be overwritten')
    if output.suffix.lower() not in ('.mp4', '.mkv'):
        raise ValueError('MP4/MKV output required')
    Params(mode=mode).validate(width, height)
    if height % 2:
        raise ValueError('Even output height required for yuv420p encoding')
    if max_frames is not None and (type(max_frames) is not int or max_frames <= 0):
        raise ValueError('max_frames must be a positive integer or None')
    if not source.is_file():
        raise ValueError('Input video file does not exist')
    auto = bool(auto and mode == 5)
    if auto_policy not in ('v4', 'v5'):
        raise ValueError('auto_policy must be v4 or v5')
    initial_controls = controls_snapshot(image_controls).to_dict()
    cancel = cancel if cancel is not None else threading.Event()
    output.parent.mkdir(parents=True, exist_ok=True)
    temp = output.with_name('.' + output.stem + '.' + uuid.uuid4().hex[:10] + '.part' + output.suffix)
    report = dict(schema=1, backend=BACKEND, algorithm='enhance-v4-split-y-uv',
        pixel_format=PIXEL_FORMAT, temporal_filter='DISABLED',
        pixel_algorithm_execution='CPU', auto_statistics_execution='CPU',
        hardware_validation='NOT_PERFORMED_NO_BOARD',
        auto_params=auto, auto_policy=(AUTO_POLICY_V5 if auto_policy == 'v5' else AUTO_POLICY) if auto else None,
        image_controls_initial=initial_controls, image_control_changes=[],
        input=str(source), output=str(output), mode=mode, geometry=[width, height],
        max_frames=max_frames, frame_limit_reached=False, frames=0, status='RUNNING',
        started_utc=datetime.now(timezone.utc).isoformat(), frame_trace=str(trace),
        selected_frames=[], missing_pts=0, audio_packets=0,
        stage_seconds=dict(decode_pack=0., auto_analysis=0., reference=0., encode=0.),
        timing_policy='source_pts_minus_video_stream_start',
        audio_limit_policy='complete_packets_starting_before_last_frame_end' if max_frames else 'full_source')
    begin = time.perf_counter()
    try:
        if cancel.is_set():
            raise InterruptedError('Cancelled')
        report['input_sha256'] = sha_file(source, cancel)
        report['reference_code_sha256'] = {name: sha_file(ROOT / name) for name in
            ('reference.py', 'reference_v3_frozen.py', 'geometry.py', 'pixels.py', 'exposure_v4.py')}
        # Audio can begin before the video stream. Keep its negative normalized
        # timestamps instead of letting the muxer silently shift every stream.
        options = {'avoid_negative_ts': 'disabled'}
        if output.suffix.lower() == '.mp4':
            options['movflags'] = '+faststart'
        with av.open(str(source)) as inp, av.open(str(temp), 'w', options=options) as out, trace.open('x', encoding='utf-8') as log:
            if not inp.streams.video:
                raise ValueError('Input contains no video stream')
            vs = inp.streams.video[0]
            tb = vs.time_base or Fraction(1, 90000)
            rate = vs.average_rate or vs.guessed_rate or Fraction(25)
            origin = vs.start_time or 0
            encoded = out.add_stream('libx264', rate=rate)
            encoded.width, encoded.height = width, height
            encoded.pix_fmt = 'yuv420p'
            encoded.time_base = encoded.codec_context.time_base = tb
            encoded.options = {'crf': '18', 'preset': 'veryfast', 'bf': '0'}
            tag_bt709(encoded)
            ai = inp.streams.audio[0] if inp.streams.audio else None
            ao = out.add_stream_from_template(ai) if ai is not None else None
            report.update(source_geometry=[vs.width, vs.height], source_rate=str(rate),
                time_base=str(tb), source_start_pts=origin,
                audio='passthrough' if ai is not None else 'none',
                audio_codec=ai.codec_context.name if ai is not None else None)
            controller = AutoOptimizerV5() if auto_policy == 'v5' else ExposureControllerV4()
            pending_audio = deque()
            pending_bytes = 0
            last = None
            video_end = None
            limit_end = None
            next_notify = 0.

            def flush_audio(boundary=None):
                nonlocal pending_bytes
                while pending_audio and (boundary is None or pending_audio[0][0] < boundary):
                    audio_time, packet = pending_audio.popleft()
                    pending_bytes -= packet.size
                    packet.stream = ao
                    out.mux(packet)
                    report['audio_packets'] += 1

            for packet in inp.demux([vs] + ([ai] if ai is not None else [])):
                if cancel.is_set():
                    raise InterruptedError('Cancelled')
                if ai is not None and packet.stream.index == ai.index:
                    if packet.size and packet.dts is not None:
                        audio_tb = packet.time_base or ai.time_base
                        shift = round(Fraction(origin) * tb / audio_tb)
                        if packet.pts is not None:
                            packet.pts -= shift
                        packet.dts -= shift
                        audio_time = (packet.pts if packet.pts is not None else packet.dts) * audio_tb
                        if limit_end is not None and audio_time >= limit_end:
                            break
                        pending_audio.append((audio_time, packet))
                        pending_bytes += packet.size
                        if pending_bytes > 32 * 1024 * 1024:
                            raise ValueError('Audio leads video by more than the 32 MiB bounded buffer')
                        if video_end is not None:
                            flush_audio(video_end)
                    continue
                if limit_end is not None:
                    continue
                start = time.perf_counter()
                frames = packet.decode()
                report['stage_seconds']['decode_pack'] += time.perf_counter() - start
                for frame in frames:
                    if cancel.is_set():
                        raise InterruptedError('Cancelled')
                    start = time.perf_counter()
                    if frame.pts is None:
                        report['missing_pts'] += 1
                    pts = _timestamp(frame, tb, origin, last)
                    rgb, rect = _fit(frame.to_ndarray(format='rgb24'), width, height)
                    payload = pack_rgb(rgb)
                    parameters = asdict(Params(mode=mode))
                    if rect is not None:
                        parameters.update(roi_enable=1, **dict(zip(
                            ('roi_x', 'roi_y', 'roi_width', 'roi_height'), rect)))
                    report['stage_seconds']['decode_pack'] += time.perf_counter() - start
                    decision = None
                    if auto:
                        start = time.perf_counter()
                        stats, noise = analyze_yuyv_v4(payload, width, height, rect)
                        if auto_policy == 'v5':
                            upscale = round(256 * (rect[3] if rect else height) / max(1, vs.height))
                            values, decision = controller.update(round(pts * tb * 1000), stats, noise,
                                detail_profile(payload, width, height, rect, noise.get('sigma_q8')), upscale)
                        else:
                            values, decision = controller.update(round(pts * tb * 1000), stats, noise)
                        parameters.update(values)
                        report['stage_seconds']['auto_analysis'] += time.perf_counter() - start
                    controls = controls_snapshot(image_controls)
                    parameters = apply_controls(parameters, controls, automatic=auto)
                    if parameter_curves:
                        parameters = apply_curves(parameters, report['frames'], parameter_curves)
                    if curve_region is not None:
                        parameters.update(plan_roi(curve_region, (width, height), (width, height), rect))
                    start = time.perf_counter()
                    result_payload = enhance(payload, width, height, Params(**parameters))
                    report['stage_seconds']['reference'] += time.perf_counter() - start
                    if cancel.is_set():
                        raise InterruptedError('Cancelled')
                    start = time.perf_counter()
                    enhanced = unpack_rgb(result_payload, width, height)
                    vf = export_frame(enhanced)
                    vf.pts, vf.time_base = pts, tb
                    duration = (Fraction(frame.duration) * (frame.time_base or tb)
                                if frame.duration else Fraction(1, 1) / rate)
                    vf.duration = max(1, round(duration / tb))
                    for encoded_packet in encoded.encode(vf):
                        out.mux(encoded_packet)
                    report['stage_seconds']['encode'] += time.perf_counter() - start
                    index = report['frames']
                    log.write(json.dumps(dict(frame_id=index, pts=pts, time_base=str(tb),
                        image_controls=controls.to_dict(),
                        backend=BACKEND, parameters=parameters, auto_decision=decision,
                        input_sha256=sha(payload), output_sha256=sha(result_payload)), ensure_ascii=False) + '\n')
                    report['frames'] += 1
                    changes = report['image_control_changes']
                    if not changes or changes[-1]['settings'] != controls.to_dict():
                        changes.append(dict(frame_id=index, settings=controls.to_dict()))
                    if index in selected_frames:
                        _preview(output, index, rgb, enhanced, result_payload)
                        report['selected_frames'].append(index)
                    last = pts
                    video_end = Fraction(pts) * tb + duration
                    flush_audio(video_end)
                    if time.perf_counter() >= next_notify:
                        window = None
                        if preview_detail:
                            from run_video import preview_window
                            window = preview_window(width, height, tuple(preview_focus) if preview_focus is not None else None)
                        def view(image):
                            return image[window[1]:window[1]+window[3], window[0]:window[0]+window[2]] if window else image
                        notify('progress', dict(frames=report['frames'], elapsed=time.perf_counter()-begin,
                            source=view(rgb), result=view(enhanced), preview_window=window,
                            preview_detail=bool(window), source_fps=float(rate), source_size=(vs.width, vs.height),
                            processing_size=(width, height), output_size=(width, height),
                            image_controls=controls.to_dict(), parameters=dict(parameters)))
                        next_notify = time.perf_counter() + .3
                    if max_frames is not None and report['frames'] >= max_frames:
                        report['frame_limit_reached'] = True
                        limit_end = video_end
                        report['frame_limit_end_seconds'] = str(limit_end)
                        break
                if limit_end is not None and ai is None:
                    break
            if report['frames'] == 0:
                raise ValueError('No decoded frames')
            flush_audio(limit_end)
            for encoded_packet in encoded.encode(None):
                out.mux(encoded_packet)
        if cancel.is_set():
            raise InterruptedError('Cancelled')
        if output.exists():
            raise ValueError('Output appeared during processing; refusing to overwrite it')
        os.rename(temp, output)
        report.update(status='PASS', output_sha256=sha_file(output))
    except BaseException as exc:
        report.update(status='CANCELLED' if isinstance(exc, (InterruptedError, KeyboardInterrupt)) else 'FAIL',
                      error=str(exc))
    finally:
        temp.unlink(missing_ok=True)
        report.update(elapsed_seconds=time.perf_counter()-begin,
                      finished_utc=datetime.now(timezone.utc).isoformat())
        report['processing_fps'] = report['frames'] / max(report['elapsed_seconds'], 1e-9)
        report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
        notify('done', report)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description='V4 CPU reference video preview; no FPGA required or verified')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', type=int, choices=range(6), default=5)
    parser.add_argument('--fixed', action='store_true', help='Use fixed reference defaults instead of auto parameters')
    parser.add_argument("--width", type=int, default=DEFAULT_OUTPUT[0])
    parser.add_argument("--height", type=int, default=DEFAULT_OUTPUT[1])
    parser.add_argument('--max-frames', type=int, help='Process only the first N frames')
    args = parser.parse_args(argv)

    def progress(kind, data):
        if kind == 'progress':
            print(json.dumps(dict(event=kind, backend=BACKEND, frames=data['frames'], elapsed=data['elapsed'])), flush=True)

    try:
        report = process(args.input, args.output, mode=args.mode, auto=not args.fixed,
            width=args.width, height=args.height, max_frames=args.max_frames, notify=progress)
    except (ValueError, OSError) as exc:
        print(json.dumps(dict(status='FAIL', backend=BACKEND, error=str(exc))), flush=True)
        return 1
    print(json.dumps({key: report[key] for key in ('status', 'backend', 'frames', 'elapsed_seconds', 'processing_fps')}, ensure_ascii=False), flush=True)
    return 0 if report['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
