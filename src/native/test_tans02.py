"""P6TANS02 return path (encoder IP 5.0): CPU model, fast and reference decoders.

The reconstruction must equal the Rice02 return path's (same quantiser), the
fast decoder must agree with the reference on every packet, and damaged packets
must not be accepted differently by the two.
"""
import ctypes as C
from pathlib import Path
import random
import time
import unittest

try:
    from . import rice_codec
except ImportError:
    import rice_codec

ROOT = Path(__file__).resolve().parents[2]
SIGNATURE = [C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_uint, C.c_int, C.c_int]


def corpus(name, width, height):
    data = (ROOT / 'hardware' / 'hls' / name).read_bytes(); size = width * height * 2
    return [data[4 + i * size:4 + (i + 1) * size] for i in range(int.from_bytes(data[:4], 'little'))]


class Tans02Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        lib = cls.lib = rice_codec._lib()
        for name in ('p6_tans02_encode', 'p6_rice02_encode_near_mock_reference'):
            getattr(lib, name).argtypes = SIGNATURE; getattr(lib, name).restype = C.c_int
        lib.p6_rice_decode_reference.argtypes = [C.c_void_p, C.c_int, C.c_void_p, C.c_int, C.c_int]
        lib.p6_rice_decode_reference.restype = C.c_int
        cls.sets = [((1920, 1080), corpus('tans_corpus_1080p.bin', 1920, 1080) + corpus('rice_corpus_1080p.bin', 1920, 1080)),
                    ((1280, 720), corpus('rice_corpus.bin', 1280, 720))]

    def encode(self, function, raw, w, h, shift):
        capacity = rice_codec.wire_capacity(w, h)
        target = C.create_string_buffer(b'\xa5' * (capacity + 32), capacity + 32)
        n = function(C.c_char_p(raw), len(raw), C.byref(target, 16), capacity, shift, w, h)
        self.assertGreater(n, 0); self.assertLessEqual(n, capacity)
        self.assertEqual(target.raw[:16], b'\xa5' * 16); self.assertEqual(target.raw[16 + n:], b'\xa5' * (capacity + 16 - n))
        return target.raw[16:16 + n]

    def decode(self, packet, size, reference=False):
        dst = C.create_string_buffer(size)
        f = self.lib.p6_rice_decode_reference if reference else self.lib.p6_rice_decode
        n = f(C.c_char_p(packet), len(packet), dst, size, 2)
        return dst.raw[:n] if n == size else n

    def test_reconstruction_equals_rice02_return_and_both_decoders_agree(self):
        for (w, h), frames in self.sets:
            for i, raw in enumerate(frames):
                for shift in (0, 1, 2, 3):
                    with self.subTest(geometry=(w, h), frame=i, shift=shift):
                        packet = self.encode(self.lib.p6_tans02_encode, raw, w, h, shift)
                        self.assertEqual(packet[:8], b'P6TANS02'); self.assertEqual(packet[16:20], bytes([2 if shift else 3, shift, 1, 0]))
                        fast, ref = self.decode(packet, len(raw)), self.decode(packet, len(raw), True)
                        rice = self.decode(self.encode(self.lib.p6_rice02_encode_near_mock_reference, raw, w, h, shift), len(raw))
                        self.assertIsInstance(fast, bytes); self.assertEqual(fast, ref); self.assertEqual(fast, rice)
                        if not shift: self.assertEqual(fast, raw)

    def test_damaged_packets(self):
        raw = self.sets[0][1][0]; size = len(raw)
        for shift in (0, 1):
            packet = self.encode(self.lib.p6_tans02_encode, raw, 1920, 1080, shift)
            for bad in (packet[:-1], packet + b'\0', packet[:19], b'P6TANS03' + packet[8:],
                        packet[:18] + b'\x02' + packet[19:], packet[:-2] + bytes([packet[-2] ^ 1, packet[-1]])):
                self.assertLess(self.lib.p6_rice_decode(C.c_char_p(bad), len(bad), C.create_string_buffer(size), size, 2), 0)
                self.assertLess(self.lib.p6_rice_decode_reference(C.c_char_p(bad), len(bad), C.create_string_buffer(size), size, 2), 0)
            # A rejected packet leaves the caller's buffer as it was.
            canary = C.create_string_buffer(b'\x5a' * size, size)
            self.assertLess(self.lib.p6_rice_decode(C.c_char_p(packet[:-1]), len(packet) - 1, canary, size, 2), 0)
            self.assertEqual(canary.raw, b'\x5a' * size)
            rng = random.Random(20261027 + shift)
            for _ in range(40):
                bad = bytearray(packet); at = rng.randrange(20, len(bad)); bad[at] ^= 1 << rng.randrange(8); bad = bytes(bad)
                self.assertEqual(self.decode(bad, size), self.decode(bad, size, True))

    def test_geometry_and_bound(self):
        raw = bytes(128 * 4 * 2)
        target = C.create_string_buffer(rice_codec.wire_capacity(128, 4))
        self.assertLess(self.lib.p6_tans02_encode(C.c_char_p(raw), len(raw), target, len(target), 0, 128, 4), 0)
        noise = random.Random(7).randbytes(1920 * 1080 * 2)
        for shift in (0, 3):
            packet = self.encode(self.lib.p6_tans02_encode, noise, 1920, 1080, shift)
            self.assertLessEqual(len(packet), 4181784)           # tansref::max_bytes(1920, 1080)
            self.assertEqual(self.decode(packet, len(noise)), self.decode(packet, len(noise), True))

    def test_fast_decode_speed(self):
        raw = self.sets[0][1][0]
        packet = self.encode(self.lib.p6_tans02_encode, raw, 1920, 1080, 0)
        best = min(self._time(packet, len(raw)) for _ in range(5))
        print(f'\nP6TANS02 fast decode 1080p lossless: {best * 1000:.1f} ms ({len(packet)} bytes)')
        self.assertLess(best, 0.2)

    def _time(self, packet, size):
        dst = C.create_string_buffer(size); started = time.perf_counter()
        self.assertEqual(self.lib.p6_rice_decode(C.c_char_p(packet), len(packet), dst, size, 2), size)
        return time.perf_counter() - started


if __name__ == '__main__':
    unittest.main()
