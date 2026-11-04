"""Parameter-curve back end: measurements, overrides, ROI words; offline processing honours a plan."""
from pathlib import Path
import json, tempfile, unittest, unittest.mock
import av
import numpy as np
import signal_curves as sc
from reference import Params


class MeasureTest(unittest.TestCase):
    def test_flat_noise_detail_and_blocking(self):
        rng = np.random.default_rng(3)
        flat = np.full((64, 64, 3), 100, np.uint8)
        noisy = np.clip(100 + rng.normal(0, 4, (64, 64, 1)), 0, 255).repeat(3, 2).astype(np.uint8)
        a, b = sc.measure(flat), sc.measure(noisy)
        self.assertAlmostEqual(a['brightness'], 100, places=3); self.assertEqual(a['noise'], 0)
        self.assertAlmostEqual(b['noise'], 4, delta=.6); self.assertGreater(b['detail'], a['detail'])
        blocks = np.kron(rng.integers(60, 140, (8, 8)), np.ones((8, 8)))[..., None].repeat(3, 2).astype(np.uint8)
        self.assertGreater(sc.measure(blocks + rng.integers(0, 2, blocks.shape).astype(np.uint8))['blocking'], 3)

    def test_region_is_measured_alone_and_scaled_onto_the_source(self):
        frame = np.zeros((40, 80, 3), np.uint8); frame[10:30, 40:80] = 200
        self.assertAlmostEqual(sc.measure(frame, (40, 10, 40, 20))['brightness'], 200, places=3)
        self.assertEqual(sc.scale_region((960, 540, 960, 540), (1920, 1080), (1280, 720)), (640, 360, 640, 360))


def write_video(path, frames, rate=25):
    with av.open(str(path), 'w') as out:
        s = out.add_stream('ffv1', rate=rate); s.width, s.height, s.pix_fmt = frames[0].shape[1], frames[0].shape[0], 'bgr0'
        for i, rgb in enumerate(frames):
            f = av.VideoFrame.from_ndarray(rgb, format='rgb24'); f.pts = i
            for p in s.encode(f): out.mux(p)
        for p in s.encode(None): out.mux(p)


class GeometryTest(unittest.TestCase):
    """Review F3/F4: identity exports (letterboxed portrait, 2x upscale) must measure the same on both sides."""

    def exported(self, folder, source_frames, size):
        from media_frame import fit_rgb
        source, export = Path(folder) / 'in.mkv', Path(folder) / 'out.mkv'
        write_video(source, source_frames)
        with av.open(str(source)) as video:
            write_video(export, [fit_rgb(f, *size)[0] for f in video.decode(video=0)])
        return source, export

    def finished(self, analysis):
        analysis.thread.join(30); self.assertIsNone(analysis.error); return analysis

    def test_content_rect_matches_the_exporters_letterbox(self):
        self.assertEqual(sc.content_rect((544, 960), (1920, 1080)), (654, 0, 612, 1080))
        self.assertEqual(sc.content_rect((1280, 720), (1920, 1080)), (0, 0, 1920, 1080))
        self.assertEqual(sc.content_rect((64, 96), (192, 108)), (60, 0, 72, 108))
        self.assertEqual(sc.export_to_source((72, 18, 24, 60), (60, 0, 72, 108), (64, 96)), (11, 16, 21, 53))
        self.assertIsNone(sc.clip_region((0, 0, 50, 50), (60, 0, 72, 108)))

    def test_portrait_letterbox_region_measures_the_same_scene_on_both_sides(self):
        rng = np.random.default_rng(5)
        frames = [np.clip(rng.normal(90 + 10 * i, 20, (96, 64, 3)), 0, 255).astype(np.uint8) for i in range(3)]
        with tempfile.TemporaryDirectory() as folder:
            source, export = self.exported(folder, frames, (192, 108))
            for region in ((72, 18, 24, 60), None):
                a = self.finished(sc.CurveAnalysis(source, export, region))
                for key in ('brightness', 'noise', 'detail'):
                    np.testing.assert_allclose(a.input[key], a.output[key], rtol=1e-6, err_msg=f'{region} {key}')
            with self.assertRaises(ValueError):   # a box on the black padding only
                a = sc.CurveAnalysis(source, export, (0, 0, 40, 40)); a.thread.join(30); raise a.error

    def test_upscaled_source_is_measured_on_the_export_grid(self):
        rng = np.random.default_rng(6)
        frames = [np.clip(rng.normal(120, 25, (90, 160, 3)), 0, 255).astype(np.uint8) for _ in range(2)]
        with tempfile.TemporaryDirectory() as folder:
            source, export = self.exported(folder, frames, (320, 180))
            a = self.finished(sc.CurveAnalysis(source, export))
            for key in ('noise', 'detail', 'brightness'):
                np.testing.assert_allclose(a.input[key], a.output[key], rtol=1e-6, err_msg=key)


