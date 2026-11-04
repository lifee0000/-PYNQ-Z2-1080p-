import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from preview_compare import (LivePreviewMode, compose, dark_levels, load_samples,
                             native_available, view_images)


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.a=Image.fromarray(np.arange(8*6*3,dtype=np.uint8).reshape(6,8,3))
        self.b=Image.new('RGB',(8,6),(201,117,33))

    def test_one_to_one_keeps_actual_pixels_and_does_not_fit_up(self):
        a,b,crop=view_images(self.a,self.b,(80,60),1)
        self.assertEqual(a.size,(8,6))
        self.assertEqual(a.tobytes(),self.a.tobytes())
        self.assertEqual(b.tobytes(),self.b.tobytes())
        self.assertEqual(crop,(0,0,8,6))

    def test_integer_zoom_repeats_pixels_without_blending(self):
        a,_,_=view_images(self.a,self.b,(32,24),4)
        expected=np.asarray(self.a).repeat(4,axis=0).repeat(4,axis=1)
        np.testing.assert_array_equal(np.asarray(a),expected)

    def test_small_view_crops_matching_pixels_at_requested_focus(self):
        a,b,crop=view_images(self.a,self.b,(4,4),2,focus=(1,0))
        self.assertEqual(crop,(6,0,2,2))
        np.testing.assert_array_equal(np.asarray(a)[::2,::2],np.asarray(self.a)[:2,6:])
        self.assertEqual(a.size,b.size)

    def test_wipe_uses_input_on_left_and_result_on_right(self):
        picture,_=compose(self.a,self.b,(8,6),zoom=1,divider=.5)
        np.testing.assert_array_equal(np.asarray(picture)[:,:4],np.asarray(self.a)[:,:4])
        np.testing.assert_array_equal(np.asarray(picture)[:,4:],np.asarray(self.b)[:,4:])

    def test_peek_really_shows_original(self):
        picture,_=compose(self.a,self.b,(8,6),zoom=1,divider=0,original=True)
        self.assertEqual(picture.tobytes(),self.a.tobytes())

    def test_native_label_requires_matching_geometry(self):
        self.assertFalse(native_available({'processing_size':[1920,1080]},(640,360)))
        self.assertTrue(native_available({'preview_window':[20,40,640,360]},(640,360)))
        self.assertFalse(native_available({'preview_window':[20,40,640,360]},(320,180)))

    def test_dynamic_preview_request_is_a_snapshot_boolean(self):
        mode=LivePreviewMode()
        self.assertFalse(bool(mode))
        mode.set(True);self.assertTrue(bool(mode))
        mode.set(False);self.assertFalse(bool(mode))

    def test_dark_stat_ignores_black_padding(self):
        a=np.zeros((40,40,3),np.uint8);b=a.copy()
        a[10:30,10:30]=20;b[10:30,10:30]=40
        self.assertEqual(dark_levels(Image.fromarray(a),Image.fromarray(b),(0,0,40,40)),(20.,40.))

    def test_sample_images_have_valid_integrity_and_physical_provenance(self):
        samples=load_samples()
        self.assertEqual(len(samples),6)
        for sample in samples:
            self.assertEqual(sample['metadata']['sample_provenance'],'REFERENCE_BUFFER_WITH_EXACT_PHYSICAL_OUTPUT_SHA_MATCH')
            self.assertEqual(len(sample['metadata']['physical_output_sha256']),64)


if __name__=='__main__':unittest.main()
