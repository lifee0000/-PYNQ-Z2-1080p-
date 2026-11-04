"""Independent YUYV422 transport; deliberately incompatible with legacy PZV1.

This module contains no image algorithm. Payload is FULL-range BT.709-labelled
YUYV422 (Y0 U0 Y1 V0). A source converter must really produce that colour model;
merely relabelling limited-range camera bytes is not supported.
"""
import dataclasses
import json
import socket
import struct
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor

MAGIC = b"PZYUV7S\0"
VERSION = 7
# Version 7 raises the frame limit to 1920x1080. Compressed (Rice) sessions need
# whole 64-pair groups per row: width a multiple of 128. geometry.py mirrors this.
MAX_WIDTH, MAX_HEIGHT = 1920, 1080
RICE_GEOMETRIES = ((1280, 720), (1920, 1080))
# Host frames encoded ahead of the in-flight window (bounded memory: 2 wire packets).
ENCODE_AHEAD = 2
# Returned frames decoded concurrently on worker threads (encode_ahead > 0 only).
# P6TANS02 decodes in 25-50 ms per 1080p frame (Rice02: ~12 ms); four in flight
# keep the receiver draining the socket at the board's rate.
DECODE_AHEAD = 4


def frames_ahead_limit(max_inflight, encode_ahead=ENCODE_AHEAD):
    """Most frames a Session may have pulled from its source but not yet yielded.

    max_inflight on the board; frames whose slot was already released but whose
    result is not yet yielded (1, or DECODE_AHEAD with the decode pool); with
    encode-ahead also the sender's frame waiting for a slot, encode_ahead queued
    packets and the encoder's frame waiting for queue space.
    """
    if not encode_ahead:
        return max_inflight + 1
    return max_inflight + DECODE_AHEAD + encode_ahead + 2
HEADER = struct.Struct("!8sHHIQqIIIIIIQ")
PARAMETERS = struct.Struct("!24I")
RESULT = struct.Struct("!IIIIQQ")
HELLO, FRAME, FIN, STATUS, CANCEL = 1, 2, 3, 4, 5
RESPONSE, ERROR = 0x8000, 0xffff
PIXEL_FORMAT = "YUYV422_BT709_FULL_YUV_V4_SPLIT"
PARAMETER_ORDER = ("width", "height", "mode", "brightness", "gain_q8_8",
                   "threshold", "sharp_q8_8", "filter_enable", "knee_out",
                   "soft_q8_8", "noise_floor", "detail_limit", "dark_thr",
                   "light_thr", "roi_enable", "roi_x", "roi_y", "roi_width",
                   "roi_height", "discard_startup_frame", "noise_floor_uv",
                   "overshoot", "chroma_q8", "clarity")
DEFAULTS = dict(zip(PARAMETER_ORDER[2:],
                   (5, 0, 256, 64, 256, 1, 200, 128, 2, 32, 48, 208,
                    0, 0, 0, 0, 0, 0, 2, 255, 0, 0)))


@dataclasses.dataclass(frozen=True)
class Header:
    op: int
    frame_id: int = 0
    pts: int = 0
    time_base_num: int = 0
    time_base_den: int = 0
    payload_bytes: int = 0
    parameter_bytes: int = 0
    width: int = 0
    height: int = 0
    flags: int = 0
    checksum: int = 0

    def pack(self):
        return HEADER.pack(MAGIC, VERSION, self.op, self.flags, self.frame_id,
                           self.pts, self.time_base_num, self.time_base_den,
                           self.payload_bytes, self.parameter_bytes,
                           self.width, self.height, self.checksum)

    @classmethod
    def unpack(cls, data):
        (magic, version, op, flags, fid, pts, num, den, count,
         params, w, h, checksum) = HEADER.unpack(data)
        if magic != MAGIC or version != VERSION or flags & ~(0x1303 if op == HELLO else 0x303) or checksum > 0xffffffff:
            raise ValueError("incompatible YUYV protocol magic/version/reserved")
        if op not in (FRAME, FRAME | RESPONSE) and (checksum or (flags and op != HELLO)):
            raise ValueError('nonzero control flags/checksum')
        return cls(op, fid, pts, num, den, count, params, w, h, flags, checksum)


def recv_exact(sock, count):
    data = bytearray(count)
    view = memoryview(data)
    done = 0
    while done < count:
        n = sock.recv_into(view[done:])
        if not n:
            raise ConnectionError("native peer disconnected")
        done += n
    return data