class CurvesTest(unittest.TestCase):
    words = dict(Params(mode=5, gain_q8_8=384, brightness=4, noise_floor=4, sharp_q8_8=512, chroma_q8=200,
                        clarity=32 | 8 << 8 | 24 << 16 | 8 << 24).__dict__)

    def test_overrides_only_where_a_curve_has_a_value_and_are_clamped(self):
        curves = dict(denoise=[None, 2, 99], gain=[1.25, None, None], clarity=[0, None, .5])
        self.assertEqual(sc.apply_curves(self.words, 0, curves)['gain_q8_8'], 320)
        self.assertEqual(sc.apply_curves(self.words, 0, curves)['clarity'] & 255, 0)
        self.assertEqual(sc.apply_curves(self.words, 1, curves)['noise_floor'], 2)
        self.assertEqual(sc.apply_curves(self.words, 2, curves)['noise_floor'], 12)       # clamped to the editor range
        self.assertEqual(sc.apply_curves(self.words, 2, curves)['clarity'] & 255, 32)
        self.assertEqual(sc.apply_curves(self.words, 5, curves), self.words)              # past the curve: automatic
        for i in range(3):
            Params(**sc.apply_curves(self.words, i, curves)).validate(1920, 1080)
        self.assertAlmostEqual(sc.control_values([self.words], 'gain')[0], 1.5)

    def test_roi_words_are_even_and_inside_the_frame_and_the_letterbox(self):
        words = sc.roi_words((1901, 5, 300, 2000), (1920, 1080))
        self.assertEqual((words['roi_x'] % 2, words['roi_width'] % 2), (0, 0))
        self.assertLessEqual(words['roi_x'] + words['roi_width'], 1920); self.assertLessEqual(words['roi_y'] + words['roi_height'], 1080)
        Params(mode=5, **words).validate(1920, 1080)
        inside = sc.plan_roi((0, 0, 1920, 1080), (1920, 1080), (1920, 1080), letterbox=(240, 0, 1440, 1080))
        self.assertEqual((inside['roi_x'], inside['roi_width']), (240, 1440))
        with self.assertRaises(ValueError): sc.plan_roi((0, 0, 100, 100), (1920, 1080), (1920, 1080), letterbox=(240, 0, 1440, 1080))


