"""Independent integer parity, exhaustive color coverage and buffer edges."""
import unittest

import numpy as np

from benchmark_pc import benchmark, frozen_pack_rgb, frozen_unpack_rgb
from pixels import pack_rgb, unpack_rgb


def _clip(value):
    return min(255, max(0, value))


def _scalar_pack(image):
    raw = bytearray()
    for row in image:
        for pair in row.reshape(-1, 2, 3):
            values = []
            for r, g, b in pair.astype(int):
                values.append((
                    _clip((13933*int(r)+46871*int(g)+4732*int(b)+32768) >> 16),
                    _clip(((-7509*int(r)-25259*int(g)+32768*int(b)+32768) >> 16)+128),
                    _clip(((32768*int(r)-29763*int(g)-3005*int(b)+32768) >> 16)+128)))
            first, second = values
            raw.extend((first[0], (first[1]+second[1]+1)//2,
                        second[0], (first[2]+second[2]+1)//2))
    return bytes(raw)


def _scalar_unpack(payload, width, height):
    pixels = []
    for index in range(0, len(payload), 4):
        y0, u, y1, v = payload[index:index+4]
        u -= 128
        v -= 128
        for y in (y0, y1):
            pixels.append((_clip(y+((103206*v+32768) >> 16)),
                           _clip(y-((12276*u+30679*v+32768) >> 16)),
                           _clip(y+((121609*u+32768) >> 16))))
    return np.array(pixels, np.uint8).reshape(height, width, 3)


class PixelParityTests(unittest.TestCase):
    def test_scalar_extremes_rounding_and_pair_clipping(self):
        rng = np.random.default_rng(619)
        image = rng.integers(0, 256, (7, 18, 3), dtype=np.uint8)
        corners = np.array([(r, g, b) for r in (0, 255) for g in (0, 255)
                            for b in (0, 255)], np.uint8)
        image[0, :8] = corners
        image[1, :8] = corners[::-1]
        original = image.copy()
        raw = pack_rgb(image)
        self.assertEqual(raw, _scalar_pack(image))
        np.testing.assert_array_equal(unpack_rgb(raw, 18, 7), _scalar_unpack(raw, 18, 7))
        np.testing.assert_array_equal(image, original)

    def test_every_rgb_color_forward(self):
        # 32 valid frames cover all 16,777,216 RGB triples without a huge LUT.
        for block in range(32):
            numbers = np.arange(block*524288, (block+1)*524288, dtype=np.uint32)
            image = np.empty((512, 1024, 3), np.uint8)
            flat = image.reshape(-1, 3)
            flat[:, 0] = numbers >> 16
            flat[:, 1] = (numbers >> 8) & 255
            flat[:, 2] = numbers & 255
            self.assertEqual(pack_rgb(image), frozen_pack_rgb(image), f'RGB block {block}')

    def test_every_y_u_v_triple_preview(self):
        # All 256^3 YUV triples, including clipping and signed rounding limits.
        frame = np.empty((256, 512, 2), np.uint8)
        frame[:, 0::2, 1] = np.arange(256, dtype=np.uint8)[:, None]
        frame[:, 1::2, 1] = np.arange(256, dtype=np.uint8)[None, :]
        for y in range(256):
            frame[:, :, 0] = y
            raw = frame.tobytes()
            np.testing.assert_array_equal(unpack_rgb(raw, 512, 256),
                                          frozen_unpack_rgb(raw, 512, 256), err_msg=f'Y={y}')

    def test_strided_readonly_and_maximum_geometry(self):
        rng = np.random.default_rng(98)
        large = rng.integers(0, 256, (720, 1280, 3), dtype=np.uint8)
        for image in (large, large[::-1, ::-1], large[::2, ::2], large[:3, :4]):
            image.flags.writeable = False
            raw = pack_rgb(image)
            self.assertEqual(raw, frozen_pack_rgb(image))
            h, w = image.shape[:2]
            np.testing.assert_array_equal(unpack_rgb(raw, w, h), frozen_unpack_rgb(raw, w, h))

    def test_buffers_and_independent_outputs(self):
        payload = bytes(range(24))
        expected = _scalar_unpack(payload, 4, 3)
        for buffer in (payload, bytearray(payload), memoryview(payload),
                       np.frombuffer(payload, np.uint8)):
            decoded = unpack_rgb(buffer, 4, 3)
            np.testing.assert_array_equal(decoded, expected)
            decoded.fill(255)
            np.testing.assert_array_equal(unpack_rgb(buffer, 4, 3), expected)

    def test_reject_invalid_images_geometry_and_buffers(self):
        for image in (np.zeros((3, 4, 3), np.float32), np.zeros((3, 4), np.uint8),
                      np.zeros((3, 4, 4), np.uint8), np.zeros((2, 4, 3), np.uint8),
                      np.zeros((3, 5, 3), np.uint8), np.zeros((3, 1922, 3), np.uint8)):
            with self.assertRaises(ValueError):
                pack_rgb(image)
        for width, height in ((3, 4), (2, 3), (1922, 3), (4, 1081), (4, 2),
                              (True, 3), (4, False), (4.0, 3), ('4', 3)):
            with self.assertRaises(ValueError):
                unpack_rgb(bytes(24), width, height)
        for payload in (b'', bytes(23), bytes(25), 'a'*24, memoryview(bytes(48))[::2]):
            with self.assertRaises(ValueError):
                unpack_rgb(payload, 4, 3)

    def test_benchmark_bounds_and_exact_hashes(self):
        report = benchmark(4, 3, repeats=1, warmup=0, frames=1, include_auto=False)
        self.assertFalse(report['board_contacted'])
        for stage in report['stages'].values():
            self.assertTrue(stage['exact_byte_parity'])
            self.assertEqual(stage['baseline_sha256'], stage['optimized_sha256'])
        for settings in ({'repeats': 0}, {'repeats': 101}, {'warmup': 21},
                         {'frames': 9}, {'seed': -1}, {'width': 3}):
            with self.assertRaises(ValueError):
                benchmark(**settings)


if __name__ == '__main__':
    unittest.main()
