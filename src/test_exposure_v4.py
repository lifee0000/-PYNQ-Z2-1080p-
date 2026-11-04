"""Deterministic CPU tests. No media files, EXE, hardware or file-name rules."""
import importlib.util
import json
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import exposure_v4 as a

FROZEN = next((path for path in (HERE/'test_support/v3',HERE.parent/'V3/src',HERE.parents[1]/'PYNQ23/src')
    if (path/'pc_app/pynq_video/analysis_v3.py').is_file()),None)
if FROZEN is None:
    raise FileNotFoundError('Matching v3 src/pc_app/pynq_video/analysis_v3.py is required inside this package')
spec = importlib.util.spec_from_file_location('frozen_analysis_v3',FROZEN/'pc_app/pynq_video/analysis_v3.py')
v3 = importlib.util.module_from_spec(spec);spec.loader.exec_module(v3)
sys.path.insert(0,str(FROZEN/'tools'))
from file_process_protocol import normalize_parameters

METRICS = {}


def gray(level,h=96,w=128):
    return np.full((h,w,3),level,np.uint8)


def sigma(y,uv=None,confidence=256):
    result = dict(sigma_q8=round(y*256),confidence_q8=confidence)
    if uv is not None:
        result.update(filter_sigma_q8=round(max(y,uv)*256),filter_confidence_q8=confidence,
                      uv_sigma_q8=round(uv*256),uv_confidence_q8=confidence)
    return result


def apply_tone(rgb,p,matrix=a.luminance):
    yy = matrix(rgb).astype(np.int32)
    delta = a.tone_lut(p['gain_q8_8'],p['knee_out'],p['soft_q8_8'])[yy]-yy
    return np.clip(rgb.astype(np.int32)+delta[:,:,None],0,255).astype(np.uint8)


def inverse709(y,u,v):
    uu = np.repeat(u.astype(np.int32)-128,2,axis=1)
    vv = np.repeat(v.astype(np.int32)-128,2,axis=1)
    yy = y.astype(np.int32)
    return np.clip(np.stack((yy+((103206*vv+32768)>>16),
        yy-((12276*uu+30679*vv+32768)>>16),
        yy+((121609*uu+32768)>>16)),axis=-1),0,255).astype(np.uint8)


def pack709(rgb):
    rgb = rgb.astype(np.int32)
    r,g,b = (rgb[:,:,i] for i in range(3))
    y = ((13933*r+46871*g+4732*b+32768)>>16).astype(np.uint8)
    u = np.clip(((-7509*r-25259*g+32768*b+32768)>>16)+128,0,255).astype(np.uint16)
    v = np.clip(((32768*r-29763*g-3005*b+32768)>>16)+128,0,255).astype(np.uint16)
    result = np.empty((*rgb.shape[:2],2),np.uint8)
    result[:,:,0] = y
    result[:,0::2,1] = (u[:,0::2]+u[:,1::2]+1)//2
    result[:,1::2,1] = (v[:,0::2]+v[:,1::2]+1)//2
    return result.tobytes()