def read_header(sock):
    return Header.unpack(recv_exact(sock, HEADER.size))


def read_json(sock, expected):
    header = read_header(sock)
    if header.parameter_bytes or header.payload_bytes > 131072:
        raise ValueError("invalid JSON response length")
    value = json.loads(recv_exact(sock, header.payload_bytes))
    if header.op == ERROR:
        raise RuntimeError(value.get("error", "native service error"))
    if header.op != expected:
        raise ValueError("unexpected native response")
    return value


def status(host="192.168.2.99", port=5010, timeout=5):
    with socket.create_connection((host, port), timeout) as sock:
        sock.sendall(Header(STATUS).pack())
        return read_json(sock, STATUS | RESPONSE)


def parameter_words(width, height, settings=None):
    p = dict(DEFAULTS)
    if settings:
        unknown = set(settings) - set(p)
        if unknown:
            raise ValueError(f"unknown parameters: {sorted(unknown)}")
        p.update(settings)
    p.update(width=width, height=height)
    if any(type(v) is not int for v in p.values()):
        raise ValueError("integer parameters required")
    if not (4 <= width <= MAX_WIDTH and width % 2 == 0 and 3 <= height <= MAX_HEIGHT):
        raise ValueError(f"even width 4..{MAX_WIDTH}, height 3..{MAX_HEIGHT} required")
    ranges = {"mode": (0, 5), "brightness": (-255, 255),
              "gain_q8_8": (0, 1024), "sharp_q8_8": (0, 1024),
              "filter_enable": (0, 1), "soft_q8_8": (0, 256),
              "roi_enable": (0, 1), "discard_startup_frame": (0, 0),
              "chroma_q8": (0, 256), "clarity": (0, 0xffffffff)}
    for key in ("threshold", "knee_out", "noise_floor", "noise_floor_uv", "overshoot", "detail_limit", "dark_thr", "light_thr"):
        ranges[key] = (0, 255)
    for key in ("roi_x", "roi_y", "roi_width", "roi_height"):
        ranges[key] = (0, MAX_WIDTH)
    for key, (low, high) in ranges.items():
        if not low <= p[key] <= high:
            raise ValueError(f"invalid {key}")
    # Enhance IP 1.5: a clarity strength needs its edge threshold T (bits 16-23).
    if p["clarity"] & 255 and not p["clarity"] >> 16 & 255:
        raise ValueError("invalid clarity")
    if p["roi_enable"] and not (p["roi_width"] >= 3 and p["roi_height"] >= 3
            and p["roi_x"] + p["roi_width"] <= width
            and p["roi_y"] + p["roi_height"] <= height):
        raise ValueError("ROI must be within the frame and at least 3x3")
    return PARAMETERS.pack(*(p[name] & 0xffffffff for name in PARAMETER_ORDER))


@dataclasses.dataclass(frozen=True)
class Frame:
    frame_id: int
    pts: int
    payload: bytes
    parameters: dict = dataclasses.field(default_factory=dict)
    time_base_num: int = 1
    time_base_den: int = 50


@dataclasses.dataclass(frozen=True)
class Output:
    frame_id: int
    pts: int
    payload: bytes
    time_base_num: int
    time_base_den: int
    completed_frames: int
    stream_errors: int
    mm2s_status: int
    s2mm_status: int
    dma_ns: int
    transport_shift: int = 0  # near shift this frame came back with (0 = lossless)
    upload_shift: int = 0     # near shift it went up with (differs only with return_lossless)


