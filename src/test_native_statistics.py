"""Exact measured histogram/headroom and resulting controller parity, not pixels."""
import unittest
import numpy as np
import exposure_v4 as a
import native_pixels_bridge as b
class StatisticsParity(unittest.TestCase):
    def test_bounded_roi_grid_and_controls_match_frozen_numpy(self):
        self.assertTrue(b.STATISTICS_AVAILABLE)
        rng=np.random.default_rng(20261025)
        for w,h in ((2,1),(4,3),(18,19),(128,96),(1280,720)):
            raw=rng.integers(0,256,w*h*2,dtype=np.uint8).tobytes()
            for rect in (None,(1,0,w-1,h)):
                for budget in (1,7,65536):
                    with self.subTest(w=w,h=h,rect=rect,budget=budget):
                        ref=a.analyze_yuyv_v4(raw,w,h,rect,budget,_native=False)
                        got=a.analyze_yuyv_v4(raw,w,h,rect,budget)
                        self.assertEqual(got,ref)
                        c1=a.ExposureControllerV4();c2=a.ExposureControllerV4()
                        self.assertEqual(c1.update(0,*got),c2.update(0,*ref))
    def test_clipped_levels_and_neutral_chroma_match(self):
        for y in (0,1,16,128,250,255):
            raw=bytes([y,128,y,128])*460800
            self.assertEqual(a.analyze_yuyv_v4(raw,1280,720),a.analyze_yuyv_v4(raw,1280,720,_native=False))
if __name__=='__main__':unittest.main()