class BoundedStatistics(unittest.TestCase):
    def test_bt709_primary_values_and_int32_safe_white(self):
        rgb = np.array([[(255,0,0),(0,255,0),(0,0,255),(255,255,255),(0,0,0)]],np.uint8)
        self.assertEqual(a.luminance(rgb).tolist(),[[54,182,18,255,0]])

    def test_histogram_and_native_noise_budgets(self):
        stats,noise = a.analyze_v4(gray(96,720,1280))
        self.assertLessEqual(stats['sample_count'],65536)
        self.assertLessEqual(noise['native_pixels'],9216)
        self.assertLessEqual(noise['sampled_patches'],64)
        self.assertEqual(sum(stats['histogram']),stats['sample_count'])
        self.assertEqual(len(stats['max_rgb_by_luma']),256)
        self.assertEqual(stats['color_matrix'],a.COLOR_MATRIX)

    def test_odd_roi_excludes_black_and_incomplete_chroma_pairs(self):
        rgb = np.zeros((120,160,3),np.uint8);rgb[:,31:111]=80
        stats,noise = a.analyze_v4(rgb,(31,0,80,120))
        self.assertEqual(set(stats['quantiles'].values()),{80})
        self.assertEqual(stats['region_pixels'],80*120)
        self.assertEqual(noise['sigma_q8'],0)
        self.assertEqual(noise['u_sigma_q8'],0)
        self.assertEqual(noise['v_sigma_q8'],0)

    def test_pure_chroma_noise_is_measured_after_actual_pair_sampling(self):
        rng = np.random.default_rng(20261023)
        yy = np.full((192,256),96,np.uint8)
        u = np.clip(128+rng.normal(0,9,(192,128)),0,255).round().astype(np.uint8)
        v = np.clip(128+rng.normal(0,9,(192,128)),0,255).round().astype(np.uint8)
        stats,noise = a.analyze_v4(inverse709(yy,u,v))
        self.assertLess(noise['sigma_q8'],2*256)
        self.assertGreater(noise['u_sigma_q8'],6*256)
        self.assertGreater(noise['v_sigma_q8'],6*256)
        params,reason = a.suggest_v4(stats,noise)
        self.assertEqual(params['filter_enable'],1)
        self.assertEqual(params['noise_floor'],0)
        self.assertGreaterEqual(params['noise_floor_uv'],9)
        self.assertEqual(reason['noise_gain_ceiling'],384)
        METRICS['pure_chroma_noise'] = dict(noise=noise,parameters=params,
            note='Pair-domain sigma; Y exposure ceiling is independent of UV sigma')

    def test_clean_fine_luma_textures_do_not_trigger_noise_filter(self):
        yy,xx = np.indices((96,128))
        for amplitude in (3,40,100):
            for y in (96+amplitude*((xx&1)*2-1),96+amplitude*(((xx+yy)&1)*2-1)):
                rgb = np.repeat(np.clip(y,0,255).astype(np.uint8)[:,:,None],3,axis=2)
                stats,noise = a.analyze_v4(rgb)
                params,_ = a.suggest_v4(stats,noise)
                self.assertEqual(params['filter_enable'],0)

    def test_split_control_reduces_chroma_noise_without_erasing_clean_luma_texture(self):
        split_root = HERE
        sys.path.insert(0,str(split_root))
        split_spec = importlib.util.spec_from_file_location('spatial_split_reference',split_root/'reference.py')
        spatial = importlib.util.module_from_spec(split_spec);split_spec.loader.exec_module(spatial)
        rng = np.random.default_rng(20261023)
        y = (128+(np.indices((128,192))[1]%2)*2-1).astype(np.uint8)
        u = np.clip(128+rng.normal(0,9,(128,96)),0,255).round().astype(np.uint8)
        v = np.clip(128+rng.normal(0,9,(128,96)),0,255).round().astype(np.uint8)
        rgb = inverse709(y,u,v)
        stats,noise = a.analyze_v4(rgb)
        p,record = a.ExposureControllerV4().update(0,stats,noise)
        self.assertEqual((p['gain_q8_8'],p['noise_floor'],p['filter_enable']),(256,0,1))
        self.assertGreater(p['noise_floor_uv'],0)
        payload = pack709(rgb)
        actual = spatial.enhance(payload,192,128,spatial.Params(mode=5,**p))
        original = spatial.v3.unpack(payload,192,128)
        output = spatial.v3.unpack(actual,192,128)
        np.testing.assert_array_equal(original[:,:,0],output[:,:,0])
        before = float(np.mean((original[:,:,1].astype(float)-128)**2))
        after = float(np.mean((output[:,:,1].astype(float)-128)**2))
        self.assertLess(after,before*.8)
        METRICS['mixed_y_texture_uv_noise'] = dict(y_max_error=0,
            uv_mse_input=before,uv_mse_output=after,uv_gain_db=float(10*np.log10(before/after)),
            parameters=p,noise=noise,reference_kind='CPU v4_split, not FPGA')

    def test_invalid_roi_budget_and_input(self):
        rgb = gray(96,16,16)
        for rect in ((0.5,0,8,8),(-1,0,8,8),(0,0,0,8),(12,12,8,8)):
            with self.subTest(rect=rect),self.assertRaises(ValueError):a.analyze_v4(rgb,rect)
        for count in (False,0,-1,65537,1.5):
            with self.subTest(count=count),self.assertRaises(ValueError):a.analyze_v4(rgb,max_samples=count)


