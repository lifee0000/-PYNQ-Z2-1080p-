"""Fast Rice03 and MOCK Rice02 must match untouched references byte for byte."""
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
from pathlib import Path
import random
import unittest

try:
    from . import rice_codec
except ImportError:
    import rice_codec


ROOT = Path(__file__).resolve().parents[2]


class RiceFastTests(unittest.TestCase):
    MINIMUM_HEIGHT = 3

    @classmethod
    def setUpClass(cls):
        cls.lib = rice_codec._lib()
        cls.fast = cls.lib.p6_rice03_encode_near
        cls.reference = cls.lib.p6_rice03_encode_near_reference
        cls.reference.argtypes = cls.fast.argtypes
        cls.reference.restype = C.c_int
        cls.lossless = cls.lib.p6_rice03_encode

    # Rice03 exports take the band count (one per FPGA decoder) and the method
    # (3 = layout 2, what the FPGA decodes; 1 = layout 1); Rice02 mocks do not.
    METHOD = 3
    EXTRA = (3, METHOD)

    def encode(self, function, raw, width, height, shift, extra=None):
        capacity = rice_codec.wire_capacity(width, height)
        # Guard the exported buffer on both sides, including maximum-size raw
        # groups and packets whose last byte contains padding bits.
        target = C.create_string_buffer(b'\xa5' * (capacity + 32), capacity + 32)
        size = function(C.c_char_p(raw), len(raw), C.byref(target, 16), capacity,
                        shift, width, height, *(self.EXTRA if extra is None else extra))
        self.assertGreater(size, 0)
        self.assertLessEqual(size, capacity)
        self.assertEqual(target.raw[:16], b'\xa5' * 16)
        self.assertEqual(target.raw[16 + size:], b'\xa5' * (capacity + 16 - size))
        return target.raw[16:16 + size]

    def assert_matches(self, raw, width, height, shift):
        self.assertEqual(self.encode(self.fast, raw, width, height, shift),
                         self.encode(self.reference, raw, width, height, shift))

    def test_both_complete_corpora_all_near_shifts(self):
        for name, width, height, expected_frames in (
            ('rice_corpus_1080p.bin', 1920, 1080, 5),
            ('rice_corpus.bin', 1280, 720, 9),
        ):
            corpus = (ROOT / 'hardware' / 'hls' / name).read_bytes()
            count = int.from_bytes(corpus[:4], 'little')
            self.assertEqual(count, expected_frames)
            size = width * height * 2
            self.assertEqual(len(corpus), 4 + count * size)
            for frame in range(count):
                raw = corpus[4 + frame * size:4 + (frame + 1) * size]
                for shift in (1, 2, 3):
                    with self.subTest(geometry=(width, height), frame=frame, shift=shift):
                        self.assert_matches(raw, width, height, shift)

    def test_lossless_fast_encoder_matches_lossless_reference(self):
        # Shift 0 runs the table-driven encoder; with method 1 it must equal
        # p6_rice03_encode, the untouched layout-1 reference.
        if not self.EXTRA:
            self.skipTest('Rice02 lossless mock keeps its own encoder')
        size = 1920 * 1080 * 2
        corpus = (ROOT / 'hardware' / 'hls' / 'rice_corpus_1080p.bin').read_bytes()
        frames = [corpus[4 + i * size:4 + (i + 1) * size] for i in range(5)]
        frames.append(random.Random(604).randbytes(size))
        capacity = rice_codec.wire_capacity(1920, 1080)
        for i, raw in enumerate(frames):
            for bands in (3, 4):
                with self.subTest(frame=i, bands=bands):
                    target = C.create_string_buffer(capacity)
                    n = self.lossless(C.c_char_p(raw), len(raw), target, capacity, 1920, 1080, bands)
                    self.assertGreater(n, 0)
                    self.assertEqual(self.encode(self.fast, raw, 1920, 1080, 0, (bands, 1)), target.raw[:n])

    def test_four_bands_match_reference_and_decode(self):
        if not self.EXTRA:
            self.skipTest('Rice02 is a single band')
        corpus = (ROOT / 'hardware' / 'hls' / 'rice_corpus_1080p.bin').read_bytes()
        size = 1920 * 1080 * 2
        for frame in (0, 3):
            raw = corpus[4 + frame * size:4 + (frame + 1) * size]
            for shift in (0, 3):
                with self.subTest(frame=frame, shift=shift):
                    packet = self.encode(self.fast, raw, 1920, 1080, shift, (4, self.METHOD))
                    self.assertEqual(packet, self.encode(self.reference, raw, 1920, 1080, shift, (4, self.METHOD)))
                    self.assertEqual((packet[16], packet[17]), (self.METHOD, 4))
                    restored = C.create_string_buffer(size)
                    self.assertEqual(self.lib.p6_rice_decode(C.c_char_p(packet), len(packet), restored, size, 3), size)
                    if shift == 0:
                        self.assertEqual(restored.raw, raw)
        target = C.create_string_buffer(rice_codec.wire_capacity(128, 5))
        for bands in (2, 5):
            self.assertEqual(self.fast(C.c_char_p(bytes(128 * 5 * 2)), 128 * 5 * 2, target, len(target), 3, 128, 5, bands, 3), -1)
        for method in (0, 2, 4):
            self.assertEqual(self.fast(C.c_char_p(bytes(128 * 5 * 2)), 128 * 5 * 2, target, len(target), 3, 128, 5, 3, method), -1)

    def test_predictor_boundaries_extremes_and_incompressible_groups(self):
        rng = random.Random(6031080)
        # Three rows give one row per slice; 4/5/11 expose unequal slice sizes.
        for width, height in ((128, 3), (128, 4), (128, 5), (256, 11), (1920, 7)):
            size = width * height * 2
            patterns = (bytes(size), b'\xff' * size, b'\x00\xff' * (size // 2),
                        bytes(range(256)) * (size // 256), rng.randbytes(size))
            for pattern, raw in enumerate(patterns):
                for shift in (1, 2, 3):
                    with self.subTest(geometry=(width, height), pattern=pattern, shift=shift):
                        self.assert_matches(raw, width, height, shift)

    def test_independent_concurrent_calls(self):
        raw = random.Random(603).randbytes(256 * 13 * 2)
        expected = {shift: self.encode(self.reference, raw, 256, 13, shift) for shift in (1, 2, 3)}
        with ThreadPoolExecutor(max_workers=4) as pool:
            shifts = [1, 2, 3] * 4
            actual = list(pool.map(lambda shift: self.encode(self.fast, raw, 256, 13, shift), shifts))
        for shift, packet in zip(shifts, actual):
            self.assertEqual(packet, expected[shift])

    def test_shift_zero_keeps_existing_lossless_path(self):
        if self.METHOD != 1:
            self.skipTest('the layout-1 lossless reference only covers method 1')
        raw = random.Random(600).randbytes(128 * 5 * 2)
        capacity = rice_codec.wire_capacity(128, 5)
        target = C.create_string_buffer(capacity)
        size = self.lossless(C.c_char_p(raw), len(raw), target, capacity, 128, 5, *self.EXTRA[:1])
        self.assertGreater(size, 0)
        self.assertEqual(self.encode(self.fast, raw, 128, 5, 0), target.raw[:size])
        self.assertEqual(self.encode(self.reference, raw, 128, 5, 0), target.raw[:size])

    def test_shift_zero_matches_reference(self):
        rng = random.Random(601)
        for raw in (rng.randbytes(128 * 5 * 2), bytes(128 * 5 * 2), bytes(range(256)) * 5):
            self.assertEqual(self.encode(self.fast, raw, 128, 5, 0), self.encode(self.reference, raw, 128, 5, 0))

    def test_invalid_arguments_match_reference_and_leave_destination_untouched(self):
        raw = bytes(128 * 3 * 2)
        capacity = rice_codec.wire_capacity(128, 3)
        cases = (
            (None, len(raw), capacity, 3, 128, 3, -1),
            (raw, len(raw) - 1, capacity, 3, 128, 3, -1),
            (raw, len(raw), capacity - 1, 3, 128, 3, -1),
            (raw, len(raw), capacity, 4, 128, 3, -1),
            (raw, len(raw), capacity, 3, 127, 3, -1),
            (raw, len(raw), capacity, 3, 2048, 3, -1),
            (raw, len(raw), capacity, 3, 128, 0, -1),
            (raw, len(raw), capacity, 3, 128, 1081, -1),
            (raw, len(raw), capacity, 3, -128, 3, -1),
        )
        for function in (self.fast, self.reference):
            for source, size, available, shift, width, height, expected in cases:
                with self.subTest(function=function.__name__, geometry=(width, height), shift=shift, size=size, capacity=available):
                    target = C.create_string_buffer(b'\xa5' * capacity, capacity)
                    self.assertEqual(function(C.c_char_p(source) if source is not None else None,
                                              size, target, available, shift, width, height, *self.EXTRA), expected)
                    self.assertEqual(target.raw, b'\xa5' * capacity)
            self.assertEqual(function(C.c_char_p(raw), len(raw), None, capacity, 3, 128, 3, *self.EXTRA), -1)
            for height in range(1, self.MINIMUM_HEIGHT):
                target = C.create_string_buffer(capacity)
                self.assertEqual(function(C.c_char_p(raw), 128 * height * 2,
                                          target, capacity, 3, 128, height, *self.EXTRA), -3)


class RiceFastLayoutOneTests(RiceFastTests):
    METHOD = 1
    EXTRA = (3, METHOD)


class LayoutTwoTests(unittest.TestCase):
    """Layout 2 (full-resolution luma, zero groups) on the real corpus: smaller
    than layout 1, exact when lossless, within step/2 otherwise."""
    def test_layout_two_is_smaller_and_round_trips(self):
        corpus = (ROOT / 'hardware' / 'hls' / 'rice_corpus_1080p.bin').read_bytes()
        size = 1920 * 1080 * 2
        for frame in (0, 1, 2):
            raw = corpus[4 + frame * size:4 + (frame + 1) * size]
            for shift in (0, 1):
                with self.subTest(frame=frame, shift=shift):
                    old, _, _ = rice_codec.adaptive_encode(raw, 1920, 1080, shift, 4, method=1)
                    new, flags, digest = rice_codec.adaptive_encode(raw, 1920, 1080, shift, 4)
                    self.assertEqual(new[16], 3)
                    self.assertLess(len(new), 0.9 * len(old))
                    restored = rice_codec.decode(new, flags, size, digest)
                    if shift == 0:
                        self.assertEqual(restored, raw)
                    else:
                        import numpy as np
                        d = np.abs(np.frombuffer(restored, np.uint8).astype(int) - np.frombuffer(raw, np.uint8))
                        self.assertLessEqual(int(d.max()), 1)

    def test_flat_frame_is_zero_groups(self):
        raw = bytes([16, 128] * (1920 * 1080))
        packet, flags, digest = rice_codec.adaptive_encode(raw, 1920, 1080)
        # Only the first group of each band row start codes values; the rest are k=9 headers.
        self.assertLess(len(packet), 1920 * 1080 * 2 // 100)
        self.assertEqual(rice_codec.decode(packet, flags, len(raw), digest), raw)


class NearRoundingTests(unittest.TestCase):
    """Halfway residuals: Rice03 host luma rounds down, chroma half to even;
    the Rice02 return model keeps the FPGA's round-up rule. The two luma
    halves cancel end to end instead of adding a colour cast."""
    def mean_errors(self, packet, flags, raw):
        import numpy as np
        restored = rice_codec.decode(packet, flags, len(raw), rice_codec.checksum(packet))
        d = np.frombuffer(restored, np.uint8).astype(int)-np.frombuffer(raw, np.uint8)
        return np.abs(d).max(), d[0::2].mean(), d[1::4].mean(), d[3::4].mean()

    def test_rounding_bias_per_channel(self):
        lib = rice_codec._lib()
        corpus = (ROOT / 'hardware' / 'hls' / 'rice_corpus_1080p.bin').read_bytes()
        size = 1920 * 1080 * 2
        raw = corpus[4:4 + size]
        for shift in (1, 2):
            with self.subTest(shift=shift):
                packet, flags, _ = rice_codec.adaptive_encode(raw, 1920, 1080, shift)
                worst, y, u, v = self.mean_errors(packet, flags, raw)
                self.assertLessEqual(worst, 1 << shift >> 1)
                self.assertLess(y, -0.1); self.assertLess(abs(u), 0.25); self.assertLess(abs(v), 0.25)
                target = C.create_string_buffer(rice_codec.wire_capacity(1920, 1080))
                n = lib.p6_rice02_encode_near_mock(C.c_char_p(raw), size, target, len(target), shift, 1920, 1080)
                worst, y2, _, _ = self.mean_errors(target.raw[:n], 2, raw)
                self.assertGreater(y2, 0.1)              # hardware return hop rounds up
                self.assertLess(abs(y+y2), 0.25)         # and the host luma rule cancels it

class RiceMock02FastTests(RiceFastTests):
    MINIMUM_HEIGHT = 1
    EXTRA = ()

    @classmethod
    def setUpClass(cls):
        cls.lib = rice_codec._lib()
        cls.fast = cls.lib.p6_rice02_encode_near_mock
        cls.reference = cls.lib.p6_rice02_encode_near_mock_reference
        cls.lossless = cls.lib.p6_rice02_encode_mock
        cls.METHOD = 3
        for function in (cls.fast, cls.reference):
            function.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_uint, C.c_int, C.c_int]
            function.restype = C.c_int
        cls.lossless.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_int, C.c_int]
        cls.lossless.restype = C.c_int

    def test_one_and_two_row_rice02_frames(self):
        for height in (1, 2):
            raw = random.Random(602 + height).randbytes(128 * height * 2)
            for shift in (1, 2, 3):
                with self.subTest(height=height, shift=shift):
                    self.assert_matches(raw, 128, height, shift)


if __name__ == '__main__':
    unittest.main()
