import unittest
from dataclasses import replace
import numpy as np
import reference as v4
import reference_v3_frozen as v3
import pixels


class SpatialV4Tests(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(20261023)
        self.p=v4.Params(mode=5,noise_floor=8,noise_floor_uv=8,knee_out=255,soft_q8_8=256)

    def make(self,h=21,w=32,y=96,u=128,v=128):
        frame=np.empty((h,w,2),np.uint8);frame[:,:,0]=y
        frame[:,0::2,1]=u;frame[:,1::2,1]=v
        return frame

    def process(self,frame,p=None):
        h,w=frame.shape[:2]
        return v4.unpack(v4.enhance(frame.tobytes(),w,h,p or self.p),w,h)

    def test_modes_zero_through_four_exact_legacy(self):
        for mode in range(5):
            for roi in (False,True):
                raw=self.rng.integers(0,256,(9,14,2),dtype=np.uint8).tobytes()
                p=replace(self.p,mode=mode,roi_enable=int(roi),roi_x=1,roi_y=1,roi_width=11,roi_height=7)
                self.assertEqual(v4.enhance(raw,14,9,p),v3.enhance(raw,14,9,p))

    def test_filter_off_exact_legacy(self):
        raw=self.rng.integers(0,256,(9,14,2),dtype=np.uint8).tobytes()
        p=replace(self.p,filter_enable=0,gain_q8_8=350,brightness=9)
        self.assertEqual(v4.enhance(raw,14,9,p),v3.enhance(raw,14,9,p))

    def test_no_chroma_cross_talk(self):
        frame=self.make(u=20,v=235)
        np.testing.assert_array_equal(self.process(frame),frame)

    def test_constant_black_white_and_colour_unchanged(self):
        for y in (0,1,127,254,255):
            for u,v in ((0,255),(255,0),(128,128)):
                frame=self.make(y=y,u=u,v=v)
                np.testing.assert_array_equal(self.process(frame),frame)

    def test_isolated_luma_pulse_removed(self):
        frame=self.make();frame[10,14,0]=255
        out=self.process(frame)
        self.assertEqual(int(out[10,14,0]),96)
        np.testing.assert_array_equal(out[:,:,1],frame[:,:,1])

    def test_isolated_chroma_pair_pulse_removed(self):
        frame=self.make();frame[10,14,1]=0;frame[10,15,1]=255
        out=self.process(frame)
        self.assertEqual((int(out[10,14,1]),int(out[10,15,1])),(128,128))
        np.testing.assert_array_equal(out[:,:,0],frame[:,:,0])

    def test_connected_luma_lines_preserved(self):
        for diagonal in (False,True):
            frame=self.make(y=35)
            if diagonal:
                for y in range(21):frame[y,y,0]=210
            else:frame[:,14,0]=210
            np.testing.assert_array_equal(self.process(frame),frame)

    def test_connected_chroma_lines_preserved(self):
        frame=self.make();frame[:,14,1]=220;frame[:,15,1]=30
        np.testing.assert_array_equal(self.process(frame),frame)

    def test_checker_and_high_contrast_colour_boundaries(self):
        frame=self.make()
        yy,xx=np.indices(frame.shape[:2]);frame[:,:,0]=np.where((xx+yy)%2,210,35)
        frame[:,0:16:2,1]=30;frame[:,1:16:2,1]=220
        frame[:,16::2,1]=220;frame[:,17::2,1]=30
        np.testing.assert_array_equal(self.process(frame),frame)

    def test_y_edge_blocks_uv_blending(self):
        frame=self.make(y=25,u=128,v=128)
        frame[:,16:,0]=200
        # Small UV difference would normally be mixed, but the Y discontinuity gates it.
        frame[:,16::2,1]=136;frame[:,17::2,1]=120
        np.testing.assert_array_equal(self.process(frame),frame)

    def test_random_flat_luma_and_chroma_noise_reduced(self):
        clean=self.make(96,128)
        noisy=np.clip(clean.astype(np.int32)+self.rng.normal(0,4,clean.shape).round().astype(np.int32),0,255).astype(np.uint8)
        out=self.process(noisy)
        for channel in (0,1):
            mse_in=np.mean((noisy[2:-2,4:-4,channel].astype(float)-clean[2:-2,4:-4,channel])**2)
            mse_out=np.mean((out[2:-2,4:-4,channel].astype(float)-clean[2:-2,4:-4,channel])**2)
            self.assertLess(mse_out,mse_in*.55)

    def test_impulse_does_not_reinsert_original_residual(self):
        frame=self.make();frame[10,14,0]=255
        out=self.process(frame,replace(self.p,sharp_q8_8=1024,detail_limit=255))
        self.assertEqual(int(out[10,14,0]),96)

    def test_impulse_requires_neighbour_consensus(self):
        frame=self.make();frame[10,14,0]=255;frame[9,13,0]=0
        # Neighbours now have spread 96 > 2*sigma, so the pulse rule must not fire.
        out=self.process(frame)
        self.assertEqual(int(out[10,14,0]),255)

    def test_uv_impulse_requires_flat_luma(self):
        frame=self.make();frame[10,14,1]=0;frame[10,15,1]=255
        frame[9,12,0]=230;frame[9,13,0]=230
        out=self.process(frame)
        self.assertEqual((int(out[10,14,1]),int(out[10,15,1])),(0,255))

    def test_roi_preserves_outside_and_partial_chroma_pairs(self):
        frame=self.make();frame[5,0,1]=0;frame[5,1,1]=255;frame[5,6,1]=0;frame[5,7,1]=255
        p=replace(self.p,roi_enable=1,roi_x=1,roi_y=1,roi_width=27,roi_height=18)
        out=self.process(frame,p)
        self.assertEqual((int(out[5,0,1]),int(out[5,1,1])),(0,255))
        self.assertEqual((int(out[5,6,1]),int(out[5,7,1])),(128,128))
        np.testing.assert_array_equal(out[:,28:],frame[:,28:])
        np.testing.assert_array_equal(out[0],frame[0])

    def test_roi_edge_replication_no_padding_bleed(self):
        frame=self.make(y=0,u=0,v=255)
        frame[2:18,4:28,0]=96;frame[2:18,4:28,1]=128
        p=replace(self.p,roi_enable=1,roi_x=4,roi_y=2,roi_width=24,roi_height=16)
        np.testing.assert_array_equal(self.process(frame,p),frame)

    def test_width_four_and_single_complete_roi_pair(self):
        frame=self.make(3,4,u=20,v=230)
        p=replace(self.p,roi_enable=1,roi_x=1,roi_y=0,roi_width=3,roi_height=3)
        np.testing.assert_array_equal(self.process(frame,p),frame)

    def test_v3_reference_frozen_identity(self):
        import hashlib
        from pathlib import Path
        digest=hashlib.sha256(Path(v3.__file__).read_bytes()).hexdigest()
        # 1080p build: only the geometry bound now comes from geometry.py (was
        # 1280x720). Every pixel rule is unchanged; all 148 earlier HLS golden
        # vectors regenerate byte-identically from it.
        self.assertEqual(digest,"41e68fbe76e4207b50cc6b9301e7a05f92fa1c55cfe9352af8e3e449cbd05110")

    def test_strong_chroma_sigma_does_not_erase_clean_weak_luma_texture(self):
        frame=self.make(48,64)
        yy,xx=np.indices(frame.shape[:2]);frame[:,:,0]=np.where((xx+yy)%2,101,91)
        frame[:,:,1]=np.clip(128+self.rng.normal(0,10,frame.shape[:2]).round(),0,255).astype(np.uint8)
        p=replace(self.p,noise_floor=1,noise_floor_uv=20)
        out=self.process(frame,p)
        np.testing.assert_array_equal(out[:,:,0],frame[:,:,0])
        before=np.mean((frame[2:-2,4:-4,1].astype(float)-128)**2)
        after=np.mean((out[2:-2,4:-4,1].astype(float)-128)**2)
        self.assertLess(after,before*.55)

    def test_separate_sigma_changes_only_corresponding_plane(self):
        frame=self.rng.integers(80,140,(24,32,2),dtype=np.uint8)
        a=self.process(frame,replace(self.p,noise_floor=2,noise_floor_uv=2))
        b=self.process(frame,replace(self.p,noise_floor=2,noise_floor_uv=20))
        np.testing.assert_array_equal(a[:,:,0],b[:,:,0])
        self.assertGreater(np.count_nonzero(a[:,:,1]!=b[:,:,1]),0)

    def test_invalid_separate_uv_sigma_rejected(self):
        frame=self.make()
        for value in (-1,256,2.0,True):
            with self.assertRaises(ValueError):self.process(frame,replace(self.p,noise_floor_uv=value))

    def test_uv_only_keeps_weak_luma_gradient_exact(self):
        frame=self.make(48,64)
        yy,xx=np.indices(frame.shape[:2]);frame[:,:,0]=80+xx//4+(yy%5)
        frame[:,:,1]=np.clip(128+self.rng.normal(0,10,frame.shape[:2]).round(),0,255).astype(np.uint8)
        p=replace(self.p,noise_floor=0,noise_floor_uv=20)
        out=self.process(frame,p)
        np.testing.assert_array_equal(out[:,:,0],frame[:,:,0])
        self.assertLess(np.mean((out[2:-2,4:-4,1].astype(float)-128)**2),
                        np.mean((frame[2:-2,4:-4,1].astype(float)-128)**2)*.55)

    def test_zero_luma_sigma_still_applies_exposure(self):
        frame=self.make();frame[10,14,0]=255
        p=replace(self.p,noise_floor=0,noise_floor_uv=0,gain_q8_8=320,brightness=8)
        self.assertEqual(v4.enhance(frame.tobytes(),32,21,p),
            v3.enhance(frame.tobytes(),32,21,replace(p,mode=3)))

    def test_zero_uv_sigma_bypasses_all_chroma(self):
        frame=self.rng.integers(0,256,(24,32,2),dtype=np.uint8)
        out=self.process(frame,replace(self.p,noise_floor_uv=0))
        np.testing.assert_array_equal(out[:,:,1],frame[:,:,1])


class OvershootTests(unittest.TestCase):
    """Enhance IP 1.1 halo control: mode 4 luma within the 3x3 input range +/- overshoot."""
    def setUp(self):
        rng=np.random.default_rng(5)
        yy,xx=np.indices((20,30))
        y=np.where((xx%7<2)|(yy==9),40,200).astype(np.int32)
        y=(2*y+np.roll(y,1,1)+np.roll(y,-1,1)+2)//4    # soft strokes, like upscaled text
        self.frame=np.stack([y.astype(np.uint8),rng.integers(0,256,y.shape,dtype=np.uint8)],2)
        self.p=v4.Params(mode=4,filter_enable=1,sharp_q8_8=960,detail_limit=32,noise_floor=1)

    def run_p(self,p):
        return np.frombuffer(v4.enhance(self.frame.tobytes(),30,20,p),np.uint8).reshape(20,30,2)

    def bounds(self):
        padded=np.pad(self.frame[:,:,0].astype(np.int32),1,mode="edge")
        stack=np.stack([padded[r:r+20,c:c+30] for r in range(3) for c in range(3)])
        return stack.min(0),stack.max(0)

    def test_255_is_the_earlier_output(self):
        self.assertEqual(v4.Params().overshoot,255)
        np.testing.assert_array_equal(self.run_p(self.p),self.run_p(replace(self.p,overshoot=255)))

    def test_mode4_stays_within_range_plus_margin(self):
        low,high=self.bounds();inner=(slice(1,-1),slice(1,-1))
        free=self.run_p(self.p)[:,:,0].astype(np.int32)
        self.assertGreater(int(np.maximum(free-high,0)[inner].max()),20)   # unclamped halo
        for m in (0,1,4):
            out=self.run_p(replace(self.p,overshoot=m))
            y=out[:,:,0].astype(np.int32)
            self.assertTrue(np.all(y[inner]<=high[inner]+m) and np.all(y[inner]>=low[inner]-m))
            np.testing.assert_array_equal(out[:,:,1],self.frame[:,:,1])         # chroma untouched
            np.testing.assert_array_equal(y[0],self.frame[0,:,0])               # border bypass
            changed=y!=free
            # Only pixels beyond the bounds (or, IP 1.3, above their colour ceiling) change,
            # and only down to that bound.
            padded=np.pad(self.frame[:,:,0].astype(np.int32),1,mode="edge")
            k=((1,2,1),(2,4,2),(1,2,1))
            base=(sum(k[r][c]*padded[r:r+20,c:c+30] for r in range(3) for c in range(3))+8)>>4
            capped=np.minimum(np.clip(free,low-m,high+m),np.maximum(v4._colour_ceiling(self.frame),base))
            np.testing.assert_array_equal(y[changed],capped[changed])

    def test_roi_clamps_inside_roi_only(self):
        p=replace(self.p,overshoot=0,roi_enable=1,roi_x=3,roi_y=2,roi_width=21,roi_height=13)
        out=self.run_p(p)[:,:,0];free=self.run_p(replace(p,overshoot=255))[:,:,0]
        outside=np.ones((20,30),bool);outside[2:15,3:24]=False
        np.testing.assert_array_equal(out[outside],free[outside])
        self.assertTrue(np.any(out!=free))

    def test_modes_0_to_3_ignore_overshoot(self):
        rng=np.random.default_rng(9)
        for mode in (0,1,2,3):
            for filter_enable in (0,1):
                p=v4.Params(mode=mode,filter_enable=filter_enable,sharp_q8_8=1024,noise_floor=int(rng.integers(0,20)),
                            gain_q8_8=400,brightness=-20,knee_out=150,soft_q8_8=64,detail_limit=255)
                np.testing.assert_array_equal(self.run_p(replace(p,overshoot=0)),self.run_p(p))

    def test_mode5_sharp_has_no_effect(self):
        # Why mode 5 needs no clamp: its detail term never passes the 2 sigma gate.
        rng=np.random.default_rng(13)
        for _ in range(200):
            f=np.clip(128+rng.integers(-40,41,(7,10,2)),0,255).astype(np.uint8)
            p=v4.Params(mode=5,filter_enable=int(rng.integers(0,2)),noise_floor=int(rng.integers(0,40)),
                        detail_limit=255,gain_q8_8=int(rng.integers(0,1025)),knee_out=255,soft_q8_8=256)
            self.assertEqual(v4.enhance(f.tobytes(),10,7,replace(p,sharp_q8_8=0)),v4.enhance(f.tobytes(),10,7,replace(p,sharp_q8_8=1024)))

    def test_overshoot_range_is_validated(self):
        for value in (-1,256):
            with self.assertRaises(ValueError):replace(self.p,overshoot=value).validate(30,20)


class Mode5SharpenTests(unittest.TestCase):
    """Enhance IP 1.2: mode 5 adds a cored 5x5 detail term while overshoot < 255."""
    def setUp(self):
        rng=np.random.default_rng(21)
        yy,xx=np.indices((24,36))
        soft=np.where((xx//6+yy//6)%2,170,70).astype(np.float64)
        for _ in range(2):soft=(np.roll(soft,1,0)+np.roll(soft,-1,0)+np.roll(soft,1,1)+np.roll(soft,-1,1)+4*soft)/8
        self.y=np.clip(soft+rng.normal(0,1.2,soft.shape),0,255).astype(np.uint8)
        self.frame=np.stack([self.y,rng.integers(0,256,self.y.shape,dtype=np.uint8)],2)
        self.p=v4.Params(mode=5,filter_enable=1,noise_floor=2,noise_floor_uv=0,sharp_q8_8=512,detail_limit=24,
                         gain_q8_8=300,knee_out=230,soft_q8_8=128,overshoot=1)

    def run_p(self,p,frame=None):
        f=self.frame if frame is None else frame
        h,w=f.shape[:2]
        return np.frombuffer(v4.enhance(f.tobytes(),w,h,p),np.uint8).reshape(h,w,2)

    def test_255_keeps_the_earlier_mode5(self):
        np.testing.assert_array_equal(self.run_p(replace(self.p,overshoot=255)),self.run_p(replace(self.p,overshoot=255,sharp_q8_8=0)))

    def test_soft_edges_get_steeper_within_the_toned_range(self):
        old=self.run_p(replace(self.p,overshoot=255))[:,:,0].astype(np.int32)
        for filter_enable,noise in ((1,2),(0,2),(1,0)):
            p=replace(self.p,filter_enable=filter_enable,noise_floor=noise)
            new=self.run_p(p)[:,:,0].astype(np.int32);ref=self.run_p(replace(p,overshoot=255))[:,:,0].astype(np.int32)
            lap=lambda a:np.abs(4*a[1:-1,1:-1]-a[:-2,1:-1]-a[2:,1:-1]-a[1:-1,:-2]-a[1:-1,2:]).mean()
            self.assertGreater(lap(new),1.1*lap(ref))
            padded=np.pad(self.y.astype(np.int32),1,mode="edge")
            stack=np.stack([padded[r:r+24,c:c+36] for r in range(3) for c in range(3)])
            low,high=v4._tone(stack.min(0),p)-1,v4._tone(stack.max(0),p)+1
            inner=(slice(1,-1),slice(1,-1))
            self.assertTrue(np.all(new[inner]>=low[inner]) and np.all(new[inner]<=high[inner]))
        self.assertTrue(np.any(old!=self.run_p(self.p)[:,:,0]))

    def test_two_pixel_border_is_unchanged(self):
        new=self.run_p(self.p)[:,:,0];old=self.run_p(replace(self.p,overshoot=255))[:,:,0]
        ring=np.ones_like(new,dtype=bool);ring[2:-2,2:-2]=False
        np.testing.assert_array_equal(new[ring],old[ring])
        p=replace(self.p,roi_enable=1,roi_x=3,roi_y=2,roi_width=27,roi_height=17)
        new=self.run_p(p)[:,:,0];old=self.run_p(replace(p,overshoot=255))[:,:,0]
        keep=np.ones_like(new,dtype=bool);keep[4:17,5:28]=False
        np.testing.assert_array_equal(new[keep],old[keep])
        self.assertTrue(np.any(new!=old))

    def test_noise_below_sigma_is_not_sharpened(self):
        rng=np.random.default_rng(3)
        flat=np.stack([(100+rng.integers(-1,2,(24,36))).astype(np.uint8),np.full((24,36),128,np.uint8)],2)
        for filter_enable in (0,1):
            p=replace(self.p,filter_enable=filter_enable,noise_floor=3)
            np.testing.assert_array_equal(self.run_p(p,flat),self.run_p(replace(p,overshoot=255),flat))

    def test_chroma_is_untouched_by_the_detail_term(self):
        np.testing.assert_array_equal(self.run_p(self.p)[:,:,1],self.run_p(replace(self.p,overshoot=255))[:,:,1])


class ColourCeilingTests(unittest.TestCase):
    """Enhance IP 1.3: sharpening raises luma only up to where an RGB channel would clip."""
    def setUp(self):
        rng=np.random.default_rng(13)
        yy,xx=np.indices((24,36))
        y=np.where((xx//5+yy//7)%2,140,60).astype(np.float64)
        y=(np.roll(y,1,1)+2*y+np.roll(y,-1,1))/4
        self.y=np.clip(y+rng.normal(0,1,y.shape),0,255).astype(np.uint8)
        # Saturated orange/red chroma (V high, U low), like Tokyo's signs.
        c=np.empty_like(self.y);c[:,0::2]=rng.integers(60,90,(24,18));c[:,1::2]=rng.integers(195,216,(24,18))
        self.frame=np.stack([self.y,c],2);self.neutral=np.stack([self.y,np.full_like(self.y,128)],2)
        self.p4=v4.Params(mode=4,filter_enable=1,sharp_q8_8=960,detail_limit=32,noise_floor=1,overshoot=1)
        self.p5=v4.Params(mode=5,filter_enable=1,noise_floor=2,noise_floor_uv=0,sharp_q8_8=768,detail_limit=40,
                          gain_q8_8=256,knee_out=255,soft_q8_8=256,overshoot=1)

    def run_p(self,p,f):
        return np.frombuffer(v4.enhance(f.tobytes(),36,24,p),np.uint8).reshape(24,36,2)

    @staticmethod
    def overflow(f):
        y=f[:,:,0].astype(np.int32);u=np.repeat(f[:,0::2,1].astype(np.int32)-128,2,1);v=np.repeat(f[:,1::2,1].astype(np.int32)-128,2,1)
        return np.maximum(np.maximum(y+((103206*v+32768)>>16),y+((121609*u+32768)>>16)),y-((12276*u+30679*v+32768)>>16))-255

    def test_ceiling_matches_the_frozen_unpack(self):
        ceiling=v4._colour_ceiling(self.frame)
        for delta in (0,1):
            f=self.frame.copy();f[:,:,0]=np.clip(ceiling+delta,0,255)
            rgb=pixels.unpack_rgb_numpy(f.tobytes(),36,24).astype(np.int32)
            over=self.overflow(f)
            self.assertTrue(np.all(over<=0) if delta==0 else np.all(over[ceiling<255]==1))
            if delta==0:self.assertTrue(np.all(rgb.max(2)[ceiling<255]==255))

    def test_neutral_chroma_is_unchanged(self):
        self.assertTrue(np.all(v4._colour_ceiling(self.neutral)==255))
        for p in (self.p4,self.p5):
            free=self.run_p(p,self.neutral)
            orig=v4._colour_ceiling
            try:
                v4._colour_ceiling=lambda s:np.full(s.shape[:2],255,np.int32)
                np.testing.assert_array_equal(free,self.run_p(p,self.neutral))
            finally:v4._colour_ceiling=orig

    def test_sharpening_no_longer_clips_saturated_colour(self):
        inner=(slice(2,-2),slice(2,-2))
        for p in (self.p4,self.p5):
            out=self.run_p(p,self.frame)
            orig=v4._colour_ceiling
            try:
                v4._colour_ceiling=lambda s:np.full(s.shape[:2],10**6,np.int32);free=self.run_p(p,self.frame)
            finally:v4._colour_ceiling=orig
            src=self.overflow(self.frame)
            self.assertGreater(int(((self.overflow(free)>0)&(src<=0))[inner].sum()),20,p.mode)   # it did clip
            self.assertEqual(int(((self.overflow(out)>0)&(src<=0))[inner].sum()),0,p.mode)
            np.testing.assert_array_equal(out[:,:,1],free[:,:,1])
            self.assertTrue(np.all(out[:,:,0]<=free[:,:,0]))          # only lowers, never raises
            lap=lambda a:np.abs(4*a[1:-1,1:-1]-a[:-2,1:-1]-a[2:,1:-1]-a[1:-1,:-2]-a[1:-1,2:]).mean()
            old=self.run_p(replace(p,overshoot=255,sharp_q8_8=0 if p.mode==5 else p.sharp_q8_8),self.frame)
            self.assertGreater(lap(out[:,:,0].astype(np.int32)),lap(self.frame[:,:,0].astype(np.int32)))  # still sharper

    def test_255_keeps_the_ip11_output(self):
        orig=v4._colour_ceiling
        for p in (self.p4,self.p5):
            p=replace(p,overshoot=255)
            a=self.run_p(p,self.frame)
            try:
                v4._colour_ceiling=lambda s:np.zeros(s.shape[:2],np.int32);b=self.run_p(p,self.frame)
            finally:v4._colour_ceiling=orig
            np.testing.assert_array_equal(a,b)


if __name__=="__main__":unittest.main()