class AdversarialNoiseEvidence(unittest.TestCase):
    def test_clipped_dark_and_highlight_stochastic_noise_enable_and_improve_truth(self):
        import reference as spatial
        rng = np.random.default_rng(20261023)
        rows = []
        for level in (0,2,5,250,255):
            with self.subTest(level=level):
                y = np.clip(level+rng.normal(0,6,(128,192)),0,255).round().astype(np.uint8)
                rgb = np.repeat(y[:,:,None],3,axis=2)
                stats,noise = a.analyze_v4(rgb)
                p,_ = a.ExposureControllerV4().update(0,stats,noise)
                self.assertGreaterEqual(noise['confidence_q8'],128)
                self.assertGreater(noise['sigma_q8'],2*256)
                self.assertEqual((p['gain_q8_8'],p['filter_enable'],p['noise_floor_uv']),(256,1,0))
                source = pack709(rgb)
                output = spatial.enhance(source,192,128,spatial.Params(mode=5,**p))
                actual = spatial.v3.unpack(output,192,128)[:,:,0]
                before = float(np.mean((y.astype(float)-level)**2))
                after = float(np.mean((actual.astype(float)-level)**2))
                self.assertLess(after,before*.75)
                rows.append(dict(clean_level=level,injected_preclip_sigma=6,
                    input_mse=before,output_mse=after,gain_db=float(10*np.log10(before/after)),
                    observed_sigma_q8=noise['sigma_q8'],parameters=p,
                    censoring_corrected=noise['channels']['y']['gaussian']['censoring_corrected']))
        METRICS['clipped_stochastic_truth'] = dict(cases=rows,execution='CPU reference only')

    def test_complete_clipping_and_small_rois_are_unknown_not_measured_zero(self):
        for level in (0,255):
            stats,noise = a.analyze_v4(gray(level))
            self.assertIsNone(noise['sigma_q8'])
            self.assertEqual(noise['confidence_q8'],0)
            self.assertEqual(noise['channels']['y']['status'],'clipped-unidentifiable')
            self.assertEqual(a.suggest_v4(stats,noise)[0]['filter_enable'],0)
        for roi in ((1,3,5,4),(0,0,12,12)):
            _,noise = a.analyze_v4(gray(96),roi)
            self.assertIsNone(noise['sigma_q8'])
            self.assertEqual(noise['confidence_q8'],0)
        _,flat = a.analyze_v4(gray(5))
        self.assertEqual(flat['sigma_q8'],0)
        self.assertEqual(flat['channels']['y']['status'],'observed-flat')

    def test_real_isolated_lights_thin_lines_and_text_are_clean_negatives(self):
        import reference as spatial
        protected = []
        glyph = np.array([[1,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],
            [1,1,1,1,0],[1,0,0,0,1],[1,0,0,0,1],[1,1,1,1,0]],bool)
        for level,bright in ((5,255),(96,99),(96,180),(250,255)):
            for kind in ('isolated-lights','thin-lines','text'):
                y = np.full((128,192),level,np.uint8)
                if kind=='isolated-lights':
                    y[3::17,4::23]=bright
                elif kind=='thin-lines':
                    y[7::19,:]=bright;y[:,11::29]=bright
                else:
                    for oy in range(5,116,16):
                        for ox in range(5,180,13):
                            y[oy:oy+7,ox:ox+5][glyph]=bright
                rgb = np.repeat(y[:,:,None],3,axis=2)
                stats,noise = a.analyze_v4(rgb)
                p,_ = a.ExposureControllerV4().update(0,stats,noise)
                with self.subTest(level=level,bright=bright,kind=kind):
                    self.assertEqual(p['filter_enable'],0)
                    payload = pack709(rgb)
                    self.assertEqual(spatial.enhance(payload,192,128,spatial.Params(mode=5,**p)),payload)
                protected.append(dict(kind=kind,background=level,foreground=bright,max_byte_error=0,
                    impulse_candidates=noise['channels']['y']['impulse']['candidate_count']))
        METRICS['clean_negative_details'] = protected

    def test_sparse_events_are_recorded_without_claiming_noise_or_enabling_filter(self):
        rgb = gray(5,128,192);rgb[3::17,4::23]=255
        stats,noise = a.analyze_v4(rgb)
        impulse = noise['channels']['y']['impulse']
        self.assertGreater(impulse['candidate_count'],0)
        self.assertGreaterEqual(impulse['confidence_q8'],128)
        self.assertFalse(impulse['used_for_filter'])
        self.assertEqual(impulse['interpretation'],'ambiguous-isolated-events')
        self.assertEqual(a.suggest_v4(stats,noise)[0]['filter_enable'],0)
        METRICS['sparse_impulse_ambiguity'] = dict(diagnostic=impulse,
            note='The identical frame may be real lights or salt noise; neither identity is inferable.')

    def test_compression_like_blocks_and_oscillation_are_diagnostics_not_gaussian_noise(self):
        rng = np.random.default_rng(4)
        yy,xx = np.indices((128,192))
        cases = dict(grid=np.repeat(np.repeat(rng.integers(90,103,(16,24)),8,0),8,1),
            oscillation=96+np.round(6*np.cos(xx*np.pi/2)))
        rows = {}
        for name,y in cases.items():
            stats,noise = a.analyze_v4(np.repeat(y.astype(np.uint8)[:,:,None],3,axis=2))
            diagnostic = noise['channels']['y']['compression']
            self.assertGreaterEqual(diagnostic['confidence_q8'],128)
            self.assertFalse(diagnostic['codec_identity_known'])
            self.assertFalse(diagnostic['used_for_filter'])
            self.assertEqual(a.suggest_v4(stats,noise)[0]['filter_enable'],0)
            rows[name]=diagnostic
        METRICS['compression_or_texture_ambiguity'] = rows

    def test_rgb_packed_diagnostics_match_at_clipped_odd_rois(self):
        rng = np.random.default_rng(176)
        for level in (0,5,250,255):
            y = np.clip(level+rng.normal(0,6,(128,192)),0,255).round().astype(np.uint8)
            rgb = np.repeat(y[:,:,None],3,axis=2)
            for roi in (None,(1,3,190,120)):
                _,rn = a.analyze_v4(rgb,roi)
                _,yn = a.analyze_yuyv_v4(pack709(rgb),192,128,roi)
                self.assertEqual(rn,yn)
                self.assertLessEqual(rn['native_pixels'],9216)
        self.assertFalse(rn['evidence_scores_are_probabilities'])

    def test_unknown_history_expires_independently_and_stops_filter(self):
        stats,_ = a.analyze_v4(gray(96))
        controller = a.ExposureControllerV4(unknown_hold_ms=1500)
        controller.update(0,stats,sigma(8,7))
        p,r = controller.update(1000,stats,{})
        self.assertEqual(p['filter_enable'],1)
        self.assertTrue(r['noise_held'])
        p,r = controller.update(1500,stats,{})
        self.assertEqual((p['filter_enable'],p['noise_floor'],p['noise_floor_uv']),(0,0,0))
        self.assertTrue(r['noise_history_expired'])
        self.assertTrue(r['uv_noise_history_expired'])
        controller.reset()
        controller.update(0,stats,sigma(8,7))
        p,r = controller.update(1500,stats,dict(uv_sigma_q8=6*256,uv_confidence_q8=256))
        self.assertEqual((p['filter_enable'],p['noise_floor']),(1,0))
        self.assertGreater(p['noise_floor_uv'],0)
        self.assertTrue(r['noise_history_expired'])
        self.assertFalse(r['uv_noise_history_expired'])


