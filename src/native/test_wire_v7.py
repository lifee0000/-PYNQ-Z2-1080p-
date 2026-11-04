"""Protocol v7 wire integrity/ownership acceptance at 1080p and 720p. Localhost mock; no board claims."""
import json,os,socket,time,threading,unittest
from pathlib import Path
from binding import mock
from protocol import Header,HELLO,FRAME,FIN,CANCEL,RESPONSE,Session,Frame,PARAMETERS,PIXEL_FORMAT,RESULT,VERSION,parameter_words,read_json,read_header,recv_exact
from rice_codec import adaptive_encode,checksum

ROOT=Path(__file__).resolve().parent
W,H=1920,1080
RAW=W*H*2
_dll_dir=os.add_dll_directory(str(ROOT)) if os.name=='nt' else None

class WireV7Tests(unittest.TestCase):
    def setUp(self):
        self.server=mock(ROOT/('y50_native.dll' if os.name=='nt' else 'liby50_native.so'),timeout_ms=350)
        self.port=self.server.status()['port']
    def tearDown(self):self.server.stop();self.server.close()
    def idle(self):
        limit=time.monotonic()+4
        while True:
            state=self.server.status()
            if state['state']=='IDLE':
                self.assertEqual(state['first_fault'],'');return state
            self.assertLess(time.monotonic(),limit);time.sleep(.005)
    def open(self,codec='raw',shift=0,w=W,h=H):
        s=socket.create_connection(('127.0.0.1',self.port),2)
        try:
            s.sendall(Header(HELLO,width=w,height=h,flags=(3 if codec=='rice03' else 0)|(shift<<8)).pack())
            caps=read_json(s,HELLO|RESPONSE)
            self.assertEqual(caps['version'],7);self.assertEqual(caps['checksum'],'XXH32_WIRE_SEED0')
            self.assertEqual((caps['max_width'],caps['max_height']),(1920,1080))
            self.assertEqual(caps['near_shift'],shift);self.assertEqual(caps['enhance_params'],24);return s
        except BaseException:
            # A refused HELLO must not leak the socket (ResourceWarning).
            s.close();raise
    def packet(self,wire,flag=0,digest=None):
        return Header(FRAME,1,1,1,50,len(wire),PARAMETERS.size,W,H,flag,checksum(wire) if digest is None else digest).pack()+parameter_words(W,H,{'mode':0})+wire
    def reject(self,packet,codec='raw',shift=0,partial=False):
        before=self.server.status()
        with self.open(codec,shift) as s:
            s.sendall(packet)
            if partial:s.shutdown(socket.SHUT_WR)
            try:self.assertEqual(s.recv(1),b'')
            except (ConnectionResetError,ConnectionAbortedError):pass
        after=self.idle()
        for name in ('received','processed','sent'):self.assertEqual(after[name],before[name],name)
        self.assertGreater(after['cancelled_sessions'],before['cancelled_sessions'])
    def test_raw_corruption_fails_before_processing(self):
        raw=bytes(RAW);changed=b'\1'+raw[1:]
        self.reject(self.packet(changed,digest=checksum(raw)))
    def test_compressed_corruption_fails_before_processing(self):
        wire,flag,digest=adaptive_encode(bytes([64,128,64,128])*(RAW//4),W,H,3)
        self.assertEqual(flag,3)
        changed=wire[:-1]+bytes([wire[-1]^1])
        self.reject(self.packet(changed,flag,digest),'rice03',3)
    def test_precision_above_negotiated_maximum_fails_before_processing(self):
        # A frame may use any near shift up to the negotiated maximum, never above.
        wire,flag,_=adaptive_encode(bytes(RAW),W,H,3)
        self.assertEqual(flag,3);self.reject(self.packet(wire,flag),'rice03',2)
    def test_per_frame_shift_below_maximum_round_trips(self):
        # Shift-1 session: lossless and shift-1 frames mixed; each returns at its own shift.
        payloads=[bytes([40+i*7,128,90+i,128])*(RAW//4) for i in range(6)]
        with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=1,
                     frame_shift=lambda frame:frame.frame_id%2) as s:
            out=list(s.exchange(Frame(i,i,p,{'mode':0}) for i,p in enumerate(payloads)))
        self.assertEqual([o.transport_shift for o in out],[i%2 for i in range(6)])
        for i,o in enumerate(out):
            if i%2==0:self.assertEqual(o.payload,payloads[i])   # lossless frames are exact
        self.idle()
    def test_return_lossless_splits_the_two_hops(self):
        # HELLO 0x1000: shift-1 frames go up near-lossless but every frame comes back
        # lossless, so a near frame carries only the upstream hop's error (<= 1 level).
        payloads=[bytes([40+i*7,128,90+i,129])*(RAW//4) for i in range(6)]
        class Policy:
            returns=[]
            def __call__(self,frame):return frame.frame_id%2
            def observe_return(self,frame_id,shift,wire_bytes):self.returns.append((frame_id,shift,wire_bytes))
        with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=1,
                     frame_shift=Policy(),return_lossless=True) as s:
            self.assertIs(s.caps['return_lossless'],True);self.assertIs(s.caps['return_precision_split'],True)
            out=list(s.exchange(Frame(i,i,p,{'mode':0}) for i,p in enumerate(payloads)))
            metrics=s.transport_metrics
        self.assertEqual([o.transport_shift for o in out],[0]*6)
        # The report still shows which frames went up near-lossless.
        self.assertEqual([o.upload_shift for o in out],[i%2 for i in range(6)])
        self.assertEqual((metrics['near_frames'],metrics['near_return_frames']),(3,0))
        # The selector learns every real return size, with the shift it came back at.
        self.assertEqual([(i,shift) for i,shift,_ in Policy.returns],[(i,0) for i in range(6)])
        self.assertEqual(sum(b for *_,b in Policy.returns),metrics['output_wire_bytes'])
        for i,o in enumerate(out):
            error=max(abs(a-b) for a,b in zip(o.payload,payloads[i]))
            self.assertEqual(error,0 if i%2==0 else error);self.assertLessEqual(error,1)
        self.idle()
    def test_return_lossless_flag_only_on_a_near_hello(self):
        # 0x1000 is a HELLO flag: refused on a frame, on a raw session and by the PC
        # client without a near-lossless rice03 session.
        self.reject(self.packet(bytes(RAW),0x1000))
        with self.assertRaisesRegex(RuntimeError,'unsupported P6 session geometry/codec'):
            with socket.create_connection(('127.0.0.1',self.port),2) as s:
                s.sendall(Header(HELLO,width=W,height=H,flags=0x1000).pack());read_json(s,HELLO|RESPONSE)
        self.idle()
        for codec,shift in (('raw',0),('rice03',0)):
            with self.subTest(codec=codec,shift=shift),self.assertRaises(ValueError):
                Session('127.0.0.1',self.port,W,H,require_fpga=False,wire_codec=codec,near_shift=shift,return_lossless=True)
        self.idle()
    def test_raw_fallback_frame_keeps_its_own_shift(self):
        # A frame chosen lossless in a shift-3 session whose lossless upstream
        # packet is not smaller than raw goes up raw; its return must stay
        # lossless (the board used to fall back to the session's shift 3).
        import random
        noise=random.Random(7).randbytes(RAW)
        with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=3,frame_shift=lambda frame:0) as s:
            out=list(s.exchange([Frame(0,0,noise,{'mode':0})]))
            self.assertEqual(s.transport_metrics['compressed_input_frames'],0)
        self.assertEqual(out[0].payload,noise)
        self.idle()
    def test_raw_frame_shift_above_session_rejected(self):
        p=bytearray(self.packet(bytes(RAW),0x100));self.reject(p,'rice03',0)
    def test_band_count_mismatch_fails_before_processing(self):
        wire,flag,_=adaptive_encode(bytes(RAW),W,H,0)
        bad=wire[:17]+b'\2'+wire[18:]
        self.reject(self.packet(bad,flag),'rice03')
    def test_unnegotiated_compression_fails_before_processing(self):
        wire,flag,_=adaptive_encode(bytes(RAW),W,H,0)
        self.reject(self.packet(wire,flag))
    def test_partial_payload_disconnect_recovers(self):
        self.reject(self.packet(bytes(RAW))[:-1],partial=True)
    def test_stalled_payload_deadline_recovers(self):
        self.reject(self.packet(bytes(RAW))[:-1])
    def test_cancel_without_frames_recovers(self):self.reject(Header(CANCEL).pack())
    def test_reserved_header_bits_rejected(self):
        p=bytearray(self.packet(bytes(RAW)));p[56]=1;self.reject(p)
    def test_valid_frames_after_failure_reuse_buffers(self):
        self.reject(self.packet(bytes(RAW),digest=1))
        # Wrap the bounded slots and alternate compressed/raw entropy fallback,
        # at 1080p and then 720p on the same 1080p-sized server buffers.
        for w,h in ((W,H),(1280,720)):
            payloads=[bytes([i])*(w*h*2) for i in range(8)]
            with Session('127.0.0.1',self.port,w,h,require_fpga=False,max_inflight=6,near_shift=0) as s:
                outputs=[]
                for out in s.exchange(Frame(i,i,p,{'mode':0}) for i,p in enumerate(payloads)):
                    time.sleep(.01);outputs.append(out.payload)
            self.assertEqual(outputs,payloads);self.idle()
    def test_rice_requires_whole_groups(self):
        # Raw sessions accept any even geometry; Rice needs a width multiple of 128.
        with self.assertRaises(RuntimeError):
            with self.open('rice03',0,1366,768):pass
        self.idle()
        with self.open('raw',0,1366,768):pass
        self.idle()
    def test_geometry_beyond_1080p_rejected(self):
        for w,h in ((1922,1080),(1920,1082)):
            with self.assertRaises(RuntimeError):
                with self.open('raw',0,w,h):pass
            self.idle()
    def host_threads_end(self):
        limit=time.monotonic()+4
        while any(t.name.startswith(('yuyv-host-send','yuyv-host-encode','yuyv-host-decode')) for t in threading.enumerate()):
            self.assertLess(time.monotonic(),limit,'host send/encode thread retained');time.sleep(.01)
    def test_out_of_order_input_reports_its_cause(self):
        # Validation runs in the encode-ahead thread; its error, not the
        # resulting socket shutdown, must reach the caller.
        frames=[Frame(i,i,bytes(RAW),{'mode':0}) for i in (1,3,2)]
        with self.assertRaisesRegex(ValueError,'out-of-order'):
            with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=0) as s:
                for _ in s.exchange(frames):pass
        self.idle();self.host_threads_end()
    def test_frames_pulled_ahead_stay_within_the_published_limit(self):
        # run_video sizes a per-frame side queue with frames_ahead_limit; a
        # Session must never pull more source frames than that ahead of its yields.
        from protocol import frames_ahead_limit
        payloads=[bytes([16+i,128])*(W*H) for i in range(4)]
        for ahead in (0,2):
            state=dict(pulled=0,yielded=0,peak=0)
            def source():
                for i in range(40):
                    state['pulled']+=1;state['peak']=max(state['peak'],state['pulled']-state['yielded'])
                    yield Frame(i,i,payloads[i%4],{'mode':0})
            with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=2,encode_ahead=ahead) as s:
                for _ in s.exchange(source()):state['yielded']+=1;time.sleep(.005)
            self.assertLessEqual(state['peak'],frames_ahead_limit(6,ahead),ahead)
            self.idle()
    def test_source_error_reports_its_cause(self):
        def source():
            yield Frame(1,1,bytes(RAW),{'mode':0})
            raise RuntimeError('source broke')
        with self.assertRaisesRegex(RuntimeError,'source broke'):
            with Session('127.0.0.1',self.port,W,H,require_fpga=False,max_inflight=6,near_shift=0) as s:
                for _ in s.exchange(source()):pass
        self.idle();self.host_threads_end()

class FourBandTests(unittest.TestCase):
    def test_four_decoder_board_gets_four_band_packets(self):
        server=mock(ROOT/('y50_native.dll' if os.name=='nt' else 'liby50_native.so'),timeout_ms=2000,bands=4)
        try:
            port=server.status()['port'];self.assertEqual(server.status()['decoder_bands'],4)
            payloads=[bytes([16+i,128])*(W*H) for i in range(4)]
            with Session('127.0.0.1',port,W,H,require_fpga=False,max_inflight=6,near_shift=0) as s:
                self.assertEqual(s.bands,4)
                out=[o.payload for o in s.exchange(Frame(i,i,p,{'mode':0}) for i,p in enumerate(payloads))]
                self.assertEqual(s.transport_metrics['decoder_bands'],4)
            self.assertEqual(out,payloads)
            # A three-band packet is refused by a four-decoder board before any processing.
            wire,flag,_=adaptive_encode(bytes(RAW),W,H,0,3)
            with socket.create_connection(('127.0.0.1',port),2) as sock:
                sock.sendall(Header(HELLO,width=W,height=H,flags=3).pack());read_json(sock,HELLO|RESPONSE)
                sock.sendall(Header(FRAME,1,1,1,50,len(wire),PARAMETERS.size,W,H,flag,checksum(wire)).pack()+parameter_words(W,H,{'mode':0})+wire)
                try:self.assertEqual(sock.recv(1),b'')
                except (ConnectionResetError,ConnectionAbortedError):pass
        finally:
            server.stop();server.close()

class ClientIntegrityTests(unittest.TestCase):
    def forged(self,payload,flags,digest,layout=2,enhance=24,returned='tans02'):
        listener=socket.socket();listener.bind(('127.0.0.1',0));listener.listen(1);listener.settimeout(3)
        port=listener.getsockname()[1];errors=[]
        def peer():
            try:
                with listener.accept()[0] as conn:
                    conn.settimeout(3);self.assertEqual(read_header(conn).op,HELLO)
                    caps=json.dumps(dict(version=VERSION,max_width=1920,max_height=1080,checksum='XXH32_WIRE_SEED0',near_shift=0,selected_codec='raw',pixel_format=PIXEL_FORMAT,backend='MOCK_TRANSPORT_ONLY',state='OWNED',slots=6,**({'rice_layout':layout} if layout else {}),**({'enhance_params':enhance} if enhance else {}),**({'return_codec':returned} if returned else {}))).encode()
                    conn.sendall(Header(HELLO|RESPONSE,payload_bytes=len(caps)).pack()+caps)
                    request=read_header(conn);recv_exact(conn,request.parameter_bytes+request.payload_bytes)
                    self.assertEqual(read_header(conn).op,FIN)
                    reply=Header(FRAME|RESPONSE,request.frame_id,request.pts,request.time_base_num,request.time_base_den,len(payload),RESULT.size,16,12,flags,digest)
                    conn.sendall(reply.pack()+RESULT.pack(1,0,1,1,1,0)+payload)
            except (ConnectionResetError,ConnectionAbortedError,BrokenPipeError):pass
            except BaseException as exc:errors.append(exc)
            finally:listener.close()
        t=threading.Thread(target=peer);t.start()
        if layout!=2 or enhance!=24 or returned!='tans02':
            # A board without the layout-2 FPGA codec, the P6TANS02 return
            # encoder or the 24-parameter (clarity) enhance core is refused at HELLO.
            try:
                with self.assertRaisesRegex(ValueError,'layout 2' if layout!=2 else 'P6TANS02' if returned!='tans02' else '24 parameters'):
                    Session('127.0.0.1',port,16,12,require_fpga=False,wire_codec='raw')
            finally:t.join(5);self.assertFalse(t.is_alive())
            return
        try:
            with Session('127.0.0.1',port,16,12,require_fpga=False,wire_codec='raw') as s:
                with self.assertRaises((ValueError,RuntimeError)):
                    list(s.exchange([Frame(1,1,bytes(384),{'mode':0})]))
        finally:t.join(5);self.assertFalse(t.is_alive());self.assertEqual(errors,[])
    def test_corrupt_return_is_not_displayed(self):self.forged(b'\1'+bytes(383),0,checksum(bytes(384)))
    def test_unnegotiated_return_codec_is_rejected(self):self.forged(b'invalid',2,checksum(b'invalid'))
    def test_layout_one_board_is_refused(self):
        for layout in (None,1):
            with self.subTest(layout=layout):self.forged(bytes(384),0,checksum(bytes(384)),layout)
    def test_old_enhance_core_board_is_refused(self):
        for enhance in (None,21,22,23):
            with self.subTest(enhance=enhance):self.forged(bytes(384),0,checksum(bytes(384)),2,enhance)
    def test_rice02_return_board_is_refused(self):
        for returned in (None,'rice02'):
            with self.subTest(returned=returned):self.forged(bytes(384),0,checksum(bytes(384)),2,24,returned)

class SplitPrecisionValidation(unittest.TestCase):
    def test_invalid_options_are_rejected_before_connecting(self):
        from unittest.mock import patch
        for codec,shift,value in [('rice03',0,True),('raw',1,True),('rice03',1,1),('rice03',1,'true')]:
            with self.subTest(codec=codec,shift=shift,value=value), patch('protocol.socket.create_connection') as connect:
                with self.assertRaises(ValueError):
                    Session('127.0.0.1',1,W,H,wire_codec=codec,near_shift=shift,return_lossless=value)
                connect.assert_not_called()

    def test_feature_flag_is_only_valid_in_hello(self):
        packet=Header(HELLO,width=W,height=H,flags=0x1103).pack()
        self.assertEqual(Header.unpack(packet).flags,0x1103)
        with self.assertRaises(ValueError):Header.unpack(Header(FRAME,width=W,height=H,flags=0x1000).pack())


if __name__=='__main__':unittest.main(verbosity=2)
