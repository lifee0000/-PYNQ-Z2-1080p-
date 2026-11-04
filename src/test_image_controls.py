from dataclasses import asdict, replace
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

from image_controls import (ImageControls, LiveImageControls, apply_controls,
                            available_controls, load_profile, save_profile)
from reference import Params, enhance


class ImageControlTests(unittest.TestCase):
    def test_automatic_is_exactly_unchanged_for_all_modes(self):
        for mode in range(6):
            p = asdict(Params(mode=mode, brightness=-8, chroma_q8=256, clarity=135792160))
            result = apply_controls(p, ImageControls(), automatic=True)
            self.assertEqual(result, p)
            self.assertIsNot(result, p)

    def test_presets_are_ordered_without_changing_exposure_or_transport(self):
        original = asdict(Params(mode=5, sharp_q8_8=512, gain_q8_8=384,
                                 overshoot=1, clarity=135792160, chroma_q8=256))
        values = [apply_controls(original, ImageControls(preset=p))
                  for p in ('natural', 'balanced', 'enhanced')]
        self.assertEqual([p['gain_q8_8'] for p in values], [384] * 3)
        self.assertEqual([p['chroma_q8'] for p in values], [256] * 3)
        self.assertEqual([p['clarity'] & 255 for p in values], [0, 16, 32])
        self.assertLess(values[0]['sharp_q8_8'], values[1]['sharp_q8_8'])
        self.assertLess(values[1]['sharp_q8_8'], values[2]['sharp_q8_8'])
        self.assertEqual(original['clarity'], 135792160)

    def test_manual_overrides_survive_different_auto_decisions(self):
        settings = ImageControls(preset='natural', brightness=12, denoise=50,
                                 sharpen=75, clarity=30, color_preservation=80)
        for gain in (256, 384, 512):
            source = asdict(Params(mode=5, gain_q8_8=gain, brightness=-7,
                                   noise_floor=9, sharp_q8_8=900, clarity=135792160))
            p = apply_controls(source, settings, automatic=True)
            Params(**p).validate(64, 48)
            self.assertEqual((p['brightness'], p['noise_floor'], p['sharp_q8_8'], p['chroma_q8']), (5, 6, 768, 205))
            self.assertEqual(p['clarity'] & 255, 14)
            self.assertEqual(p['gain_q8_8'], gain)

    def test_presets_keep_auto_clarity_protection_but_manual_can_override(self):
        original = asdict(Params(mode=5, clarity=0, overshoot=1))
        for name in ('natural', 'balanced', 'enhanced'):
            self.assertEqual(apply_controls(original, ImageControls(preset=name), automatic=True)['clarity'], 0)
        explicit = apply_controls(original, ImageControls(preset='enhanced', clarity=60), automatic=True)
        self.assertGreater(explicit['clarity'] & 255, 0)
        self.assertGreater(apply_controls(original, ImageControls(preset='enhanced'))['clarity'] & 255, 0)

    def test_only_auto_may_change_mode_for_mode5_controls(self):
        source = asdict(Params(mode=4, overshoot=1))
        settings = ImageControls(brightness=10, denoise=0, color_preservation=0)
        auto = apply_controls(source, settings, automatic=True)
        fixed = apply_controls(source, settings)
        self.assertEqual((auto['mode'], auto['brightness'], auto['filter_enable']), (5, 10, 0))
        self.assertEqual(fixed, source)
        self.assertEqual(available_controls(4), {'sharpen', 'clarity'})
        self.assertFalse(available_controls(0))

    def test_auto_mode_promotion_keeps_integrated_denoise_and_halo_guards(self):
        source = asdict(Params(mode=4, noise_floor=1, noise_floor_uv=0,
                               sharp_q8_8=960, overshoot=1, chroma_q8=0))
        p = apply_controls(source, ImageControls(brightness=8), automatic=True)
        self.assertEqual((p['mode'], p['noise_floor'], p['noise_floor_uv'], p['filter_enable']), (5, 2, 2, 1))
        self.assertEqual((p['sharp_q8_8'], p['overshoot'], p['chroma_q8']), (512, 1, 256))
        explicit = apply_controls(source, ImageControls(denoise=0, sharpen=100), automatic=True)
        self.assertEqual((explicit['filter_enable'], explicit['sharp_q8_8']), (0, 1024))

    def test_each_supported_knob_changes_reference_pixels(self):
        # Real pixel effects on a multi-scale pattern, rather than testing just
        # register assignments. Sharpening and clarity produce different images.
        y, x = np.indices((48, 64))
        a = np.full((48, 64, 2), 128, np.uint8)
        a[:, :, 0] = (75 + 18*np.sin(x/3) + 10*np.sin(y/9) + 2*(x % 2)).astype(np.uint8)
        a[:, 0::2, 1] = 150
        a[:, 1::2, 1] = 140
        a[20, 20, 0] = 190  # Isolated impulse for denoise.
        p = asdict(Params(mode=5, gain_q8_8=320, knee_out=255, soft_q8_8=256,
                          overshoot=1, sharp_q8_8=0, noise_floor=0, noise_floor_uv=0, filter_enable=0))
        base = enhance(a.tobytes(), 64, 48, Params(**p))
        outputs = []
        for name, value in (('brightness', 10), ('denoise', 100), ('sharpen', 75),
                            ('clarity', 50), ('color_preservation', 100)):
            settings = ImageControls(**{name: value})
            result = enhance(a.tobytes(), 64, 48, Params(**apply_controls(p, settings)))
            self.assertNotEqual(result, base, name)
            outputs.append(result)
        self.assertNotEqual(outputs[2], outputs[3])
        # Colour correction does not change the luma bytes.
        self.assertEqual(outputs[4][::2], base[::2])

    def test_live_snapshots_remain_immutable_after_edit_and_reset(self):
        live = LiveImageControls(ImageControls(sharpen=70))
        frame1 = live.snapshot()
        live.update(ImageControls(clarity=20))
        frame2 = live.snapshot()
        live.update(ImageControls())
        self.assertEqual(frame1.sharpen, 70)
        self.assertEqual(frame2.clarity, 20)
        self.assertEqual(live.snapshot(), ImageControls())

    def test_extremes_validate_without_touching_roi_or_exposure_policy(self):
        original = asdict(Params(roi_enable=1, roi_x=2, roi_y=2, roi_width=60, roi_height=40))
        for mode in range(6):
            for value in (0, 100):
                p = apply_controls(dict(original, mode=mode), ImageControls(
                    brightness=-32 if value == 0 else 32, denoise=value,
                    sharpen=value, clarity=value, color_preservation=value))
                Params(**p).validate(64, 48)
                self.assertEqual([p[n] for n in ('roi_x', 'roi_y', 'roi_width', 'roi_height')], [2, 2, 60, 40])


