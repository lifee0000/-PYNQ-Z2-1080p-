"""Parallel host Rice03 decode versus the independent reference, including errors."""
import ctypes as C
from pathlib import Path
import random
import struct
import unittest

try:
    from . import rice_codec
except ImportError:
    import rice_codec

ROOT = Path(__file__).resolve().parents[2]


class RiceFastDecodeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lib = rice_codec._lib()
        cls.fast = cls.lib.p6_rice_decode
        cls.reference = cls.lib.p6_rice_decode_reference
        cls.reference.argtypes = cls.fast.argtypes
        cls.reference.restype = C.c_int
        cls.encoder = cls.lib.p6_rice03_encode_near_reference
        cls.encoder.argtypes = cls.lib.p6_rice03_encode_near.argtypes
        cls.encoder.restype = C.c_int

    def packet(self, raw, width, height, shift, method=3):
        target = C.create_string_buffer(rice_codec.wire_capacity(width, height))
        size = self.encoder(C.c_char_p(raw), len(raw), target, len(target), shift, width, height, 3, method)
        self.assertGreater(size, 0)
        return target.raw[:size]

    def compare(self, packet, raw_size):
        outputs = []
        for operation in (self.fast, self.reference):
            target = C.create_string_buffer(b'\xa5' * (raw_size + 32), raw_size + 32)
            size = operation(C.c_char_p(packet), len(packet), C.byref(target, 16), raw_size, 3)
            self.assertEqual(target.raw[:16], b'\xa5' * 16)
            self.assertEqual(target.raw[-16:], b'\xa5' * 16)
            if size <= 0:
                self.assertEqual(target.raw, b'\xa5' * (raw_size + 32))
                outputs.append(None)
            else:
                self.assertEqual(size, raw_size)
                outputs.append(target.raw[16:16+size])
        self.assertEqual(outputs[0], outputs[1])
        return outputs[0]

    def test_complete_corpora_all_near_shifts(self):
        for name, width, height in (('rice_corpus_1080p.bin', 1920, 1080), ('rice_corpus.bin', 1280, 720)):
            data = (ROOT/'hardware/hls'/name).read_bytes()
            size = width * height * 2
            for index in range(int.from_bytes(data[:4], 'little')):
                raw = data[4+index*size:4+(index+1)*size]
                for shift in (0, 1, 2, 3):
                    for method in (1, 3):
                        with self.subTest(geometry=(width, height), frame=index, shift=shift, method=method):
                            restored = self.compare(self.packet(raw, width, height, shift, method), size)
                            self.assertIsNotNone(restored)
                            if shift == 0:
                                self.assertEqual(restored, raw)

    def test_slice_boundaries_predictors_random_damage_and_padding(self):
        rng = random.Random(603701)
        for height in (3, 4, 5, 11):
            size = 128 * height * 2
            for raw, method in ((bytes(size), 3), (b'\xff' * size, 3), (rng.randbytes(size), 3), (rng.randbytes(size), 1)):
                packet = self.packet(raw, 128, height, 3, method)
                self.assertIsNotNone(self.compare(packet, size))
                alternate_predictor = bytearray(packet)
                alternate_predictor[16] ^= 1  # MED <-> UP within the same layout
                self.assertIsNotNone(self.compare(bytes(alternate_predictor), size))
                damaged = [packet[:n] for n in (0, 7, 19, 20, 31, 32, len(packet)//2, len(packet)-1)]
                damaged += [packet+b'\0', packet+b'junk']
                for position, value in ((0, 0), (7, 50), (16, 2), (16, 4), (17, 0), (17, 17),
                                        (18, 4), (19, 1), (20, 0), (24, 0), (28, 0), (32, 15)):
                    changed = bytearray(packet)
                    changed[position] = value
                    damaged.append(bytes(changed))
                for _ in range(15):
                    changed = bytearray(packet)
                    position = rng.randrange(16, len(packet))
                    changed[position] ^= 1 << rng.randrange(8)
                    damaged.append(bytes(changed))
                for value in damaged:
                    self.compare(value, size)

    def test_literal_groups_with_single_small_and_many_slices(self):
        # Construct packets independently of either encoder. A k=8 group stores
        # literal samples, so the expected interleaved frame is simply raw.
        # Include one-row slices, uneven row bands and more than one 64-sample
        # group per row; these are absent from the fixed three-slice encoder.
        rng = random.Random(316128)
        geometries = ((128, 1, 1), (128, 2, 1), (128, 2, 2),
                      (256, 5, 2), (256, 5, 4), (256, 17, 16))
        for width, height, slices in geometries:
            raw = rng.randbytes(width * height * 2)
            bands = []
            for part in range(slices):
                bits = []
                top, bottom = part * height // slices, (part + 1) * height // slices
                for y in range(top, bottom):
                    for x in range(0, width // 2, 64):
                        for channel in range(4):
                            bits.extend((0, 0, 0, 1))  # k=8, little-endian bits
                            for j in range(64):
                                value = raw[(y * (width // 2) + x + j) * 4 + channel]
                                bits.extend((value >> bit) & 1 for bit in range(8))
                bits.extend([0] * (-len(bits) % 8))
                bands.append(bytes(sum(bits[start + bit] << bit for bit in range(8))
                                   for start in range(0, len(bits), 8)))
            # Layout 2: luma groups carry 64 full-resolution samples (byte 2n
            # of the row), groups 0 and 2 the first and second half of a tile.
            layout2 = []
            for part in range(slices):
                bits = []
                top, bottom = part * height // slices, (part + 1) * height // slices
                for y in range(top, bottom):
                    for x in range(0, width // 2, 64):
                        for channel in range(4):
                            bits.extend((0, 0, 0, 1))
                            for j in range(64):
                                if channel & 1:
                                    value = raw[(y * (width // 2) + x + j) * 4 + channel]
                                else:
                                    value = raw[2 * (y * width + 2 * x + (64 if channel else 0) + j)]
                                bits.extend((value >> bit) & 1 for bit in range(8))
                bits.extend([0] * (-len(bits) % 8))
                layout2.append(bytes(sum(bits[start + bit] << bit for bit in range(8))
                                     for start in range(0, len(bits), 8)))
            self.assertEqual([len(b) for b in layout2], [len(b) for b in bands])
            offset = 20 + 4 * slices
            offsets = []
            for band in bands:
                offsets.append(offset)
                offset += len(band)
            table = struct.pack('<' + 'I' * slices, *offsets)
            for method in (0, 1, 2, 3):
                for shift in (1, 2, 3):
                    packet = (b'P6RICE03' + struct.pack('<IIBBBB', width, height,
                              method, slices, shift, 0) + table + b''.join(layout2 if method & 2 else bands))
                    with self.subTest(width=width, height=height, slices=slices,
                                      method=method, shift=shift):
                        self.assertEqual(self.compare(packet, len(raw)), raw)


if __name__ == '__main__':
    unittest.main()