class ExposureRegression(unittest.TestCase):
    def test_v3_backlight_defect_and_v4_measured_shadow_lift(self):
        rgb = gray(205);rgb[24:72,16:96]=52;rgb[4:12,104:120]=255
        old_stats,old_noise = v3.analyze_v3(rgb)
        old = v3.suggest_v3(old_stats,old_noise)
        stats,noise = a.analyze_v4(rgb)
        new,reason = a.suggest_v4(stats,noise)
        old_image = apply_tone(rgb,old,v3.luminance)
        new_image = apply_tone(rgb,new)
        self.assertEqual(int(old_image[40,40,0]),52)
        self.assertGreaterEqual(int(new_image[40,40,0]),64)
        self.assertGreaterEqual(int(new_image[7,110,0]),253)
        self.assertEqual(reason['decision'],'measured-shadow-region')
        METRICS['backlight'] = dict(v3_shadow=int(old_image[40,40,0]),
            v4_shadow=int(new_image[40,40,0]),v4_white=int(new_image[7,110,0]),
            parameters=new,input_sha256=__import__('hashlib').sha256(rgb).hexdigest())

    def test_v3_coloured_highlight_clipping_is_prevented_in_sample_guard(self):
        rgb = gray(52);rgb[:24]=(250,200,30);rgb[24:30]=255
        os,on = v3.analyze_v3(rgb);old = v3.suggest_v3(os,on)
        stats,noise = a.analyze_v4(rgb);new,guard = a.suggest_v4(stats,noise)
        before = apply_tone(rgb,old,v3.luminance)
        after = apply_tone(rgb,new)
        old_clips = int(np.count_nonzero((rgb<255)&(before==255)))
        new_clips = int(np.count_nonzero((rgb<255)&(after==255)))
        self.assertGreater(old_clips,0)
        self.assertEqual(new_clips,0)
        self.assertLessEqual(int(after[0,0,0]),253)
        self.assertGreater(int(after[60,60,0]),52)
        self.assertEqual(guard['sampled_predicted_new_clipping_bins'],0)
        METRICS['coloured_highlight'] = dict(v3_new_clipped_channels=old_clips,
            v4_new_clipped_channels=new_clips,v3_rgb=before[0,0].tolist(),
            v4_rgb=after[0,0].tolist(),v4_shadow=int(after[60,60,0]),parameters=new)

    def test_white_anchor_black_floor_monotonic_curve_and_parameter_contract(self):
        rgb = gray(48);stats,_ = a.analyze_v4(rgb)
        for noise in (sigma(0),sigma(4),sigma(9),sigma(20)):
            p,_ = a.suggest_v4(stats,noise)
            normalize_parameters(dict(mode=5,**a.adapt_legacy_parameters(p)))
            lut = a.tone_lut(p['gain_q8_8'],p['knee_out'],p['soft_q8_8'])
            self.assertEqual(int(lut[0]),0)
            self.assertTrue(np.all(np.diff(lut)>=0))
            self.assertGreaterEqual(int(lut[255]),253)
            self.assertLessEqual(int(lut[255]),255)
        black,_ = a.analyze_v4(gray(5))
        p,_ = a.suggest_v4(black,sigma(10))
        self.assertEqual((p['gain_q8_8'],p['brightness']),(256,0))

    def test_legacy_adapter_never_silently_discards_active_uv_or_y_bypass(self):
        stats,_ = a.analyze_v4(gray(96))
        uv,_ = a.suggest_v4(stats,sigma(0,9))
        self.assertEqual((uv['noise_floor'],uv['filter_enable']),(0,1))
        self.assertGreater(uv['noise_floor_uv'],0)
        with self.assertRaisesRegex(ValueError,'active UV'):
            a.adapt_legacy_parameters(uv)
        with self.assertRaisesRegex(ValueError,'independent Y bypass'):
            a.adapt_legacy_parameters(dict(uv,noise_floor_uv=0))

    def test_very_noisy_shadows_limit_gain(self):
        stats,_ = a.analyze_v4(gray(48))
        params,_ = a.suggest_v4(stats,sigma(12))
        self.assertLessEqual(params['gain_q8_8'],288)
        clean,_ = a.suggest_v4(stats,sigma(0))
        self.assertGreater(clean['gain_q8_8'],params['gain_q8_8'])

    def test_v3_sigma_four_ceiling_discontinuity_removed(self):
        rgb = gray(52)
        old_stats,_ = v3.analyze_v3(rgb)
        stats,_ = a.analyze_v4(rgb)
        old = [v3.suggest_v3(old_stats,sigma(s))['gain_q8_8'] for s in (3.9,4.1)]
        new = [a.suggest_v4(stats,sigma(s))[0]['gain_q8_8'] for s in (3.9,4.1)]
        self.assertEqual(abs(old[1]-old[0]),64)
        self.assertLessEqual(abs(new[1]-new[0]),4)
        METRICS['sigma_threshold'] = dict(v3_gain=old,v4_gain=new)