class SpeedTest(unittest.TestCase):
    """The faster measurement (separable mask, strided grid, pooled frames, cache) gives the same numbers."""

    def reference(self, rgb, x0=0):
        y = rgb.astype(np.float64) @ np.array([.2126, .7152, .0722])
        lap = 4 * y[1:-1, 1:-1] - y[:-2, 1:-1] - y[2:, 1:-1] - y[1:-1, :-2] - y[1:-1, 2:]
        m = (y[:-2, :-2] - 2 * y[:-2, 1:-1] + y[:-2, 2:] - 2 * y[1:-1, :-2] + 4 * y[1:-1, 1:-1] - 2 * y[1:-1, 2:]
             + y[2:, :-2] - 2 * y[2:, 1:-1] + y[2:, 2:])
        dx = np.abs(np.diff(y, axis=1)); grid = (np.arange(x0, x0 + y.shape[1] - 1) % 8) == 7
        return dict(brightness=y.mean(), detail=np.abs(lap).mean(), noise=np.sqrt(np.pi / 2) * np.abs(m).mean() / 6,
                    blocking=dx[:, grid].mean() / dx[:, ~grid].mean())

    def test_measure_matches_the_nine_term_definition(self):
        rgb = np.random.default_rng(9).integers(0, 256, (90, 160, 3), dtype=np.uint8)
        for region in (None, (13, 7, 101, 51)):
            got = sc.measure(rgb, region)
            x, y, w, h = region or (0, 0, 160, 90)
            want = self.reference(rgb[y:y + h, x:x + w], x)
            for key in want: self.assertAlmostEqual(got[key], want[key], delta=1e-4 * max(1, abs(want[key])), msg=(region, key))

    def test_stripes_give_the_same_numbers_across_stripe_boundaries(self):
        rgb = np.random.default_rng(11).integers(0, 256, (61, 97, 3), dtype=np.uint8)
        with unittest.mock.patch.object(sc, 'STRIPE_ROWS', 7):          # many stripes, odd sizes
            for region in (None, (5, 3, 80, 50), (1, 1, 20, 3)):
                got = sc.measure(rgb, region)
                x, y, w, h = region or (0, 0, 97, 61)
                want = self.reference(rgb[y:y + h, x:x + w], x)
                for key in want: self.assertAlmostEqual(got[key], want[key], delta=1e-4 * max(1, abs(want[key])), msg=(region, key))

    def test_background_analysis_runs_two_at_low_priority_until_boosted(self):
        frames = [np.full((36, 64, 3), 40 + 20 * i, np.uint8) for i in range(4)]
        with tempfile.TemporaryDirectory() as folder:
            source, export = Path(folder) / 'in.mkv', Path(folder) / 'out.mkv'
            write_video(source, frames); write_video(export, frames)
            a = sc.CurveAnalysis.shared(source, export, 4, background=True)
            self.assertEqual((a.parallel, a.low_priority), (sc.BACKGROUND_WORKERS, True))
            self.assertIs(sc.CurveAnalysis.shared(source, export, 4), a)   # the curve window asks: same analysis, full speed
            self.assertEqual((a.parallel, a.low_priority), (sc.WORKERS, False))
            a.thread.join(30); self.assertEqual(a.frames, [0, 1, 2, 3])

    def test_whole_frame_analysis_is_cached_until_a_file_changes(self):
        rng = np.random.default_rng(10)
        frames = [rng.integers(0, 256, (72, 128, 3), dtype=np.uint8) for _ in range(5)]
        with tempfile.TemporaryDirectory() as folder:
            source, export = Path(folder) / 'in.mkv', Path(folder) / 'out.mkv'
            write_video(source, frames); write_video(export, frames)
            first = sc.CurveAnalysis(source, export); first.thread.join(30)
            self.assertFalse(first.cached); self.assertTrue((Path(folder) / 'out.mkv.measure.json').is_file())
            again = sc.CurveAnalysis(source, export); again.thread.join(30)
            self.assertTrue(again.cached); self.assertEqual((again.frames, again.input, again.output), (first.frames, first.input, first.output))
            region = sc.CurveAnalysis(source, export, (0, 0, 64, 36)); region.thread.join(30)
            self.assertFalse(region.cached)                       # regions are never cached
            write_video(export, frames[::-1])                     # a changed export is measured again
            changed = sc.CurveAnalysis(source, export); changed.thread.join(30)
            self.assertFalse(changed.cached); self.assertNotEqual(changed.output['brightness'], first.output['brightness'])

    def test_shared_analysis_is_reused_by_the_window(self):
        frames = [np.full((36, 64, 3), 50 + 10 * i, np.uint8) for i in range(3)]
        with tempfile.TemporaryDirectory() as folder:
            source, export = Path(folder) / 'in.mkv', Path(folder) / 'out.mkv'
            write_video(source, frames); write_video(export, frames)
            a = sc.CurveAnalysis.shared(source, export, 3); b = sc.CurveAnalysis.shared(source, export, 3)
            self.assertIs(a, b); a.thread.join(30)
            self.assertEqual(a.frames, [0, 1, 2]); self.assertEqual(sc.default_stride(601), 2)


class OfflinePlanTest(unittest.TestCase):
    def test_offline_run_records_overridden_words_and_the_roi(self):
        from offline_video import process
        with tempfile.TemporaryDirectory() as folder:
            source, output = Path(folder) / 'in.mkv', Path(folder) / 'out.mp4'
            with av.open(str(source), 'w') as out:
                s = out.add_stream('ffv1', rate=25); s.width, s.height, s.pix_fmt = 320, 180, 'bgr0'
                for i in range(3):
                    f = av.VideoFrame.from_ndarray(np.full((180, 320, 3), 40 + 20 * i, np.uint8), format='rgb24'); f.pts = i
                    for p in s.encode(f): out.mux(p)
                for p in s.encode(None): out.mux(p)
            report = process(source, output, mode=5, auto=True, auto_policy='v5', width=1280, height=720,
                             parameter_curves=dict(denoise=[7, None, 1]), curve_region=(640, 0, 320, 360))
            self.assertEqual(report['status'], 'PASS')
            rows = [json.loads(l) for l in Path(str(output) + '.frames.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([r['parameters']['noise_floor'] for r in (rows[0], rows[2])], [7, 1])
            self.assertTrue(all(r['parameters']['roi_enable'] == 1 and r['parameters']['roi_x'] == 640 and r['parameters']['roi_width'] == 320 for r in rows))


if __name__ == '__main__':
    unittest.main()
