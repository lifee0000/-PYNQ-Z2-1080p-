"""Native ABI bounds and concurrently owned frame buffers, without a board."""
import ctypes as C
from concurrent.futures import ThreadPoolExecutor
import unittest
import numpy as np
import native_pixels_bridge as bridge
from benchmark_pc import frozen_pack_rgb,frozen_unpack_rgb
from pixels import pack_rgb,unpack_rgb

@unittest.skipUnless(bridge.AVAILABLE,'native converter not built on this platform')
class NativePixelBoundaryTests(unittest.TestCase):
    def test_parallel_rows_match_frozen_conversion_at_full_geometry(self):
        rng=np.random.default_rng(20261024)
        for w,h in ((1280,720),(1920,1080),(1920,1079)):
            with self.subTest(geometry=(w,h)):
                rgb=rng.integers(0,256,(h,w,3),dtype=np.uint8)
                packed=pack_rgb(rgb)
                self.assertEqual(packed,frozen_pack_rgb(rgb))
                np.testing.assert_array_equal(unpack_rgb(packed,w,h),frozen_unpack_rgb(packed,w,h))

    def test_abi_rejects_invalid_or_overlapping_buffers_before_writing(self):
        src=(C.c_ubyte*64)(*range(64));dst=(C.c_ubyte*64)(*([165]*64))
        for operation,n,m in (('p4_pack',36,24),('p4_unpack',24,36)):
            f=getattr(bridge._lib,operation)
            for sp,sn,dp,dn,w,h in ((None,n,dst,m,4,3),(src,n-1,dst,m,4,3),
                (src,n,dst,m-1,4,3),(src,n,src,m,4,3),
                (src,n,dst,m,3,3),(src,n,dst,m,1282,720)):
                self.assertLess(f(sp,sn,dp,dn,w,h),0)
                self.assertEqual(bytes(dst),bytes([165])*64)
            self.assertEqual(f(src,n,dst,m,4,3),0)
            self.assertEqual(bytes(dst)[m:],bytes([165])*(64-m))
            C.memset(dst,165,64)

    def test_concurrent_sender_and_preview_have_no_shared_frame_workspace(self):
        rng=np.random.default_rng(20261023)
        cases=[rng.integers(0,256,(19,32+2*i,3),dtype=np.uint8) for i in range(8)]
        expected=[frozen_pack_rgb(a) for a in cases]
        def run(index):
            for _ in range(30):
                packed=pack_rgb(cases[index]);self.assertEqual(packed,expected[index])
                np.testing.assert_array_equal(unpack_rgb(packed,cases[index].shape[1],19),
                    frozen_unpack_rgb(expected[index],cases[index].shape[1],19))
        with ThreadPoolExecutor(max_workers=8) as executor:
            list(executor.map(run,range(8)))

if __name__=='__main__':unittest.main()
