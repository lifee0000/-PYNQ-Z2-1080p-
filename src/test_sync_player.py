"""Same-frame player: frame numbers follow the files' timestamps (review F5/F6)."""
from fractions import Fraction
from pathlib import Path
import tempfile, time, unittest
import av
import numpy as np
from sync_player import SyncPlayback, frame_index


def write_marked(path, pts_ms, codec='ffv1'):
    """Frame i is a flat grey of 4*i + 8, at the given millisecond timestamps."""
    with av.open(str(path), 'w') as out:
        s = out.add_stream(codec, rate=25); s.width, s.height = 64, 48
        s.pix_fmt = 'bgr0' if codec == 'ffv1' else 'yuv420p'; s.time_base = Fraction(1, 1000)
        if codec != 'ffv1': s.options = dict(crf='0', g='12', bf='2')
        for i, pts in enumerate(pts_ms):
            f = av.VideoFrame.from_ndarray(np.full((48, 64, 3), 4 * i + 8, np.uint8), format='rgb24')
            f.pts, f.time_base = pts, Fraction(1, 1000)
            for p in s.encode(f): out.mux(p)
        for p in s.encode(None): out.mux(p)


def marker(frame):
    return round((frame.to_ndarray(format='rgb24').mean() - 8) / 4)


class SyncPlayerTest(unittest.TestCase):
    def pair_after_seek(self, player, index):
        player.seek(index); end = time.monotonic() + 10
        while time.monotonic() < end:
            item = player.next_pair()
            if item is not None: return item
            time.sleep(.01)
        self.fail(f'no pair for {index}: {player.error}')

    def check(self, path, pts_ms):
        player = SyncPlayback(path, path, lambda: (64, 48))
        try:
            self.assertEqual(player.count, len(pts_ms))
            for index in (20, 0, len(pts_ms) - 1, 19, 3, 2, 1, 25):
                item = self.pair_after_seek(player, index)
                self.assertEqual((item[0], marker(item[3]), marker(item[4])), (index, index, index))
                self.assertAlmostEqual(player.seconds(index), (pts_ms[index] - pts_ms[0]) / 1000, places=6)
        finally:
            player.close()

    def test_variable_frame_rate_seeks_to_the_real_frame(self):
        # 40 ms for 10 frames, then 120 ms (the encoder keeps a 40 ms grid): frame 20 is at 1.6 s, not 20/average-rate.
        pts = [40 * i for i in range(10)] + [400 + 120 * i for i in range(20)]
        with tempfile.TemporaryDirectory() as folder:
            for codec, name in (('ffv1', 'vfr.mkv'), ('libx264', 'vfr.mp4')):
                path = Path(folder) / name; write_marked(path, pts, codec)
                with self.subTest(codec=codec): self.check(path, pts)

    def test_mkv_without_a_frame_count_seeks_to_the_end(self):
        pts = [40 * i for i in range(30)]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'count.mkv'; write_marked(path, pts)
            with av.open(str(path)) as video: self.assertEqual(video.streams.video[0].frames, 0)
            self.assertEqual(frame_index(path)[1], 30)
            self.check(path, pts)


if __name__ == '__main__':
    unittest.main()