class Session:
    """One ordered stream; sender and receiver overlap with up to six frames.

    The hardware server also has six bounded slots. Both sides hold a frame
    until its output bytes are sent/received, including slow consumer cases.
    Results are independent host bytes; no native CMA pointer escapes the board.
    """
    def __init__(self, host="192.168.2.99", port=5010, width=1920, height=1080,
                 timeout=10, require_fpga=True, expected_identity=None, max_inflight=6,
                 wire_codec='rice03',near_shift=0,encode_ahead=ENCODE_AHEAD,frame_shift=None,return_lossless=False):
        if type(near_shift)is not int or not 0<=near_shift<=3:raise ValueError('near_shift must be 0..3')
        # 0 reproduces the earlier host behaviour (encode only once a window slot
        # is free) for A/B measurements; the default keeps 2 frames encoded ahead.
        if type(encode_ahead) is not int or not 0<=encode_ahead<=ENCODE_AHEAD:raise ValueError('encode_ahead must be 0..2')
        self.encode_ahead=encode_ahead
        # frame_shift(frame) -> shift in 0..near_shift picks a per-frame precision
        # (optional frame_shift.observe(shift, wire_bytes) is told the result,
        # optional frame_shift.observe_return(frame_id, shift, wire_bytes) the return);
        # near_shift is then the negotiated maximum and the board returns each
        # frame at that frame's own shift.
        if frame_shift is not None and (not callable(frame_shift) or wire_codec!='rice03'):raise ValueError('frame_shift needs a callable and rice03')
        self.frame_shift=frame_shift
        self._upload_shift={}  # frame_id -> shift it was sent with, until its result arrives
        if near_shift and wire_codec=='raw':raise ValueError('Near transport requires compressed mode')
        self.near_shift=near_shift
        if wire_codec=='lz4':wire_codec='rice03'  # Compatibility option name; actual wire is Rice03/v6.
        if wire_codec not in ('rice03','raw'):raise ValueError('P6 wire codec must be rice03 or raw')
        if type(return_lossless) is not bool:raise ValueError('return_lossless must be bool')
        if return_lossless and (wire_codec!='rice03' or not near_shift):raise ValueError('return_lossless needs a near-lossless rice03 session')
        self.return_lossless=return_lossless
        if wire_codec=='rice03' and (width,height) not in RICE_GEOMETRIES:raise ValueError('Rice03 requires a full 1280x720 or 1920x1080 frame; use raw for small regression vectors')
        try:from .rice_codec import adaptive_encode,decode,checksum
        except ImportError:from rice_codec import adaptive_encode,decode,checksum
        self._encode, self._decode, self._checksum = adaptive_encode, decode, checksum
        self.wire_codec = wire_codec
        self.transport_metrics = dict(codec=wire_codec,near_shift=near_shift,return_lossless=return_lossless,lossy=bool(near_shift), input_raw_bytes=0,input_wire_bytes=0,
            output_raw_bytes=0,output_wire_bytes=0,compressed_input_frames=0,compressed_output_frames=0,
            encode_seconds=0.,decode_seconds=0.,serial_fallback_frames=0,max_pending_frames=0,encode_ahead=encode_ahead,
            compression_selection='RICE03_THREE_PARALLEL_BANDS_EXACT',
            window_policy='ONE_RAW_UP_TO_SIX_COMPRESSED' if wire_codec=='rice03' else 'USER_FIXED_RAW_WINDOW')
        parameter_words(width, height)
        if type(max_inflight) is not int or not 1 <= max_inflight <= 6:
            raise ValueError('max_inflight must be 1..6')
        self.max_inflight = max_inflight
        self.width, self.height, self.timeout = width, height, timeout
        self.sock = socket.create_connection((host, port), timeout)
        self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF,2*1024*1024)
        self.sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF,2*1024*1024)
        self.transport_metrics['socket_send_buffer']=self.sock.getsockopt(socket.SOL_SOCKET,socket.SO_SNDBUF)
        self.transport_metrics['socket_receive_buffer']=self.sock.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF)
        self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        # return_lossless (HELLO flag 0x1000): the board returns every frame lossless while
        # the upstream may still be near-lossless (test plan: rain highlight dots came
        # from the near-lossless return hop).
        try:
            self.sock.sendall(Header(HELLO, width=width, height=height,flags=3*int(wire_codec=='rice03')|(near_shift<<8)|(0x1000 if return_lossless else 0)).pack())
            self.caps = read_json(self.sock, HELLO | RESPONSE)
            if self.caps.get('checksum') != 'XXH32_WIRE_SEED0':raise ValueError('wire checksum domain mismatch')
            if self.caps.get('version') != VERSION or width > self.caps.get('max_width', 0) or height > self.caps.get('max_height', 0):
                raise ValueError('board service protocol/geometry does not cover this session')
            if self.caps.get('near_shift') != near_shift:raise ValueError('near precision negotiation mismatch')
            if self.caps.get('return_lossless', False) != self.return_lossless:raise ValueError('return precision negotiation mismatch')
            if return_lossless and self.caps.get('return_precision_split') is not True:raise ValueError('board lacks split return precision capability')
            if self.caps.get('selected_codec') != wire_codec:
                raise ValueError('wire codec negotiation mismatch')
            if self.caps.get("pixel_format") != PIXEL_FORMAT:
                raise ValueError("wrong pixel format")
            if require_fpga and self.caps.get("backend") != "FPGA_MMIO":
                raise ValueError("refusing mock backend for FPGA client")
            # Rice layout 2 (full-resolution luma, zero groups) is all the
            # encoder in rice_codec produces and the layout-2 FPGA accepts.
            if self.caps.get('rice_layout') != 2:
                raise ValueError('board FPGA codec is not Rice layout 2')
            # Encoder IP 5.0 returns P6TANS02 (tANS) packets, not Rice02.
            if self.caps.get('return_codec') != 'tans02':
                raise ValueError('board FPGA return encoder is not P6TANS02')
            # Enhance IP 1.5: 24 parameters, the last is clarity (local contrast).
            if self.caps.get('enhance_params') != 24:
                raise ValueError('board enhance core lacks clarity (needs 24 parameters)')
            self.bands = self.caps.get('decoder_bands', 3)
            if self.bands not in (3, 4):
                raise ValueError('board reports an unsupported decoder band count')
            self.transport_metrics['decoder_bands'] = self.bands
            self.transport_metrics['compression_selection'] = f'RICE03_{self.bands}_PARALLEL_BANDS'
            if self.caps.get("state") != "OWNED" or self.caps.get("slots") not in (3,6):
                raise ValueError("invalid native ownership/depth")
            if expected_identity is not None and self.caps.get("identity") != expected_identity:
                raise ValueError("server build identity mismatch")
        except BaseException:
            self.sock.close()
            raise
        self.summary = None
        self._thread = None
        self._encoder = None
        self._cancel = threading.Event()
        self._cv = threading.Condition()
        self._pending = deque()
        self._sender_error = []

    def exchange(self, frames):
        if self._thread is not None:
            raise RuntimeError("session exchange may only run once")

        prepared = deque()
        done = object()
        order = dict(last=None)

        def prepare(frame):
            """Validate order/size and encode one frame (runs in one thread only)."""
            last = order['last']
            if (not 0 <= frame.frame_id < (1 << 64) or not 0 <= frame.pts < (1 << 63)
                    or not 0 < frame.time_base_num <= 10**9
                    or not 0 < frame.time_base_den <= 10**9):
                raise ValueError("invalid frame id/PTS/time base")
            if last is not None and (frame.frame_id <= last[0] or frame.pts <= last[1]
                    or (frame.time_base_num, frame.time_base_den) != last[2]):
                raise ValueError("out-of-order input or changed time base")
            if len(frame.payload) != self.width * self.height * 2:
                raise ValueError("invalid YUYV payload length")
            order['last'] = (frame.frame_id, frame.pts, (frame.time_base_num, frame.time_base_den))
            params = parameter_words(self.width, self.height, frame.parameters)
            started=time.perf_counter()
            if self.wire_codec=='rice03' and self.frame_shift is not None:
                # Decided before encoding (one encode per frame); the policy may
                # learn from the resulting size through an optional observe().
                shift=self.frame_shift(frame)
                if type(shift) is not int or not 0<=shift<=self.near_shift:raise ValueError('frame_shift outside 0..near_shift')
                wire,flag,digest=self._encode(frame.payload,self.width,self.height,shift,self.bands)
                observe=getattr(self.frame_shift,'observe',None)
                if observe is not None:observe(shift,len(wire) if flag else len(frame.payload))
            elif self.wire_codec=='rice03':
                shift=self.near_shift
                wire,flag,digest=self._encode(frame.payload,self.width,self.height,shift,self.bands)
            else:
                shift=0
                wire,flag,digest=frame.payload,0,self._checksum(frame.payload)
            self.transport_metrics['encode_seconds']+=time.perf_counter()-started
            self._upload_shift[frame.frame_id]=shift
            # A raw (uncompressed) frame tells the board its chosen precision in
            # flag bits 8-9, so the return hop does not fall back to near_shift.
            return frame, params, wire, flag | (shift << 8 if flag == 0 else 0), digest

        def encode_ahead():
            # Keeps encode_ahead frames encoded ahead of the window so a freed board
            # slot is refilled at once instead of after a 3-8 ms host encode; that
            # encode on the critical path starved the board when the host was slow.
            try:
                for frame in frames:
                    if self._cancel.is_set():
                        return
                    item = prepare(frame)
                    with self._cv:
                        if not self._cv.wait_for(lambda: self._cancel.is_set() or len(prepared) < self.encode_ahead, self.timeout):
                            raise TimeoutError('bounded host window deadline')
                        if self._cancel.is_set():
                            return
                        prepared.append(item)
                        self._cv.notify_all()
                item = done
            except BaseException as exc:
                item = exc
            with self._cv:
                prepared.append(item)
                self._cv.notify_all()

        def next_inline(iterator):
            # encode_ahead=0: the earlier behaviour, encode only once a slot is free.
            with self._cv:
                if not self._cv.wait_for(lambda: self._cancel.is_set() or
                                        len(self._pending) < self.max_inflight, self.timeout):
                    raise TimeoutError('bounded host window deadline')
                if self._cancel.is_set():
                    return None
            frame = next(iterator, done)
            return done if frame is done else prepare(frame)

        def next_prepared():
            with self._cv:
                if not self._cv.wait_for(lambda: self._cancel.is_set() or prepared, self.timeout):
                    raise TimeoutError('host encoder deadline')
                if self._cancel.is_set():
                    return None
                item = prepared.popleft()
                self._cv.notify_all()
            if isinstance(item, BaseException):
                raise item
            return item

        def send():
            try:
                if self.encode_ahead:
                    take = next_prepared
                else:
                    iterator = iter(frames)
                    take = lambda: next_inline(iterator)
                while True:
                    item = take()
                    if item is None:
                        return
                    if item is done:
                        break
                    frame, params, wire, flag, digest = item
                    # Large raw transfers compete for the board's network CPU.
                    # Prepare the next frame early, but serialize its wire send.
                    allowed=1 if self.wire_codec=='rice03' and flag&3==0 else self.max_inflight
                    with self._cv:
                        if not self._cv.wait_for(lambda: self._cancel.is_set() or len(self._pending) < allowed,
                                                self.timeout):
                            raise TimeoutError("bounded host window deadline")
                        if self._cancel.is_set():
                            return
                        self._pending.append((frame.frame_id, frame.pts, frame.time_base_num, frame.time_base_den))
                        self.transport_metrics['max_pending_frames']=max(self.transport_metrics['max_pending_frames'],len(self._pending))
                    self.transport_metrics['serial_fallback_frames']+=int(self.wire_codec=='rice03' and flag&3==0)
                    header = Header(FRAME, frame.frame_id, frame.pts, frame.time_base_num,
                                    frame.time_base_den, len(wire), PARAMETERS.size,
                                    self.width, self.height,flag,digest)
                    self.sock.sendall(header.pack()+params)
                    self.sock.sendall(wire)
                    self.transport_metrics['input_raw_bytes']+=len(frame.payload)
                    self.transport_metrics['input_wire_bytes']+=len(wire)
                    self.transport_metrics['compressed_input_frames']+=int(bool(flag&3))
                self.sock.sendall(Header(FIN).pack())
            except BaseException as exc:
                self._sender_error.append(exc)
                try:
                    self.sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        if self.encode_ahead:
            # Started before the sender so close() can always join it.
            self._encoder = threading.Thread(target=encode_ahead, name="yuyv-host-encode", daemon=False)
            self._encoder.start()
        self._thread = threading.Thread(target=send, name="yuyv-host-send", daemon=False)
        self._thread.start()

        def timed_decode(wire, flags, raw_size, digest):
            started = time.perf_counter()
            return self._decode(wire, flags, raw_size, digest), time.perf_counter()-started

        # The return stream is one serial P6TANS02 bitstream per frame (~35 ms at
        # 1080p lossless on the PC), but frames are independent: decoding
        # DECODE_AHEAD of them on worker threads (ctypes releases the GIL) keeps
        # the receiver reading the socket. Results are still yielded in order.
        pool = ThreadPoolExecutor(DECODE_AHEAD, thread_name_prefix='yuyv-host-decode') if self.encode_ahead else None
        decoding = deque()

        def deliver(entry):
            h, meta, future, shift = entry
            payload, elapsed = future.result()
            self.transport_metrics['decode_seconds'] += elapsed
            self.transport_metrics['output_raw_bytes'] += len(payload)
            self.transport_metrics['output_wire_bytes'] += h.payload_bytes
            self.transport_metrics['compressed_output_frames'] += int(bool(h.flags))
            upload = self._upload_shift.pop(h.frame_id, shift)
            # near_frames: a near-lossless hop either way; near_return_frames: on the return.
            self.transport_metrics['near_frames'] = self.transport_metrics.get('near_frames', 0)+int(max(upload, shift) > 0)
            self.transport_metrics['near_return_frames'] = self.transport_metrics.get('near_return_frames', 0)+int(shift > 0)
            # The real return size calibrates the precision selector (optional observe_return).
            observe_return = getattr(self.frame_shift, 'observe_return', None)
            if observe_return is not None:
                observe_return(h.frame_id, shift, h.payload_bytes)
            return Output(h.frame_id, h.pts, payload, h.time_base_num, h.time_base_den, *meta[:5],
                          transport_shift=shift, upload_shift=upload)
        try:
            while True:
                while decoding and (len(decoding) >= DECODE_AHEAD or decoding[0][2].done()):
                    yield deliver(decoding.popleft())
                try:
                    h = read_header(self.sock)
                except (OSError, ConnectionError, ValueError) as exc:
                    # A failed sender shuts the socket; report its cause, not the
                    # resulting disconnect.
                    if self._sender_error:
                        raise self._sender_error[0] from exc
                    raise
                if h.op == (FIN | RESPONSE):
                    while decoding:
                        yield deliver(decoding.popleft())
                    if h.parameter_bytes or h.payload_bytes > 131072:
                        raise ValueError("invalid FIN reply")
                    self.summary = json.loads(recv_exact(self.sock, h.payload_bytes))
                    with self._cv:
                        if self._pending:
                            raise ValueError("FIN before all results")
                    break
                if h.op == ERROR:
                    if h.parameter_bytes or h.payload_bytes > 131072:
                        raise ValueError('invalid ERROR response length')
                    raise RuntimeError(json.loads(recv_exact(self.sock, h.payload_bytes))["error"])
                raw_size = self.width * self.height * 2
                if (h.op != (FRAME | RESPONSE) or h.flags not in (0,2) or not 0 < h.payload_bytes <= raw_size
                        or (h.flags==0 and h.payload_bytes!=raw_size)
                        or (h.flags and (self.wire_codec!='rice03' or h.payload_bytes>=raw_size))
                        or h.parameter_bytes != RESULT.size or (h.width, h.height) != (self.width, self.height)):
                    raise ValueError("invalid FRAME reply")
                meta = RESULT.unpack(recv_exact(self.sock, RESULT.size))
                if meta[0] != 1 or meta[1] or meta[5]:
                    raise ValueError("hardware frame_count/stream_errors/reserved mismatch")
                wire=recv_exact(self.sock, h.payload_bytes)
                # P6TANS02 (as P6RICE02) header byte 17 is the near shift this frame was returned with.
                shift = wire[17] if h.flags == 2 and len(wire) > 17 else 0
                if self.return_lossless and shift:raise ValueError('board violated lossless return negotiation')

                def release():
                    with self._cv:
                        if not self._pending or self._pending.popleft() != (
                                h.frame_id, h.pts, h.time_base_num, h.time_base_den):
                            raise ValueError("reply order/PTS mismatch")
                        self._cv.notify_all()
                # The board has already released this slot; refill it before the
                # host decode so the decode stays off the board's critical path
                # (encode_ahead=0 keeps the earlier order for A/B).
                if pool is not None:
                    release()
                    decoding.append((h, meta, pool.submit(timed_decode, wire, h.flags, raw_size, h.checksum), shift))
                else:
                    done = Future(); done.set_result(timed_decode(wire, h.flags, raw_size, h.checksum))
                    release()
                    yield deliver((h, meta, done, shift))
            self._thread.join(self.timeout)
            if self._thread.is_alive():
                raise TimeoutError("sender did not finish")
            if self._sender_error:
                raise self._sender_error[0]
        finally:
            if pool is not None:
                pool.shutdown(wait=True, cancel_futures=True)
            self.close()

    def close(self):
        self._cancel.set()
        with self._cv:
            self._cv.notify_all()
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        for thread, role in ((self._thread, 'sender'), (self._encoder, 'encoder')):
            if thread is not None and thread is not threading.current_thread():
                # The encoder stops at its next frame boundary once cancelled.
                thread.join(self.timeout)
                if thread.is_alive():
                    raise TimeoutError(f"host {role} retained ownership")
        self.sock.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
