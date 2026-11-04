import unittest
from dataclasses import fields
import numpy as np
import auto_v5
from auto_v5 import AutoOptimizerV5, contrast_stretch, detail_profile
from exposure_v4 import analyze_yuyv_v4
from reference import Params
from run_video import preview_rgb
from pixels import unpack_rgb

W, H = 640, 360
NAMES = {f.name for f in fields(Params)}


def frame(y, c=None):
    raw = np.empty((H, W, 2), np.uint8)
    raw[:, :, 0] = np.clip(y, 0, 255)
    raw[:, :, 1] = 128 if c is None else c
    return raw.tobytes()


def texture(blur=0, seed=3):
    # Pixel-scale texture on a mid-grey base: the detail ratio is above 256.
    y = 128+np.random.default_rng(seed).integers(-40, 41, (H, W)).astype(np.float64)
    for _ in range(blur):
        y = (np.roll(y, 1, 1)+2*y+np.roll(y, -1, 1))/4
        y = (np.roll(y, 1, 0)+2*y+np.roll(y, -1, 0))/4
    return y


def blocks(seed=4):
    # Normally exposed, wide-range, noise-free piecewise-constant scene: 5% dark
    # blocks (below the V4 shadow-region share), the rest bright.
    rng = np.random.default_rng(seed)
    levels = rng.integers(100, 236, (H//8+1, W//8+1))
    dark = rng.random(levels.shape) < .05
    levels[dark] = rng.integers(20, 36, int(dark.sum()))
    return np.kron(levels, np.ones((8, 8)))[:H, :W]


def stats_of(payload):
    return analyze_yuyv_v4(payload, W, H)


def valid(params):
    Params(**{k: v for k, v in params.items() if k in NAMES}).validate(W, H)


class DetailProfileTests(unittest.TestCase):
    def test_acutance_falls_with_blur(self):
        values = [detail_profile(frame(texture(b)), W, H)['acutance_q8'] for b in (0, 1, 3)]
        self.assertGreater(values[0], values[1]); self.assertGreater(values[1], values[2])
        self.assertGreater(detail_profile(frame(texture(0)), W, H)['acutance_q8'], 256)

    def test_flat_frame_has_no_vote(self):
        self.assertIsNone(detail_profile(frame(np.full((H, W), 120)), W, H)['acutance_q8'])


class StretchTests(unittest.TestCase):
    def test_narrow_range_is_stretched_within_guards(self):
        y = 90+np.indices((H, W))[1]*90//W
        result = contrast_stretch(stats_of(frame(y))[0])
        self.assertIsNotNone(result)
        self.assertGreater(result['gain_q8_8'], 256); self.assertLessEqual(result['gain_q8_8'], auto_v5.MAX_STRETCH_GAIN_Q8)
        self.assertLessEqual(result['predicted_clip_permille'], 3); self.assertLessEqual(result['predicted_crush_permille'], 3)

    def test_full_range_is_left_alone(self):
        y = np.indices((H, W))[1]*255//(W-1)
        self.assertIsNone(contrast_stretch(stats_of(frame(y))[0]))


class OptimizerTests(unittest.TestCase):
    def run_one(self, payload, pts=0, optimizer=None, upscale=256):
        optimizer = optimizer or AutoOptimizerV5()
        stats, noise = stats_of(payload)
        params, record = optimizer.update(pts, stats, noise, detail_profile(payload, W, H, None, noise.get('sigma_q8')), upscale)
        valid(params)
        return params, record, optimizer

    def test_clean_normal_scene_uses_unsharp_mask(self):
        params, record, _ = self.run_one(frame(blocks()))
        self.assertEqual(params['mode'], 4); self.assertEqual(params['filter_enable'], 1)
        self.assertTrue(auto_v5.USM_MIN_Q8 <= params['sharp_q8_8'] <= auto_v5.USM_MAX_Q8)
        self.assertEqual(record['policy'], auto_v5.AUTO_POLICY_V5)

    def test_upscale_prior_raises_gain(self):
        stats, noise = stats_of(frame(blocks()))
        detail = dict(acutance_q8=300, softness_q8=85, edge_samples=10000, gate=12)
        a, _ = AutoOptimizerV5().update(0, stats, noise, detail, 256)
        b, _ = AutoOptimizerV5().update(0, stats, noise, detail, 384)
        self.assertEqual((a['mode'], b['mode']), (4, 4))
        self.assertGreater(b['sharp_q8_8'], a['sharp_q8_8'])

    def test_upscaled_source_gets_visible_sharpening(self):
        # 1.5x upscale: cap 768 and gate 2; a native frame stays within the original 448 cap.
        stats, noise = stats_of(frame(blocks()))
        detail = dict(acutance_q8=296, softness_q8=102, edge_samples=10000, gate=12)
        native, _ = AutoOptimizerV5().update(0, stats, noise, detail, 256)
        upscaled, _ = AutoOptimizerV5().update(0, stats, noise, detail, 384)
        self.assertEqual((native['mode'], upscaled['mode']), (4, 4))
        self.assertLessEqual(native['sharp_q8_8'], auto_v5.USM_MAX_Q8); self.assertEqual(native['noise_floor'], auto_v5.USM_GATE)
        self.assertGreaterEqual(upscaled['sharp_q8_8'], auto_v5.STRONG_USM_Q8)
        self.assertLessEqual(upscaled['sharp_q8_8'], auto_v5.USM_MAX_UPSCALED_Q8)
        self.assertEqual(upscaled['noise_floor'], auto_v5.STRONG_USM_GATE)
        self.assertEqual((native['detail_limit'], upscaled['detail_limit']), (auto_v5.USM_DETAIL_LIMIT, auto_v5.STRONG_USM_DETAIL_LIMIT))
        # Enhance IP 1.1: halos are capped, so the gains are 1.25x the earlier ones.
        self.assertEqual((native['overshoot'], upscaled['overshoot']), (1, 1))
        self.assertEqual((auto_v5.USM_MIN_Q8, auto_v5.USM_MAX_Q8, auto_v5.USM_MAX_UPSCALED_Q8), (400, 560, 960))

    def test_dark_noise_is_measured_in_shadows(self):
        rng = np.random.default_rng(11)
        dark = np.full((H, W), 20.0)  # flat shadow
        clean = auto_v5.dark_noise(np.clip(dark, 0, 255).astype(np.uint8))
        noisy = auto_v5.dark_noise(np.clip(dark+rng.normal(0, 2, (H, W)), 0, 255).round().astype(np.uint8))
        self.assertLess(clean['dark_sigma_q8'], 64)
        self.assertAlmostEqual(noisy['dark_sigma_q8']/256, 2.0, delta=0.35)
        bright = auto_v5.dark_noise(np.full((H, W), 180, np.uint8))
        self.assertIsNone(bright['dark_sigma_q8'])
        self.assertLess(noisy['dark_texture_q8'], 26)              # grain is not texture
        streaks = np.where((np.indices((H, W))[1]//3) % 2, 40, 10).astype(np.uint8)
        self.assertGreater(auto_v5.dark_noise(streaks)['dark_texture_q8'], 128)

    def lifted(self, gain, dark_sigma_q8, dark_texture_q8=0):
        payload = frame(blocks())
        stats, noise = stats_of(payload)
        opt = AutoOptimizerV5()
        lift = dict(Params().__dict__, mode=5, gain_q8_8=gain, knee_out=80, soft_q8_8=150, filter_enable=0, noise_floor=0, noise_floor_uv=0)
        record = dict(scene_reset=True, reason=dict(decision='global-underexposure'), effective_noise={'sigma_q8': 300}, policy='v4')
        opt.v4.update = lambda *args: (dict(lift), dict(record))
        detail = dict(acutance_q8=None, softness_q8=0, edge_samples=0, gate=12, dark_sigma_q8=dark_sigma_q8, dark_share_q8=200, dark_texture_q8=dark_texture_q8)
        return opt.update(0, stats, noise, detail, 256)

    def test_lift_turns_on_shadow_denoise(self):
        params, record = self.lifted(372, 128)       # 1.45x lift, 0.5 level of shadow grain
        self.assertEqual(params['mode'], 5); self.assertEqual(params['filter_enable'], 1)
        self.assertEqual(params['noise_floor_uv'], 3); self.assertEqual(record['v5']['lift_denoise'], 3)
        self.assertEqual(params['noise_floor'], 4)   # mode-5 minimum for a >= 1.44x lift
        params, _ = self.lifted(372, 1024)           # clamps at 6 / UV 4
        self.assertEqual((params['noise_floor'], params['noise_floor_uv']), (6, 4))

    def test_mode5_gets_cored_5x5_sharpening(self):
        # Enhance IP 1.2: mode 5 sharpens (gain 2x, 1.5x from noise floor 3), halo-clamped.
        grainy, _ = self.lifted(372, 128)            # lift denoise sets noise floor 3
        clean, _ = self.lifted(256, None)            # no lift, no denoise
        self.assertEqual((grainy['mode'], clean['mode']), (5, 5))
        self.assertEqual((grainy['sharp_q8_8'], clean['sharp_q8_8']), (auto_v5.MODE5_USM_GRAINY_Q8, auto_v5.MODE5_USM_Q8))
        self.assertEqual((grainy['detail_limit'], clean['detail_limit']), (24, 24))
        self.assertEqual((grainy['overshoot'], clean['overshoot']), (1, 1))

    def test_mode5_never_sharpens_undenoised_grain(self):
        # Floor 0 or a disabled filter under mode-5 sharpening amplified grain 1.6x (rain, camera, Tokyo).
        for gain, floor in ((256, 2), (319, 2), (320, 3), (367, 3), (368, 4), (384, 4), (415, 4), (416, 5), (440, 5)):
            params, record = self.lifted(gain, None)
            self.assertEqual((params['filter_enable'], params['noise_floor'], record['v5']['mode5_floor']), (1, floor, floor), gain)
            self.assertEqual(params['sharp_q8_8'], auto_v5.MODE5_USM_Q8)   # the minimum does not mark it grainy

    def test_lift_keeps_highlight_contrast(self):
        # V4 knee 208 / soft 68 at 1.5x squeezed highlights to 0.4x; the shoulder now keeps >= 0.75x.
        self.assertEqual(auto_v5.highlight_knee(384, 208, 68), (112, 135))
        self.assertEqual(auto_v5.highlight_knee(310, 176, 152), (144, 172))
        self.assertEqual(auto_v5.highlight_knee(302, 48, 209), (48, 209))      # already gentle
        self.assertEqual(auto_v5.highlight_knee(256, 224, 256), (224, 256))                # no lift
        for gain in range(257, 385):
            for knee in auto_v5.KNEES:
                white = (gain*255+128) >> 8; soft = min(256, max(1, ((255-knee)*256)//max(1, white-knee)))
                k, s = auto_v5.highlight_knee(gain, knee, soft)
                y = np.arange(256); m = (gain*y+128) >> 8
                old = np.clip(np.where(m > knee, knee+((m-knee)*soft)//256, m), 0, 255)
                new = np.clip(np.where(m > k, k+((m-k)*s)//256, m), 0, 255)
                self.assertTrue(k <= knee and np.all(new <= old) and np.all(new >= y-2) and new[-1] >= 253, (gain, knee))
        lift = self.lifted(384, None)[0]
        self.assertGreaterEqual(lift['gain_q8_8']*lift['soft_q8_8'], auto_v5.HIGHLIGHT_MIN_SLOPE_Q8*256)

    def night(self, seed=5):
        # Underexposed, noise-free scene: dark blocks (median ~20) and a few lamps.
        rng = np.random.default_rng(seed)
        levels = rng.integers(8, 40, (H//8+1, W//8+1))
        levels[rng.random(levels.shape) < .03] = 200
        return frame(np.kron(levels, np.ones((8, 8)))[:H, :W])

    def test_low_light_boost_follows_shadow_grain(self):
        stats = stats_of(self.night())[0]
        clean = auto_v5.low_light_curve(stats, 384, 64)            # 0.25 level of shadow grain
        self.assertEqual(clean['boost_gain_q8_8'], auto_v5.LOW_LIGHT_MAX_Q8)
        # v5.3: V4's slope plus a black offset, not more slope (block mottle scales with the slope).
        self.assertEqual(clean['gain_q8_8'], auto_v5.LOW_LIGHT_V4_Q8)
        self.assertTrue(1 <= clean['brightness'] <= auto_v5.LOW_LIGHT_MAX_OFFSET)
        self.assertLessEqual(clean['knee_out'], auto_v5.LOW_LIGHT_MAX_KNEE)
        y = np.arange(256); m = ((clean['gain_q8_8']*y+128) >> 8)+clean['brightness']
        curve = np.clip(np.where(m > clean['knee_out'], clean['knee_out']+((m-clean['knee_out'])*clean['soft_q8_8'])//256, m), 0, 255)
        self.assertEqual(curve[0], clean['brightness']); self.assertTrue(253 <= curve[-1] <= 255); self.assertTrue(np.all(np.diff(curve) >= 0))
        # The median lands where the boosted gain would put it (unless the offset cap binds).
        level = max(auto_v5.LOW_LIGHT_MIN_LEVEL, int(stats['quantiles']['p50']))
        boosted = (clean['boost_gain_q8_8']*level+128) >> 8
        self.assertLessEqual(boosted-curve[level], 1 if clean['brightness'] < auto_v5.LOW_LIGHT_MAX_OFFSET else 99)
        self.assertLessEqual(curve[level], boosted+1)
        half = auto_v5.low_light_curve(stats, 384, 192)            # halfway to the noisy end
        self.assertTrue(384 < half['boost_gain_q8_8'] < clean['boost_gain_q8_8'])
        self.assertLessEqual(half['brightness'], clean['brightness'])
        self.assertIsNone(auto_v5.low_light_curve(stats, 384, 256))   # rain-forest grain keeps V4's 1.5x
        self.assertIsNone(auto_v5.low_light_curve(stats, 384, None))  # unmeasured shadows
        bright = stats_of(frame(blocks()))[0]
        self.assertIsNone(auto_v5.low_light_curve(bright, 300, 64))  # median already above target

    def test_low_light_boost_in_the_optimizer(self):
        params, record, _ = self.run_one(self.night())
        boost = record['v5']['low_light']
        self.assertIsNotNone(boost); self.assertEqual(record['v5']['v4_decision'], 'global-underexposure')
        self.assertLessEqual(boost['v4_gain_q8_8'], 384); self.assertEqual(params['gain_q8_8'], boost['gain_q8_8'])
        self.assertGreater(boost['boost_gain_q8_8'], 384); self.assertLessEqual(boost['boost_gain_q8_8'], auto_v5.LOW_LIGHT_MAX_Q8)
        self.assertEqual(params['gain_q8_8'], 384); self.assertEqual(params['brightness'], boost['brightness'])
        self.assertGreater(params['brightness'], 0)
        self.assertLessEqual(params['knee_out'], auto_v5.LOW_LIGHT_MAX_KNEE)
        self.assertGreaterEqual(params['gain_q8_8']*params['soft_q8_8'], auto_v5.HIGHLIGHT_MIN_SLOPE_Q8*256)
        # v5.6: a noise-free night keeps the core's minimum floor (nothing for the lift to reveal);
        # chroma follows the slope, not the offset.
        self.assertEqual(params['noise_floor'], auto_v5.MODE5_MIN_FLOOR); self.assertFalse(record['v5']['lift_noise_visible'])
        self.assertTrue(0 < params['chroma_q8'] < auto_v5.CHROMA_Q8)
        self.assertIsNone(record['v5']['shoulder'])
        # A normally exposed frame is untouched by the boost.
        self.assertIsNone(self.run_one(frame(blocks()))[1]['v5']['low_light'])

    def grainy_night(self, seed=5, sigma=2.5):
        rng = np.random.default_rng(seed)
        levels = rng.integers(8, 40, (H//8+1, W//8+1)); levels[rng.random(levels.shape) < .03] = 200
        luma = np.kron(levels, np.ones((8, 8)))[:H, :W] + rng.normal(0, sigma, (H, W))
        return frame(np.clip(luma, 0, 255))

    def test_lift_denoise_needs_visible_shadow_noise(self):
        # v5.6: the 1.5x lift's floor steps apply when the measured shadow grain, lifted, is visible.
        params, record, _ = self.run_one(self.grainy_night())
        self.assertGreaterEqual(params['gain_q8_8'], 368); self.assertTrue(record['v5']['lift_noise_visible'])
        self.assertGreaterEqual(params['noise_floor'], 4); self.assertGreaterEqual(params['noise_floor_uv'], 3)
        clean, record, _ = self.run_one(self.night())
        self.assertEqual(clean['gain_q8_8'], params['gain_q8_8']); self.assertEqual(clean['noise_floor'], auto_v5.MODE5_MIN_FLOOR)

    def test_visible_noise_releases_only_after_a_quiet_dwell(self):
        opt = AutoOptimizerV5()
        self.assertTrue(opt._lift_noise_visible(200, 384, 0, False))           # 200*1.5 lifted: on at once
        self.assertTrue(opt._lift_noise_visible(60, 384, 1000, False))         # quiet, dwell running
        self.assertTrue(opt._lift_noise_visible(None, 384, 3500, False))       # unmeasured frame: kept
        self.assertFalse(opt._lift_noise_visible(60, 384, 4100, False))        # quiet >= 3 s: released
        self.assertFalse(opt._lift_noise_visible(100, 384, 4200, False))       # between the thresholds: kept off
        self.assertTrue(opt._lift_noise_visible(None, 384, 5000, True))        # a cut forgets it: protect

    def test_steady_night_keeps_its_curve(self):
        # v5.4: a static dark scene whose statistics jitter between analyses (two noise
        # draws of the same scene) settles on one curve: the offset stops changing,
        # the knee is the low-light maximum and the applied gain stays at the slope.
        opt = AutoOptimizerV5(); frames = [self.night(5), self.night(5)]
        rng = np.random.default_rng(9)
        # +1 level on a different 10 % of the 8x8 blocks each time: new statistics, no added grain.
        jitter = [frame(np.frombuffer(f, np.uint8).reshape(H, W, 2)[:, :, 0].astype(int)+
                        np.kron(rng.random((H//8+1, W//8+1)) < .1, np.ones((8, 8), int))[:H, :W]) for f in frames]
        applied = []
        for i, pts in enumerate(range(0, 6000, 40)):
            if i % 4 == 0:
                params, record, _ = self.run_one(jitter[(i//4) % 2], pts, opt)
            else:
                params = opt.advance(pts); valid(params)
            applied.append(params)
        late = applied[len(applied)//2:]
        self.assertEqual(len({p['brightness'] for p in late}), 1)
        self.assertEqual({p['knee_out'] for p in late}, {auto_v5.LOW_LIGHT_MAX_KNEE})
        gains = {p['gain_q8_8'] for p in late}
        self.assertEqual(len(gains), 1); self.assertGreaterEqual(min(gains), auto_v5.LOW_LIGHT_V4_Q8)
        self.assertGreater(late[0]['brightness'], 0)

    def test_offset_form_survives_a_one_level_rounding_failure(self):
        # Night clip f144: a lamp bin at luma 226 already at RGB 255 failed the offset
        # curve by one rounding level; v5.3 then sent the plain 1.72x curve, and the
        # smoothed curve alternated between the two forms.
        stats = dict(stats_of(self.night())[0])
        hist = list(stats['histogram']); peaks = list(stats['max_rgb_by_luma'])
        hist[226] = max(1, hist[226]); peaks[226] = 255
        stats.update(histogram=hist, max_rgb_by_luma=peaks)
        curve = auto_v5.low_light_curve(stats, 384, 64)
        self.assertEqual(curve['gain_q8_8'], auto_v5.LOW_LIGHT_V4_Q8); self.assertGreater(curve['brightness'], 0)
        y = np.arange(256); m = ((curve['gain_q8_8']*y+128) >> 8)+curve['brightness']
        tone = np.clip(np.where(m > curve['knee_out'], curve['knee_out']+((m-curve['knee_out'])*curve['soft_q8_8'])//256, m), 0, 255)
        self.assertLessEqual(tone[226], 226); self.assertGreaterEqual(tone[-1], 253)

    def test_brightening_scene_keeps_its_black_offset(self):
        # v5.5, mist clip frames 200-369: the median drifts 60 -> 64 -> 59 and v5.4 moved the
        # offset 6 -> 0 -> 6 in whole levels, darkening the shadows while the source brightened.
        # With the offset held, the slope takes the drift (down to LOW_LIGHT_HOLD_GIVE_Q8 below V4's).
        def scene(shift):
            rng = np.random.default_rng(6)
            levels = rng.integers(30, 91, (H//8+1, W//8+1))+shift
            levels[rng.random(levels.shape) < .03] = 200
            return stats_of(frame(np.kron(levels, np.ones((8, 8)))[:H, :W]))[0]
        dim, lit, brighter = scene(-3), scene(2), scene(4)
        first = auto_v5.low_light_curve(dim, 384, 64)
        self.assertEqual((first['gain_q8_8'], first['brightness']), (384, auto_v5.LOW_LIGHT_MAX_OFFSET))
        self.assertIsNone(auto_v5.low_light_curve(lit, 384, 64))     # unheld: no boost at this median
        held = auto_v5.low_light_curve(lit, 384, 64, hold=first['brightness'])
        self.assertEqual(held['brightness'], first['brightness']); self.assertEqual(held['knee_out'], auto_v5.LOW_LIGHT_MAX_KNEE)
        self.assertTrue(384-auto_v5.LOW_LIGHT_HOLD_GIVE_Q8 <= held['gain_q8_8'] < 384)
        level = int(lit['quantiles']['p50'])
        self.assertLessEqual(abs(((held['gain_q8_8']*level+128) >> 8)+held['brightness']-auto_v5.LOW_LIGHT_TARGET_MEDIAN), 1)
        # Past the give the offset is let go (the curve relaxes as before).
        self.assertIsNone(auto_v5.low_light_curve(brighter, 384, 64, hold=first['brightness']))

    def test_offset_chroma_share_uses_the_scene_level(self):
        # v5.5: at a median of ~60 a level-24 share took chroma well below the slope's gain.
        rng = np.random.default_rng(6)
        levels = rng.integers(27, 88, (H//8+1, W//8+1))
        levels[rng.random(levels.shape) < .03] = 200
        params, record, _ = self.run_one(frame(np.kron(levels, np.ones((8, 8)))[:H, :W]))
        boost = record['v5']['low_light']
        self.assertIsNotNone(boost); self.assertGreater(params['brightness'], 0)
        self.assertGreater(boost['level'], auto_v5.LOW_LIGHT_MIN_LEVEL)
        slope = params['gain_q8_8']-256
        at = lambda level: (auto_v5.CHROMA_Q8*slope+(slope+(params['brightness']*256+level//2)//level)//2)//(slope+(params['brightness']*256+level//2)//level)
        self.assertEqual(params['chroma_q8'], at(boost['level']))
        self.assertGreater(params['chroma_q8'], at(auto_v5.LOW_LIGHT_MIN_LEVEL))

    def test_black_offset_has_hysteresis(self):
        # The smoothed offset must move 0.75 level from the applied one before it changes.
        opt = AutoOptimizerV5()
        base = dict(gain_q8_8=384, brightness=4, knee_out=80, soft_q8_8=145)
        self.assertEqual(opt._tone(dict(base), 40, True, True)['brightness'], 4)
        opt.state['tone'][1] = 4*256+160                  # 4.63: still 4
        self.assertEqual(opt._tone_step(0)['brightness'], 4)
        opt.state['tone'][1] = 4*256+200                  # 4.78: now 5
        self.assertEqual(opt._tone_step(0)['brightness'], 5)
        opt.state['tone'][1] = 4*256+100                  # 4.39: back only below 4.25
        self.assertEqual(opt._tone_step(0)['brightness'], 5)

    def test_mode5_floor_hysteresis(self):
        opt = AutoOptimizerV5(); payload = frame(blocks()); stats, noise = stats_of(payload)
        record = dict(scene_reset=False, reason=dict(decision='global-underexposure'), effective_noise={'sigma_q8': 300}, policy='v4')
        detail = dict(acutance_q8=None, softness_q8=0, edge_samples=0, gate=12, dark_sigma_q8=None, dark_share_q8=0, dark_texture_q8=0)
        floors = []
        for pts, gain in enumerate((370, 364, 359, 372, 312, 311)):
            lift = dict(Params().__dict__, mode=5, gain_q8_8=gain, knee_out=80, soft_q8_8=150, filter_enable=0, noise_floor=0, noise_floor_uv=0)
            opt.v4.update = lambda *args, lift=lift: (dict(lift), dict(record))
            floors.append(opt.update(pts*40, stats, noise, detail, 256)[0]['noise_floor'])
        # The floor follows the smoothed tone gain (TONE_TAU_MS): brief gain dips no
        # longer toggle the denoise strength frame to frame (texture flicker).
        self.assertEqual(floors, [4, 4, 4, 4, 4, 4])
        # A lasting lower gain still lowers it once the curve has followed.
        for pts in range(6, 80):
            floors.append(opt.update(pts*40, stats, noise, detail, 256)[0]['noise_floor'])
        self.assertEqual(floors[-1], 2)
        self.assertEqual(floors, sorted(floors, reverse=True))   # monotone, no back-and-forth

    def test_textured_shadows_keep_their_detail(self):
        # Rain/foliage shadows (edge share >= 0.5) get no extra denoise; partly textured ones less.
        params, record = self.lifted(372, 1024, 136)
        self.assertIsNone(record['v5']['lift_denoise'])
        # Chroma denoise is the IP 1.4 chroma-gain floor (gain 1.45 >= 1.25), not a lift denoise.
        self.assertEqual((params['filter_enable'], params['noise_floor'], params['noise_floor_uv']),
                         (1, 4, auto_v5.CHROMA_GAIN_UV_FLOOR))
        params, record = self.lifted(372, 1024, 90)
        self.assertEqual(record['v5']['lift_denoise'], 3)

    def test_mode5_chroma_follows_luma(self):
        # Enhance IP 1.4: every mode-5 frame asks for full chroma gain; the chroma
        # denoise floor only rises with a real luma gain.
        params, record = self.lifted(372, 1024, 136)
        self.assertEqual((params['mode'], params['chroma_q8']), (5, auto_v5.CHROMA_Q8))
        self.assertEqual(record['v5']['chroma_q8'], auto_v5.CHROMA_Q8)
        params, _ = self.lifted(256, 1024)
        self.assertEqual((params['mode'], params['chroma_q8'], params['noise_floor_uv']), (5, auto_v5.CHROMA_Q8, 0))

    def test_clarity_follows_mode_and_noise_floor(self):
        # Enhance IP 1.5: mode 5 clarity cores more as the noise floor rises.
        params, record = self.lifted(372, 1024, 136)
        self.assertEqual(params['clarity'], auto_v5.CLARITY_MODE5[min(4, max(2, params['noise_floor']))])
        self.assertEqual(record['v5']['clarity'], params['clarity'])
        self.assertEqual(params['clarity'] >> 16 & 255, 24)
        self.assertEqual(auto_v5.CLARITY_MODE4 & 255, 28)

    def test_no_lift_no_extra_denoise(self):
        params, record = self.lifted(256, 1024)
        self.assertIsNone(record['v5']['lift_denoise'])
        self.assertEqual((params['filter_enable'], params['noise_floor']), (1, auto_v5.MODE5_MIN_FLOOR))

    def test_noisy_scene_keeps_v4_denoise(self):
        rng = np.random.default_rng(5)
        y = np.where((np.indices((H, W))[1]//24) % 2, 200, 60)+rng.normal(0, 6, (H, W))
        params, record, _ = self.run_one(frame(y, np.clip(128+rng.normal(0, 6, (H, W)), 0, 255)))
        self.assertEqual(params['mode'], 5)

    def test_lifted_blacks_are_stretched_not_brightened(self):
        y = 70+np.indices((H, W))[1]*110//W
        params, record, _ = self.run_one(frame(y))
        self.assertEqual(params['mode'], 5); self.assertTrue(record['v5']['haze'])
        self.assertGreater(params['gain_q8_8'], 256); self.assertLess(params['brightness'], 0)

    def test_mode_change_needs_dwell_and_cut_is_immediate(self):
        clean = frame(blocks())
        rng = np.random.default_rng(6)
        noisy = frame(blocks()+rng.normal(0, 6, (H, W)),
                      np.clip(128+rng.normal(0, 6, (H, W)), 0, 255))
        params, _, opt = self.run_one(clean, 0)
        self.assertEqual(params['mode'], 4)
        params, record, _ = self.run_one(noisy, 100, opt)
        if not record['scene_reset']:
            self.assertEqual(params['mode'], 4)
            params, _, _ = self.run_one(noisy, 100+auto_v5.MODE_DWELL_MS, opt)
        self.assertEqual(params['mode'], 5)

    def shadow_lift(self, gain, knee, soft):
        # Full-range frame (not hazy); V4 is pinned to a measured-shadow lift so only v5's choice is tested.
        payload = frame(blocks())
        stats, noise = stats_of(payload)
        opt = AutoOptimizerV5()
        lift = dict(Params().__dict__, mode=5, gain_q8_8=gain, knee_out=knee, soft_q8_8=soft, filter_enable=0, noise_floor=0)
        record = dict(scene_reset=True, reason=dict(decision='measured-shadow-region'), effective_noise={}, policy='v4')
        opt.v4.update = lambda *args: (dict(lift), dict(record))
        soft_detail = dict(acutance_q8=298, softness_q8=93, edge_samples=10000, gate=12)
        return opt.update(0, stats, noise, soft_detail, 384), stats

    def test_tone_effect_measures_the_curve_not_the_gain(self):
        _, stats = self.shadow_lift(338, 16, 190)
        knee_mean, knee_max = auto_v5.tone_effect(stats, dict(gain_q8_8=338, brightness=0, knee_out=16, soft_q8_8=190))
        flat_mean, flat_max = auto_v5.tone_effect(stats, dict(gain_q8_8=338, brightness=0, knee_out=255, soft_q8_8=256))
        self.assertLessEqual(knee_max, auto_v5.MILD_EFFECT_MAX); self.assertLessEqual(knee_mean, auto_v5.MILD_EFFECT_MEAN_Q8)
        self.assertGreater(flat_max, 30)

    def test_invisible_shadow_lift_is_traded_for_sharpening(self):
        # Measured on the people 720p source upscaled to 1080p (docs/AUTO_V5_CN.md):
        # V4 asks gain 1.32x with knee 16 / soft 0.74, which moves pixels ~1-4 levels.
        (params, record), _ = self.shadow_lift(338, 16, 190)
        self.assertEqual(params['mode'], 4); self.assertTrue(record['v5']['traded_mild_lift'])
        self.assertGreater(params['sharp_q8_8'], 256)

    def test_visible_shadow_lift_is_kept(self):
        (params, record), _ = self.shadow_lift(384, 255, 256)
        self.assertEqual(params['mode'], 5); self.assertEqual(params['gain_q8_8'], 384)

    def test_v4_gain_is_never_overridden_by_stale_stretch(self):
        opt = AutoOptimizerV5()
        self.run_one(frame(70+np.indices((H, W))[1]*110//W), 0, opt)
        dark = frame(np.clip(np.indices((H, W))[1]*90//W, 0, 255))
        params, record, _ = self.run_one(dark, 40, opt)
        if record['v5']['v4_decision'] != 'normal-exposure':
            # The target is V4's curve at once; the applied curve ramps there
            # (temporal tone stabilisation) instead of jumping.
            # Its only black offset is the low-light one (v5.3), never the old stretch's.
            low_light = record['v5']['low_light']
            offset = low_light['brightness'] if low_light else 0
            self.assertEqual(record['v5']['tone_target']['brightness'], offset)
            for pts in range(80, 4000, 40):
                params, record, _ = self.run_one(dark, pts, opt)
            low_light = record['v5']['low_light']
            self.assertEqual(params['brightness'], low_light['brightness'] if low_light else 0)


class ToneStabilityTests(unittest.TestCase):
    def test_tone_curve_moves_smoothly_every_frame(self):
        # Night clips: V4 re-picked the knee (80 -> 16) and false cuts snapped the gain;
        # the applied curve must change by small steps, also between analyses.
        opt = AutoOptimizerV5(); payload = frame(blocks()); stats, noise = stats_of(payload)
        detail = dict(acutance_q8=None, softness_q8=0, edge_samples=0, gate=12, dark_sigma_q8=None, dark_share_q8=0, dark_texture_q8=0)
        lut = lambda p: np.clip(np.where((m := (p['gain_q8_8']*np.arange(256)+128)//256+p['brightness']) > p['knee_out'],
                                         p['knee_out']+((m-p['knee_out'])*p['soft_q8_8'])//256, m), 0, 255)
        curves = []
        for k, (gain, knee, soft, cut) in enumerate(((370, 80, 150, False), (372, 16, 184, False), (256, 255, 256, True),
                                                     (384, 80, 147, True), (320, 32, 198, False))):
            lift = dict(Params().__dict__, mode=5, gain_q8_8=gain, knee_out=knee, soft_q8_8=soft, filter_enable=0, noise_floor=0, noise_floor_uv=0)
            record = dict(scene_reset=cut, reason=dict(decision='global-underexposure'), effective_noise={'sigma_q8': 300}, policy='v4')
            opt.v4.update = lambda *args, lift=lift, record=record: (dict(lift), dict(record))
            curves.append(lut(opt.update(k*167, stats, noise, detail, 256)[0]))
            for step in (1, 2, 3):
                curves.append(lut(opt.advance(k*167+step*42)))
        jumps = [float(np.abs(b.astype(int)-a.astype(int)).mean()) for a, b in zip(curves, curves[1:])]
        self.assertLess(max(jumps), 3.0, jumps)


class SpatialStabilityTests(unittest.TestCase):
    def setUp(self):
        self.opt = AutoOptimizerV5()
        self.stats, self.noise = stats_of(frame(blocks()))
        self.detail = dict(acutance_q8=None, softness_q8=0, edge_samples=0, gate=12,
                           dark_sigma_q8=None, dark_share_q8=0, dark_texture_q8=0)

    def update(self, pts, floor=2, gain=256, low_key=False):
        base = dict(Params().__dict__, mode=5, gain_q8_8=gain, knee_out=80 if gain>256 else 255,
                    soft_q8_8=147 if gain>256 else 256, filter_enable=1,
                    noise_floor=floor, noise_floor_uv=floor)
        record = dict(scene_reset=False, reason=dict(decision='global-underexposure'),
                      effective_noise={'sigma_q8': 400}, policy='v4')
        self.opt.v4.update = lambda *args: (dict(base), dict(record))
        stats = dict(self.stats, quantiles=dict(self.stats['quantiles'], p50=16)) if low_key else self.stats
        p, record = self.opt.update(pts, stats, self.noise, self.detail)
        valid(p)
        return p, record

    def test_noise_threshold_jitter_does_not_toggle_sharpening(self):
        values = []
        for analysis in range(12):
            p, _ = self.update(analysis*160, floor=2+analysis%2)
            values.append(p['sharp_q8_8'])
            for step in (40, 80, 120):
                p = self.opt.advance(analysis*160+step)
                valid(p)
                values.append(p['sharp_q8_8'])
        self.assertLessEqual(max(abs(b-a) for a, b in zip(values, values[1:])), 21)
        self.assertEqual(values, sorted(values, reverse=True))
        self.assertEqual(values[-1], auto_v5.MODE5_USM_GRAINY_Q8)
        self.assertGreater(len(set(values)), 5)

    def test_denoise_protects_immediately_and_requires_sustained_release(self):
        first, _ = self.update(0, floor=2)
        noisy, _ = self.update(160, floor=5)
        self.assertEqual((first['noise_floor'], noisy['noise_floor']), (2, 5))
        for pts in (320, 480, 640):
            p, _ = self.update(pts, floor=2)
            self.assertEqual(p['noise_floor'], 5)
        for pts in range(800, 2601, 160):
            p, _ = self.update(pts, floor=2)
        self.assertEqual(p['noise_floor'], 2)

    def test_low_key_protection_transitions_between_analyses(self):
        before, _ = self.update(0, gain=384)
        switched, record = self.update(160, gain=384, low_key=True)
        self.assertTrue(record['v5']['low_key_protection'])
        self.assertEqual(record['v5']['detail_target']['clarity_a'], 0)
        self.assertGreater(switched['clarity'] & 255, 0)
        self.assertLess(switched['clarity'] & 255, before['clarity'] & 255)
        strengths = []
        for pts in range(200, 2001, 40):
            p = self.opt.advance(pts)
            valid(p)
            strengths.append(p['clarity'] & 255)
        self.assertEqual(strengths, sorted(strengths, reverse=True))
        self.assertEqual(strengths[-1], 0)
        self.assertGreater(len(set(strengths)), 5)

    def test_reset_drops_spatial_history_and_uses_new_scene(self):
        self.update(0, floor=5)
        self.update(160, floor=2)
        self.opt.reset()
        p, _ = self.update(0, floor=2)
        self.assertEqual((p['noise_floor'], p['sharp_q8_8']), (2, auto_v5.MODE5_USM_Q8))


class PreviewTests(unittest.TestCase):
    def test_preview_matches_full_conversion_on_its_grid(self):
        rng = np.random.default_rng(7)
        payload = rng.integers(0, 256, W*H*2, dtype=np.uint8).tobytes()
        full = unpack_rgb(payload, W, H)
        small = preview_rgb(payload, W, H, 3)
        cols = np.array([c for p in range(0, W//2, 3) for c in (2*p, 2*p+1)])
        np.testing.assert_array_equal(small, full[::3][:, cols])


if __name__ == '__main__':
    unittest.main()
