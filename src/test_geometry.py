import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent/'native'))
import geometry,protocol,reference_v3_frozen,binding
class GeometryTests(unittest.TestCase):
    def test_pc_and_board_limits_agree(self):
        self.assertEqual((geometry.MAX_WIDTH,geometry.MAX_HEIGHT),(protocol.MAX_WIDTH,protocol.MAX_HEIGHT))
        self.assertEqual((reference_v3_frozen.MAX_WIDTH,reference_v3_frozen.MAX_HEIGHT),(1920,1080))
        self.assertEqual(set(geometry.OUTPUT_PRESETS),set(protocol.RICE_GEOMETRIES))
        self.assertEqual(geometry.DEFAULT_OUTPUT,(1920,1080))
    def test_presets_fit_rice_groups(self):
        for w,h in protocol.RICE_GEOMETRIES:
            self.assertEqual(w%128,0);self.assertTrue(geometry.valid(w,h))
    def test_packet_capacity_covers_tans_row_index(self):
        # Rice bound plus the 2-byte P6TANS02 row index (encoder IP 5.0).
        self.assertEqual(binding.wire_capacity(1280,720),1859144)
        self.assertEqual(binding.wire_capacity(1920,1080),4181864)
if __name__=='__main__':unittest.main()
