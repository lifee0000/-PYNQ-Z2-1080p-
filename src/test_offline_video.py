"""Small real-container tests for the explicit V4 software runner; no board."""
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import av
import numpy as np

import offline_video as offline
from pixels import pack_rgb
from reference import Params, enhance


def make_video(path, pts=(0, 40, 120, 160), audio=False):
    """Lossless source with known VFR presentation timestamps and optional PCM."""
    packets = []
    with av.open(str(path), 'w') as output:
        video = output.add_stream('ffv1', rate=25)
        video.width, video.height = 64, 48
        video.pix_fmt = 'bgr0'
        video.time_base = video.codec_context.time_base = Fraction(1, 1000)
        sound = output.add_stream('pcm_s16le', rate=8000) if audio else None
        if sound is not None:
            sound.layout = 'mono'
        for index, timestamp in enumerate(pts):
            rgb = np.full((48, 64, 3), 48 + index * 8, np.uint8)
            rgb[10:16, 20:32] = 96 + index * 8
            frame = av.VideoFrame.from_ndarray(rgb, format='rgb24')
            frame.pts, frame.time_base = timestamp, Fraction(1, 1000)
            packets.extend(video.encode(frame))
        packets.extend(video.encode(None))
        if sound is not None:
            for sample in range(0, 2000, 160):
                count = min(160, 2000 - sample)
                values = (np.sin(np.arange(sample, sample+count) * .1) * 1000).astype(np.int16)[None, :]
                frame = av.AudioFrame.from_ndarray(values, format='s16', layout='mono')
                frame.sample_rate, frame.pts, frame.time_base = 8000, sample, Fraction(1, 8000)
                packets.extend(sound.encode(frame))
            packets.extend(sound.encode(None))
        packets.sort(key=lambda packet: packet.dts * packet.time_base)
        for packet in packets:
            output.mux(packet)


def audio_packets(path):
    with av.open(str(path)) as source:
        stream = source.streams.audio[0]
        return [(bytes(packet), packet.pts * packet.time_base,
                 packet.dts * packet.time_base) for packet in source.demux(stream)
                if packet.size and packet.dts is not None]