class NativeYuyvEntry(unittest.TestCase):
    def test_exact_statistics_noise_and_control_match_rgb_at_identical_positions(self):
        rng = np.random.default_rng(20261023)
        inputs = [rng.integers(0,256,(128,192,3),np.uint8),gray(52,128,192)]
        y = np.full((128,192),96,np.uint8)
        u = np.clip(128+rng.normal(0,9,(128,96)),0,255).round().astype(np.uint8)
        v = np.clip(128+rng.normal(0,9,(128,96)),0,255).round().astype(np.uint8)
        inputs.append(inverse709(y,u,v))
        for rgb in inputs:
            payload = pack709(rgb)
            for roi in (None,(1,3,190,120),(3,1,5,3),(1,0,2,96)):
                for budget in (1,20,65536):
                    with self.subTest(roi=roi,budget=budget):
                        rs,rn = a.analyze_v4(rgb,roi,budget)
                        ys,yn = a.analyze_yuyv_v4(payload,192,128,roi,budget)
                        # The sole intentional difference describes source reads.
                        rs.pop('rgb_positions_read_upper_bound')
                        self.assertEqual(ys.pop('rgb_positions_read_upper_bound'),0)
                        self.assertLessEqual(ys.pop('yuyv_positions_read_upper_bound'),65536)
                        self.assertEqual(rs,ys)
                        self.assertEqual(rn,yn)
                        p1,r1 = a.ExposureControllerV4().update(0,rs,rn)
                        p2,r2 = a.ExposureControllerV4().update(0,ys,yn)
                        self.assertEqual(p1,p2)
                        self.assertEqual(r1,r2)

    def test_720p_subsampling_matches_noise_patch_phase_and_source_not_modified(self):
        rng = np.random.default_rng(20261023)
        rgb = np.clip(96+rng.normal(0,6,(720,1280,3)),0,255).round().astype(np.uint8)
        payload = bytearray(pack709(rgb));before = bytes(payload)
        rs,rn = a.analyze_v4(rgb,(1,3,1278,714))
        ys,yn = a.analyze_yuyv_v4(payload,1280,720,(1,3,1278,714))
        self.assertEqual(rs['histogram'],ys['histogram'])
        self.assertEqual(rs['max_rgb_by_luma'],ys['max_rgb_by_luma'])
        self.assertEqual(rn,yn)
        self.assertEqual(bytes(payload),before)

    def test_rejects_wrong_geometry_payload_noncontiguous_and_roi(self):
        payload = pack709(gray(96,24,32))
        for w,h in ((31,24),(32,0),(False,24),(32,1.5)):
            with self.subTest(w=w,h=h),self.assertRaises(ValueError):
                a.analyze_yuyv_v4(payload,w,h)
        with self.assertRaises(ValueError):a.analyze_yuyv_v4(payload[:-1],32,24)
        with self.assertRaises(ValueError):a.analyze_yuyv_v4(memoryview(payload)[::2],32,12)
        for roi in ((True,0,4,4),(0,0,0,4),(31,0,3,3)):
            with self.subTest(roi=roi),self.assertRaises(ValueError):
                a.analyze_yuyv_v4(payload,32,24,roi)


