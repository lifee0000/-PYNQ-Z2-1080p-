import unittest
import av,numpy as np
import io
from media_frame import fit_rgb,export_frame,tag_bt709
class FrameFitTests(unittest.TestCase):
    def test_full_geometry_preserves_rgb_pixels(self):
        rgb=np.random.default_rng(62).integers(0,256,(720,1280,3),dtype=np.uint8)
        got,rect=fit_rgb(av.VideoFrame.from_ndarray(rgb,format='rgb24'),1280,720)
        self.assertIsNone(rect);np.testing.assert_array_equal(got,rgb)
    def test_default_is_1080p_and_full_1080p_is_untouched(self):
        rgb=np.random.default_rng(63).integers(0,256,(1080,1920,3),dtype=np.uint8)
        got,rect=fit_rgb(av.VideoFrame.from_ndarray(rgb,format='rgb24'))
        self.assertIsNone(rect);np.testing.assert_array_equal(got,rgb)
        got,rect=fit_rgb(av.VideoFrame.from_ndarray(rgb[:720,:1280].copy(),format='rgb24'))
        self.assertEqual(rect,(0,0,1920,1080));self.assertEqual(got.shape,(1080,1920,3))
    def test_portrait_letterbox_has_no_stretched_content_or_padding_signal(self):
        src=np.full((960,544,3),[50,90,150],np.uint8)
        got,rect=fit_rgb(av.VideoFrame.from_ndarray(src,format='rgb24'),1280,720)
        self.assertEqual(rect,(436,0,408,720));self.assertEqual(got.shape,(720,1280,3))
        self.assertTrue(np.all(got[:,:436]==0));self.assertTrue(np.all(got[:,844:]==0))
        self.assertLessEqual(int(np.abs(got[4:-4,440:840].astype(int)-[50,90,150]).max()),1)
    def test_export_is_bt709_tagged_and_round_trips_colours(self):
        # Saturated 64x64 patches: an untagged BT.601 export read as BT.709 was off ~6.7 levels.
        blocks=np.random.default_rng(64).integers(0,256,(5,6,3),dtype=np.uint8)
        rgb=np.repeat(np.repeat(blocks,64,0),64,1)[:288,:384].copy()
        buf=io.BytesIO()
        with av.open(buf,'w',format='mp4') as out:
            s=out.add_stream('libx264',rate=25);s.width,s.height,s.pix_fmt=384,288,'yuv420p'
            s.options={'crf':'0','preset':'veryfast','bf':'0'};tag_bt709(s)
            vf=export_frame(rgb);vf.pts=0
            for p in s.encode(vf):out.mux(p)
            for p in s.encode():out.mux(p)
        with av.open(io.BytesIO(buf.getvalue())) as inp:
            f=next(inp.decode(video=0))
            self.assertEqual((int(f.colorspace),int(f.color_range)),(1,1))
            got=f.to_ndarray(format='rgb24')[32::64,32::64].astype(int)
        self.assertLessEqual(float(np.abs(got-rgb[32::64,32::64]).mean()),2.)
        self.assertEqual(export_frame(rgb,(192,144)).width,192)
if __name__=='__main__':unittest.main()
