"""Bounded lossless wire codec tests; no board or server required."""
from concurrent.futures import ThreadPoolExecutor
import ctypes as C
import os
from pathlib import Path
import random
import subprocess
import sys
import unittest

try:
    from . import codec
except ImportError:
    import codec


class CodecTests(unittest.TestCase):
    def test_import_is_lazy(self):
        code = "import native.codec as c; assert c._LIBRARY is None"
        subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).resolve().parent.parent, check=True)

    def test_version_and_known_xxhash_vector(self):
        self.assertEqual(codec.codec_info()["lz4_version"], 11000)
        # Upstream XXH32 stable test vector, seed 0.
        self.assertEqual(codec.checksum(b"abc"), 0x32d153ff)

    def test_low_entropy_maximum_round_trip(self):
        data = b"\x10\x80\x10\x80" * (codec.MAX_RAW_BYTES // 4)
        wire, flags, digest = codec.encode(data)
        self.assertEqual(flags, codec.FLAG_LZ4)
        self.assertLessEqual(len(wire), len(data) * 7 // 8)
        self.assertEqual(codec.decode(wire, flags, len(data), digest), data)

    def test_random_maximum_raw_fallback(self):
        data = random.Random(413).randbytes(codec.MAX_RAW_BYTES)
        wire, flags, digest = codec.encode(data)
        self.assertEqual(flags, codec.FLAG_RAW)
        self.assertIs(wire, data)
        self.assertEqual(codec.decode(wire, flags, len(data), digest), data)

    def test_multiple_block_sizes(self):
        rng = random.Random(615)
        for size in (1, 2, 3, 8, 16, 255, 256, 257, 4096, 65536, 65537):
            for data in (b"a" * size, rng.randbytes(size)):
                with self.subTest(size=size, repeated=data[:1]):
                    wire, flags, digest = codec.encode(data)
                    self.assertEqual(codec.decode(wire, flags, len(data), digest), data)

    def test_mutable_input_snapshot(self):
        data = bytearray(b"0123456789" * 10000)
        expected = bytes(data)
        wire, flags, digest = codec.encode(data)
        data[:] = b"z" * len(data)
        self.assertIsInstance(wire, bytes)
        self.assertEqual(codec.decode(wire, flags, len(expected), digest), expected)

    def test_output_ownership(self):
        first = b"A" * 65536
        wire, flags, digest = codec.encode(first)
        decoded = codec.decode(wire, flags, len(first), digest)
        copy = wire[:]
        for value in range(20):
            other = bytes([value]) * 65536
            w, f, d = codec.encode(other)
            self.assertEqual(codec.decode(w, f, len(other), d), other)
        self.assertEqual(wire, copy)
        self.assertEqual(decoded, first)

    def test_adaptive_transport_preserves_pixels_and_skips_noise(self):
        for data in (b'A'*codec.MAX_RAW_BYTES, random.Random(20).randbytes(codec.MAX_RAW_BYTES),
                     b'YUV!'*5000,bytes(range(256))*4096):
            wire,flags,digest=codec.adaptive_encode(data)
            self.assertEqual(codec.decode(wire,flags,len(data),digest),data)
        data=random.Random(21).randbytes(codec.MAX_RAW_BYTES)
        wire,flag,_=codec.adaptive_encode(data)
        self.assertEqual(flag,0)
        self.assertIs(wire,data)

    def test_malformed_or_truncated_lz4(self):
        data = b"abcd" * 4000
        wire, flags, digest = codec.encode(data)
        self.assertEqual(flags, 1)
        for damaged in (b"\0", b"\xff", b"\xff" * 20, wire[:-1], wire[:len(wire)//2], wire + b"junk"):
            with self.subTest(wire_length=len(damaged)), self.assertRaises(ValueError):
                codec.decode(damaged, flags, len(data), digest)

    def test_checksums_and_declared_size(self):
        for data in (b"A" * 4000, random.Random(8).randbytes(4000)):
            wire, flags, digest = codec.encode(data)
            for size, check in ((len(data), digest ^ 1), (len(data)-1, digest), (len(data)+1, digest)):
                with self.subTest(flags=flags, size=size), self.assertRaises(ValueError):
                    codec.decode(wire, flags, size, check)

    def test_bounds_and_unknown_flags(self):
        for data in (b"", b"x" * (codec.MAX_RAW_BYTES + 1)):
            with self.assertRaises(ValueError):
                codec.encode(data)
        for flag in (-1, 2, 3, 0x80000000, True, 1.5):
            with self.assertRaises(ValueError):
                codec.decode(b"x", flag, 1, 0)
        for size in (0, -1, codec.MAX_RAW_BYTES+1, 1.5, True):
            with self.assertRaises(ValueError):
                codec.decode(b"x", 0, size, 0)
        for check in (-1, 0x100000000, 1.5, True):
            with self.assertRaises(ValueError):
                codec.decode(b"x", 0, 1, check)
        with self.assertRaises(TypeError):
            codec.encode("not bytes")

    def test_native_bounds(self):
        lib = codec._library()
        dst = C.create_string_buffer(128)
        for n, cap in ((0, 128), (codec.MAX_RAW_BYTES+1, 128), (1, 0), (1, codec.MAX_RAW_BYTES*2)):
            self.assertEqual(lib.p4_lz4_compress(C.c_char_p(b"x"), dst, n, cap), 0)
        self.assertEqual(lib.p4_lz4_compress(None, dst, 1, 128), 0)
        self.assertEqual(lib.p4_lz4_decompress(C.c_char_p(b"x"), dst, 1, codec.MAX_RAW_BYTES+1), -1)
        self.assertEqual(lib.p4_lz4_decompress(None, dst, 1, 128), -1)

    def test_concurrent_threads_and_retained_outputs(self):
        def run(index):
            rng = random.Random(index)
            retained = []
            for n in range(30):
                data = rng.randbytes(4096) if n % 2 else bytes([index, n]) * 65536
                wire, flags, digest = codec.encode(data)
                result = codec.decode(wire, flags, len(data), digest)
                if result != data:
                    raise AssertionError("concurrent codec roundtrip mismatch")
                retained.append((data, result))
            return all(a == b for a, b in retained)
        with ThreadPoolExecutor(max_workers=8) as pool:
            self.assertTrue(all(pool.map(run, range(8))))


if __name__ == "__main__":
    unittest.main()