class OfflineVideo(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.source = self.folder / 'source.mkv'
        make_video(self.source)

    def tearDown(self):
        self.temp.cleanup()

    def process(self, name='result.mkv', **kwargs):
        output = self.folder / name
        report = offline.process(self.source, output, width=64, height=48, **kwargs)
        return output, report

    def test_fixed_reference_hashes_vfr_pts_and_explicit_cpu_report(self):
        output, report = self.process(auto=False)
        self.assertEqual(report['status'], 'PASS', report)
        self.assertEqual(report['backend'], 'SOFTWARE_REFERENCE')
        self.assertEqual(report['pixel_algorithm_execution'], 'CPU')
        self.assertEqual(report['hardware_validation'], 'NOT_PERFORMED_NO_BOARD')
        self.assertNotIn('identity', report)
        self.assertNotIn('dma_seconds', report)
        trace = [json.loads(line) for line in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['pts'] for row in trace], [0, 40, 120, 160])
        self.assertEqual(report['frames'], 4)
        with av.open(str(self.source)) as source:
            for frame, row in zip(source.decode(video=0), trace):
                payload = pack_rgb(frame.to_ndarray(format='rgb24'))
                expected = enhance(payload, 64, 48, Params(**row['parameters']))
                self.assertEqual(row['input_sha256'], hashlib.sha256(payload).hexdigest())
                self.assertEqual(row['output_sha256'], hashlib.sha256(expected).hexdigest())
                self.assertIsNone(row['auto_decision'])
        with av.open(str(output)) as result:
            decoded = list(result.decode(video=0))
        self.assertEqual([frame.pts * frame.time_base for frame in decoded],
                         [Fraction(value, 1000) for value in (0, 40, 120, 160)])
        self.assertEqual(len(decoded), 4)
        saved = output.parent / (output.stem+'_frames') / '0000_cpu_reference.yuyv'
        self.assertEqual(hashlib.sha256(saved.read_bytes()).hexdigest(), trace[0]['output_sha256'])
        self.assertEqual(json.loads(Path(str(output)+'.json').read_text(encoding='utf-8'))['status'], 'PASS')

    def test_auto_and_frame_limit_and_progress_contract(self):
        events = []
        output, report = self.process('limited.mp4', max_frames=2,
            notify=lambda kind, data: events.append((kind, data)))
        self.assertEqual(report['status'], 'PASS', report)
        self.assertTrue(report['auto_params'])
        self.assertTrue(report['frame_limit_reached'])
        self.assertEqual(report['frames'], 2)
        trace = [json.loads(line) for line in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(row['auto_decision'] is not None for row in trace))
        self.assertGreater(trace[0]['parameters']['gain_q8_8'], 256)
        self.assertEqual(events[-1][0], 'done')
        self.assertEqual(events[0][0], 'progress')
        self.assertEqual(events[0][1]['result'].shape, (48, 64, 3))
        with av.open(str(output)) as result:
            self.assertEqual(len(list(result.decode(video=0))), 2)

    def test_v5_live_manual_controls_match_reference_and_preview_crop(self):
        from image_controls import ImageControls, LiveImageControls
        live=LiveImageControls(ImageControls(brightness=10,sharpen=60,clarity=0))
        later=ImageControls(preset='balanced',brightness=-5,denoise=40,sharpen=25,clarity=25)
        previews=[]
        def notify(kind,data):
            if kind=='progress':
                previews.append(data)
                live.update(later)
        with patch('run_video.PREVIEW_LIMIT',(16,12)):
            output,report=self.process('manual.mkv',auto_policy='v5',image_controls=live,
                preview_detail=True,preview_focus=[1.,1.],notify=notify)
        self.assertEqual(report['status'],'PASS',report)
        self.assertIn('v5',report['auto_policy'])
        trace=[json.loads(l) for l in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(trace[-1]['image_controls'],later.to_dict())
        self.assertEqual(len(report['image_control_changes']),2)
        with av.open(str(self.source)) as source:
            for frame,row in zip(source.decode(video=0),trace):
                payload=pack_rgb(frame.to_ndarray(format='rgb24'))
                expected=enhance(payload,64,48,Params(**row['parameters']))
                self.assertEqual(row['output_sha256'],hashlib.sha256(expected).hexdigest())
        self.assertEqual(previews[0]['preview_window'],(48,36,16,12))
        self.assertEqual(previews[0]['source'].shape,(12,16,3))
        self.assertEqual(previews[0]['result'].shape,(12,16,3))

    def test_audio_full_passthrough_and_limited_packet_boundary(self):
        self.source = self.folder / 'sound.mkv'
        make_video(self.source, audio=True)
        original = audio_packets(self.source)
        output, report = self.process('sound_result.mkv', auto=False, selected_frames=())
        self.assertEqual(report['status'], 'PASS', report)
        self.assertEqual(report['audio'], 'passthrough')
        self.assertEqual(audio_packets(output), original)
        self.assertEqual(report['audio_packets'], len(original))
        limited, limited_report = self.process('sound_limited.mkv', auto=False, max_frames=2, selected_frames=())
        self.assertEqual(limited_report['status'], 'PASS', limited_report)
        boundary = Fraction(limited_report['frame_limit_end_seconds'])
        self.assertEqual(audio_packets(limited), [row for row in original if row[1] < boundary])
        self.assertEqual(limited_report['audio_limit_policy'], 'complete_packets_starting_before_last_frame_end')

    def test_nonzero_video_start_normalizes_pts(self):
        self.source = self.folder / 'offset.mkv'
        make_video(self.source, pts=(120, 160, 240))
        output, report = self.process('normalized.mkv', auto=False, selected_frames=())
        self.assertEqual(report['status'], 'PASS', report)
        self.assertEqual(report['source_start_pts'], 120)
        trace = [json.loads(line) for line in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['pts'] for row in trace], [0, 40, 120])

    def test_audio_preroll_does_not_shift_normalized_video_pts(self):
        self.source = self.folder / 'preroll.mkv'
        make_video(self.source, pts=(120, 160, 240), audio=True)
        original = audio_packets(self.source)
        output, report = self.process('preroll_result.mkv', auto=False, selected_frames=())
        self.assertEqual(report['status'], 'PASS', report)
        with av.open(str(output)) as result:
            self.assertEqual([frame.pts * frame.time_base for frame in result.decode(video=0)],
                             [Fraction(value, 1000) for value in (0, 40, 120)])
        self.assertEqual(audio_packets(output), [(data, pts-Fraction(120, 1000), dts-Fraction(120, 1000))
                                                 for data, pts, dts in original])

    def test_cancelled_and_bad_media_leave_report_without_partial_video(self):
        event = threading.Event()
        event.set()
        output, report = self.process('cancelled.mkv', cancel=event)
        self.assertEqual(report['status'], 'CANCELLED')
        self.assertFalse(output.exists())
        self.assertFalse(list(self.folder.glob('*.part*')))
        self.assertTrue(Path(str(output)+'.json').exists())
        self.source = self.folder / 'bad.mkv'
        self.source.write_bytes(b'not a video')
        output, report = self.process('bad_result.mkv')
        self.assertEqual(report['status'], 'FAIL')
        self.assertTrue(report['error'])
        self.assertFalse(output.exists())

    def test_cancellation_during_progress_removes_partial_video(self):
        event = threading.Event()
        def notify(kind, data):
            if kind == 'progress':
                event.set()
        output, report = self.process('during_cancel.mkv', cancel=event, notify=notify, selected_frames=())
        self.assertEqual(report['status'], 'CANCELLED', report)
        self.assertEqual(report['frames'], 1)
        self.assertFalse(output.exists())
        self.assertFalse(list(self.folder.glob('*.part*')))

    def test_letterbox_roi_limits_enhancement_to_content(self):
        output = self.folder / 'letterbox.mkv'
        report = offline.process(self.source, output, width=80, height=80, auto=False)
        self.assertEqual(report['status'], 'PASS', report)
        row = json.loads(Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()[0])
        params = row['parameters']
        self.assertEqual((params['roi_enable'], params['roi_y'], params['roi_height']), (1, 10, 60))
        raw = np.frombuffer((self.folder / 'letterbox_frames/0000_cpu_reference.yuyv').read_bytes(), np.uint8).reshape(80, 80, 2)
        self.assertTrue(np.all(raw[:10, :, 0] == 0))
        self.assertTrue(np.all(raw[70:, :, 0] == 0))

    def test_invalid_arguments_and_existing_diagnostics_are_protected(self):
        with self.assertRaises(ValueError):
            self.process(max_frames=0)
        with self.assertRaises(ValueError):
            offline.process(self.source, self.folder/'odd.mp4', width=63, height=48)
        with self.assertRaises(ValueError):
            offline.process(self.source, self.folder/'odd_height.mp4', width=64, height=47)
        with self.assertRaises(ValueError):
            offline.process(self.source, self.source)
        trace = self.folder/'protected.mkv.frames.jsonl'
        trace.write_text('keep', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.process('protected.mkv')
        self.assertEqual(trace.read_text(encoding='utf-8'), 'keep')

    def test_missing_negative_or_duplicate_pts_are_rejected(self):
        for value, previous in ((None, None), (-1, None), (40, 40)):
            with self.assertRaises(ValueError):
                offline._timestamp(SimpleNamespace(pts=value, time_base=Fraction(1, 1000)),
                                   Fraction(1, 1000), 0, previous)


if __name__ == '__main__':
    unittest.main()