class TemporalRegression(unittest.TestCase):
    def test_scene_cut_drops_unknown_channel_history(self):
        old,_ = a.analyze_v4(gray(52));new,_ = a.analyze_v4(gray(196))
        c = a.ExposureControllerV4()
        c.update(0,old,sigma(8,8))
        p,r = c.update(40,new,dict(sigma_q8=None,confidence_q8=0,
            uv_sigma_q8=None,uv_confidence_q8=0))
        self.assertTrue(r['scene_reset'])
        self.assertEqual(r['effective_noise'],{})
        self.assertEqual((p['filter_enable'],p['noise_floor'],p['noise_floor_uv']),(0,0,0))
        # Fresh UV evidence on a cut cannot restore obsolete Y history.
        c.update(60,old,sigma(8,8))
        p,r = c.update(80,new,dict(sigma_q8=None,confidence_q8=0,
            uv_sigma_q8=1536,uv_confidence_q8=256))
        self.assertEqual(p['noise_floor'],0)
        self.assertGreater(p['noise_floor_uv'],0)

    def test_unconfident_channel_never_borrows_other_channels_confidence(self):
        stats,_ = a.analyze_v4(gray(52))
        p,r = a.suggest_v4(stats,dict(sigma_q8=2048,confidence_q8=0,
            uv_sigma_q8=1536,uv_confidence_q8=256,filter_sigma_q8=1536,filter_confidence_q8=256))
        self.assertEqual((p['filter_enable'],p['noise_floor'],p['noise_floor_uv']),(1,0,9))
        self.assertEqual(r['noise_gain_ceiling'],384)
        p,_ = a.suggest_v4(stats,dict(sigma_q8=1536,confidence_q8=256,
            uv_sigma_q8=2048,uv_confidence_q8=0))
        self.assertGreater(p['noise_floor'],0)
        self.assertEqual(p['noise_floor_uv'],0)

    def test_weak_noise_does_not_flash_and_unknown_holds_y_and_uv(self):
        stats,_ = a.analyze_v4(gray(52))
        c = a.ExposureControllerV4()
        gains = []
        for i in range(60):
            p,_ = c.update(i*20,stats,sigma(3.9 if i%2 else 4.1,7,128))
            gains.append(p['gain_q8_8'])
        self.assertLessEqual(max(gains)-min(gains),4)
        before,record = c.update(1200,stats,{})
        held = dict(record['effective_noise'])
        for ms in (1240,1260,1300):
            after,r = c.update(ms,stats,sigma(0,0,64))
            self.assertEqual(after,before)
            self.assertEqual(r['effective_noise'],held)
            self.assertTrue(r['noise_held'])
            self.assertTrue(r['filter_noise_held'])
        json.dumps(record)

    def test_pts_ramp_accumulates_sub_code_steps_and_scene_cut_resets(self):
        normal,_ = a.analyze_v4(gray(96));dark,_ = a.analyze_v4(gray(85))
        c = a.ExposureControllerV4()
        c.update(0,normal,sigma(0))
        first,_ = c.update(20,dark,sigma(0))
        for ms in range(40,2020,20):last,_ = c.update(ms,dark,sigma(0))
        self.assertGreater(last['gain_q8_8'],first['gain_q8_8'])
        darker,_ = a.analyze_v4(gray(40))
        cut,record = c.update(2040,darker,sigma(0))
        self.assertTrue(record['scene_reset'])
        self.assertEqual(cut['gain_q8_8'],384)

    def test_invalid_timestamp_noise_no_mutation_reset(self):
        stats,_ = a.analyze_v4(gray(96));c = a.ExposureControllerV4()
        expected,_ = c.update(100,stats,sigma(6,8))
        for ms in (99,-1,False,1.5,float('nan')):
            with self.subTest(ms=ms),self.assertRaises(ValueError):c.update(ms,stats,sigma(0))
        for n in (sigma(-1),sigma(0,0,257),dict(sigma_q8=1.5,confidence_q8=256)):
            with self.subTest(noise=n),self.assertRaises(ValueError):c.update(140,stats,n)
        self.assertEqual(c.update(140,stats,{})[0],expected)
        c.reset();fresh,r = c.update(0,stats,{})
        self.assertEqual(fresh['filter_enable'],0)
        self.assertFalse(r['noise_held'])


if __name__=='__main__':
    unittest.main()