class ProfileTests(unittest.TestCase):
    def test_roundtrip_and_failed_atomic_save_preserve_last_good_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / '自定义画质.json'
            settings = ImageControls(preset='balanced', brightness=-10, sharpen=65, clarity=0)
            save_profile(path, settings)
            self.assertEqual(load_profile(path), settings)
            with patch('image_controls.os.replace', side_effect=OSError('disk unavailable')):
                with self.assertRaises(OSError):
                    save_profile(path, ImageControls())
            self.assertEqual(load_profile(path), settings)
            self.assertEqual(list(Path(folder).iterdir()), [path])
            self.assertNotIn('password', path.read_text(encoding='utf-8'))

    def test_reject_bad_schema_types_unknown_fields_and_oversized_profiles(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'bad.json'
            for data in ({'schema': True, 'image_controls': {}},
                         {'schema': 2, 'image_controls': {}},
                         {'schema': 1, 'image_controls': {'denoise': True}},
                         {'schema': 1, 'image_controls': {'clarity': 101}},
                         {'schema': 1, 'image_controls': {'sharpen': 1.5}},
                         {'schema': 1, 'image_controls': {'preset': []}},
                         {'schema': 1, 'image_controls': {'gain_q8_8': 500}},
                         {'schema': 1, 'image_controls': {}, 'password': 'ignored?'}):
                path.write_text(json.dumps(data), encoding='utf-8')
                with self.assertRaises(ValueError, msg=str(data)):
                    load_profile(path)
            path.write_text(' ' * 16385, encoding='utf-8')
            with self.assertRaises(ValueError):
                load_profile(path)


if __name__ == '__main__':
    unittest.main()
