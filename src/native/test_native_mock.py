"""Transport/ownership tests only. NEVER loads an overlay or connects to board."""
import os
from pathlib import Path
import socket
import time
import unittest

from binding import mock
from protocol import (Session, Frame, Header, HELLO, FRAME, RESPONSE, PARAMETERS,
                      read_json, parameter_words, status, PARAMETER_ORDER, PIXEL_FORMAT)

ROOT = Path(__file__).resolve().parent
LIBRARY = ROOT / ("y50_native.dll" if os.name == "nt" else "liby50_native.so")
# Delivery copy: load the redistributed pthread dependency from beside the
# native DLL. Do not rely on the original developer's compiler installation.
_dll_path = os.add_dll_directory(str(ROOT)) if os.name == "nt" else None


class MockTests(unittest.TestCase):
    def setUp(self):
        self.server = mock(LIBRARY, width=1920, height=1080, timeout_ms=500)
        self.port = self.server.status()["port"]

    def tearDown(self):
        self.server.close()

    def wait_idle(self):
        end = time.monotonic() + 3
        while time.monotonic() < end:
            state = self.server.status()
            if state["state"] == "IDLE":
                return state
            time.sleep(.01)
        self.fail("mock retained owner after cancellation")

    def open(self, width=16, height=12):
        return Session("127.0.0.1", self.port, width, height, require_fpga=False,wire_codec='raw')

    def frames(self, count=15, width=16, height=12):
        return [Frame(i+1, i+3, bytes((x+i*11) % 256 for x in range(width*height*2)),
                      {"mode": 0}) for i in range(count)]

    def test_01_bounded_unique_payloads_and_pts(self):
        frames = self.frames()
        with self.open() as session:
            outputs = list(session.exchange(frames))
            self.assertEqual([o.payload for o in outputs], [f.payload for f in frames])
            self.assertEqual([(o.frame_id, o.pts) for o in outputs], [(f.frame_id, f.pts) for f in frames])
            self.assertEqual(session.caps["backend"], "MOCK_TRANSPORT_ONLY")
        final = self.wait_idle()
        self.assertEqual(final["sent"], 15)
        self.assertEqual(final["input_bytes"], 15*16*12*2)

    def test_02_fpga_client_rejects_mock(self):
        with self.assertRaisesRegex(ValueError, "mock backend"):
            Session("127.0.0.1", self.port, 16, 12,wire_codec='raw')
        self.wait_idle()

    def test_03_busy_owner_cannot_be_stolen(self):
        with self.open():
            with self.assertRaisesRegex(RuntimeError, "BUSY"):
                self.open()
            self.assertEqual(status("127.0.0.1", self.port)["state"], "OWNED")
        self.wait_idle()
        with self.open() as next_session:
            self.assertEqual(len(list(next_session.exchange(self.frames(1)))), 1)

    def test_04_partial_payload_disconnect_then_reuse(self):
        sock = socket.create_connection(("127.0.0.1", self.port))
        sock.sendall(Header(HELLO, width=16, height=12).pack())
        read_json(sock, HELLO | RESPONSE)
        sock.sendall(Header(FRAME, 1, 1, 1, 50, 16*12*2, PARAMETERS.size, 16, 12).pack())
        sock.sendall(parameter_words(16, 12, {"mode": 0}))
        sock.sendall(b"partial")
        sock.close()
        state = self.wait_idle()
        self.assertGreaterEqual(state["cancelled_sessions"], 1)
        self.assertEqual(state["first_fault"], "")
        with self.open() as again:
            self.assertEqual(len(list(again.exchange(self.frames(3)))), 3)

    def test_05_generator_cancel_then_reuse(self):
        with self.open() as session:
            stream = session.exchange(self.frames(100))
            self.assertEqual(next(stream).frame_id, 1)
            stream.close()
        self.wait_idle()
        with self.open() as again:
            self.assertEqual(len(list(again.exchange(self.frames(3)))), 3)

    def test_06_legacy_magic_rejected(self):
        with socket.create_connection(("127.0.0.1", self.port)) as sock:
            sock.sendall(b"PZV1" + b"\0"*60)
            with self.assertRaisesRegex(RuntimeError, "magic"):
                read_json(sock, HELLO | RESPONSE)
        self.assertEqual(self.server.status()["received"], 0)

    def test_07_invalid_parameters_rejected_before_payload(self):
        with self.open() as session:
            with self.assertRaises((ValueError, ConnectionError, OSError)):
                list(session.exchange([Frame(1, 1, bytes(384), {"mode": 6})]))
        self.wait_idle()
        self.assertEqual(self.server.status()["received"], 0)

    def test_08_full_frame_slow_consumer_preserves_output(self):
        # Each frame differs. A deliberately paused consumer forces the bounded
        # windows to retain output leases instead of recycling buffers early.
        for width, height in ((1920, 1080), (1280, 720)):
            frames = [Frame(i, i, bytes([17+i])*(width*height*2), {"mode": 0}) for i in range(5)]
            with self.open(width, height) as session:
                outputs = []
                for result in session.exchange(frames):
                    time.sleep(.03)
                    outputs.append(result.payload)
            self.assertEqual(outputs, [f.payload for f in frames])
            self.wait_idle()

    def test_09_split_parameter_abi(self):
        self.assertEqual(len(PARAMETER_ORDER), 24)
        self.assertEqual(PARAMETER_ORDER[-4:], ('noise_floor_uv', 'overshoot', 'chroma_q8', 'clarity'))
        words = PARAMETERS.unpack(parameter_words(16, 12, {'noise_floor': 0, 'noise_floor_uv': 13}))
        self.assertEqual(words[10], 0)
        # overshoot defaults to 255 (off), chroma_q8 and clarity to 0 (off): the earlier V4 pixels.
        self.assertEqual(words[19:], (0, 13, 255, 0, 0))
        self.assertEqual(PARAMETERS.unpack(parameter_words(16, 12, {'overshoot': 1}))[21], 1)
        self.assertEqual(PARAMETERS.unpack(parameter_words(16, 12, {'chroma_q8': 256}))[22], 256)
        self.assertEqual(PARAMETERS.unpack(parameter_words(16, 12, {'clarity': 0x0a180328}))[23], 0x0a180328)
        for bad in ({'overshoot': 256}, {'chroma_q8': 257}, {'chroma_q8': -1}, {'clarity': 0x0a000328}, {'clarity': 1 << 32}):
            with self.assertRaises(ValueError):
                parameter_words(16, 12, bad)
        self.assertEqual(PIXEL_FORMAT, 'YUYV422_BT709_FULL_YUV_V4_SPLIT')

    def test_10_old_yuyv_v3_magic_rejected(self):
        import struct
        with socket.create_connection(('127.0.0.1', self.port)) as sock:
            sock.sendall(struct.pack('!8sHHIQqIIIIIIQ', b'PZYUYV1\0', 1,
                         HELLO, 0, 0, 0, 0, 0, 0, 0, 16, 12, 0))
            with self.assertRaisesRegex(RuntimeError, 'magic'):
                read_json(sock, HELLO | RESPONSE)
        self.assertEqual(self.server.status()['received'], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
