"""Same-frame playback of a source video and its exported result.

A worker thread decodes both files in lockstep (frame i of the source with frame i of
the export, the exporter writes one output frame per source frame), scales each to the
size the window asks for with swscale, and queues the pairs. The window pulls one pair
per frame interval while playing, so a slow decode slows playback but never drops or
misaligns a frame.

Frame numbers come from the files' own packet timestamps (review F5/F6, 2026-11-01): on
opening, both files are demuxed (no decoding) and frame i is the i-th smallest PTS. A seek
to frame i reopens at the keyframe before that PTS and decodes forward to exactly it, so a
variable-frame-rate file or one whose header has no frame count (MKV) seeks to the real
frame. A file without timestamps is counted by decoding from the start.
"""
from fractions import Fraction
import queue
import threading

import av


def frame_index(path):
    """(sorted PTS per frame or None, frame count, time base) of the first video stream, from its packets."""
    with av.open(path) as container:
        stream = container.streams.video[0]; pts = []; count = 0
        for packet in container.demux(stream):
            if packet.size:
                count += 1
                if packet.pts is not None: pts.append(packet.pts)
        if not count:
            raise ValueError(f'{path}: no video frames')
        return (sorted(pts) if len(pts) == count else None), count, stream.time_base


class SyncPlayback:
    QUEUE = 3

    def __init__(self, source, result, display_size):
        """display_size(): (width, height) each picture may use; read for every frame."""
        self.paths = (str(source), str(result)); self.display_size = display_size
        with av.open(self.paths[0]) as s, av.open(self.paths[1]) as r:
            vs, vr = s.streams.video[0], r.streams.video[0]
            self.rate = Fraction(vr.average_rate or vs.average_rate or 25)
            self.sizes = ((vs.width, vs.height), (vr.width, vr.height))
        indexes = [frame_index(path) for path in self.paths]
        self.pts = [i[0] for i in indexes]; self.time_base = indexes[1][2]
        self.count = min(i[1] for i in indexes)
        self.queue = queue.Queue(maxsize=self.QUEUE); self.lock = threading.Lock()
        self.stop_event = threading.Event(); self.generation = 0; self.start_index = 0
        self.thread = None; self.threads = []; self.error = None; self.ended = False
        self._launch(0)

    def seconds(self, index):
        """Presentation time of frame index in the export, from its timestamps."""
        pts = self.pts[1]
        if pts is None or not self.time_base:
            return index / float(self.rate)
        return float((pts[index] - pts[0]) * self.time_base)

    def _launch(self, index):
        with self.lock:
            self.generation += 1; generation = self.generation; self.start_index = index; self.ended = False
            while True:
                try: self.queue.get_nowait()
                except queue.Empty: break
        self.thread = threading.Thread(target=self._run, args=(generation, index), name='sync-playback', daemon=True)
        self.threads = [t for t in self.threads if t.is_alive()] + [self.thread]; self.thread.start()

    def _frames(self, container, side, index):
        """Frames of one file from frame index on, in presentation order."""
        stream = container.streams.video[0]; stream.thread_type = 'AUTO'; pts = self.pts[side]
        if pts is None:
            for position, frame in enumerate(container.decode(stream)):
                if position >= index: yield frame
            return
        target = pts[index]
        if index > 0:
            container.seek(target, stream=stream, backward=True, any_frame=False)
        frames = container.decode(stream)
        for frame in frames:
            if frame.pts is None or frame.pts < target:
                continue
            if frame.pts != target:
                # The demuxer landed past the frame: decode from the start instead of mislabelling.
                container.seek(pts[0], stream=stream, backward=True, any_frame=False)
                frames = (f for f in container.decode(stream) if f.pts is not None and f.pts >= target)
                frame = next(frames, None)
                if frame is None or frame.pts != target:
                    raise RuntimeError(f'frame {index} (pts {target}) not found')
            yield frame
            break
        yield from frames

    def _scaled(self, frame):
        width, height = self.display_size()
        ratio = min(width / frame.width, height / frame.height)
        w, h = max(2, round(frame.width * ratio)), max(2, round(frame.height * ratio))
        return frame.reformat(width=w, height=h, format='rgb24', interpolation='AREA').to_image()

    def _run(self, generation, index):
        try:
            with av.open(self.paths[0]) as source, av.open(self.paths[1]) as result:
                pairs = zip(self._frames(source, 0, index), self._frames(result, 1, index))
                for offset, (a, b) in enumerate(pairs):
                    if self.stop_event.is_set() or generation != self.generation or index + offset >= self.count:
                        break
                    item = (generation, (index + offset, self._scaled(a), self._scaled(b), a, b))
                    while not (self.stop_event.is_set() or generation != self.generation):
                        try: self.queue.put(item, timeout=.1); break
                        except queue.Full: continue
            if generation == self.generation and not self.stop_event.is_set(): self.ended = True
        except Exception as exc:
            if generation == self.generation: self.error = exc

    def next_pair(self):
        """The next (index, source picture, result picture, source frame, result frame), or None if not decoded yet.

        A worker replaced by a seek can still complete one put after the queue was drained;
        pairs carry their generation and stale ones are dropped here."""
        while True:
            try: generation, pair = self.queue.get_nowait()
            except queue.Empty: return None
            if generation == self.generation: return pair

    def seek(self, index):
        self._launch(max(0, min(int(index), max(0, self.count - 1))))

    def close(self, wait=2.0):
        """Stop decoding; wait (seconds) for the workers to close both files."""
        self.stop_event.set()
        for thread in self.threads:
            if thread is not threading.current_thread(): thread.join(wait)
