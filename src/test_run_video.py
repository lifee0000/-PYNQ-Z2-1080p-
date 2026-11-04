"""Ordered file-pipeline and shutdown tests against localhost MOCK; no board."""
from collections import deque
from contextlib import ExitStack
from fractions import Fraction
import hashlib
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import unittest
from unittest.mock import patch

import av
import numpy as np

import run_video
from native.binding import mock


LIBRARY=Path(__file__).resolve().parent/'native'/('y50_native.dll' if os.name=='nt' else 'liby50_native.so')


def make_video(path,pts=(0,40,120,160),audio=False):
    packets=[]
    with av.open(str(path),'w') as output:
        video=output.add_stream('ffv1',rate=25)
        video.width,video.height=64,48
        video.pix_fmt='bgr0'
        video.time_base=video.codec_context.time_base=Fraction(1,1000)
        sound=output.add_stream('pcm_s16le',rate=8000) if audio else None
        if sound is not None:sound.layout='mono'
        for index,timestamp in enumerate(pts):
            rgb=np.full((48,64,3),48+index%16*8,np.uint8)
            rgb[10:16,20:32]=96+index%16*8
            frame=av.VideoFrame.from_ndarray(rgb,format='rgb24')
            frame.pts,frame.time_base=timestamp,Fraction(1,1000)
            packets.extend(video.encode(frame))
        packets.extend(video.encode(None))
        if sound is not None:
            for sample in range(0,1600,160):
                frame=av.AudioFrame.from_ndarray(np.arange(sample,sample+160,dtype=np.int16)[None,:],format='s16',layout='mono')
                frame.sample_rate,frame.pts,frame.time_base=8000,sample,Fraction(1,8000)
                packets.extend(sound.encode(frame))
            packets.extend(sound.encode(None))
        for packet in sorted(packets,key=lambda item:item.dts*item.time_base):output.mux(packet)


def audio_packets(path):
    with av.open(str(path)) as source:
        return [(bytes(packet),packet.pts*packet.time_base,packet.dts*packet.time_base)
                for packet in source.demux(source.streams.audio[0]) if packet.size and packet.dts is not None]


class ProcessingGeometryTests(unittest.TestCase):
    def test_sources_up_to_720p_are_processed_natively(self):
        g=run_video.processing_geometry
        self.assertEqual(g(1280,720,1920,1080),(1280,720))
        self.assertEqual(g(960,540,1920,1080),(1280,720))
        self.assertEqual(g(1920,1080,1920,1080),(1920,1080))
        self.assertEqual(g(1280,960,1920,1080),(1920,1080))   # taller than 720p: has more detail
        self.assertEqual(g(1280,720,1920,1080,native=False),(1920,1080))
        self.assertEqual(g(1280,720,1280,720),(1280,720))

    def test_detail_preview_crop_matches_full_conversion(self):
        from pixels import unpack_rgb
        w,h=1280,720;payload=np.random.default_rng(9).integers(0,256,w*h*2,dtype=np.uint8).tobytes()
        x,y,pw,ph=window=run_video.preview_window(w,h)
        self.assertEqual((pw,ph),(960,540));self.assertEqual(x%2,0)
        np.testing.assert_array_equal(run_video.crop_rgb(payload,w,h,window),unpack_rgb(payload,w,h)[y:y+ph,x:x+pw])

    def test_auto_transport_is_texture_adaptive(self):
        r=run_video.resolve_transport
        self.assertEqual(r('auto',(1280,720)),'adaptive')
        self.assertEqual(r('auto',(1920,1080)),'adaptive')
        self.assertEqual(r('auto',(1920,1080),'raw'),'lossless')
        self.assertEqual(r('lossless',(1920,1080)),'lossless')
        self.assertEqual(r('fast',(1280,720)),'fast')

    def test_adaptive_shift_only_for_all_texture_frames_over_budget(self):
        import transport_adaptive as ta
        from protocol import Frame
        w,h=1920,1080;rng=np.random.default_rng(3)
        def payload(y):
            a=np.full((h,w,2),128,np.uint8);a[:,:,0]=y;return a.tobytes()
        textured=payload(rng.integers(40,200,(h,w),dtype=np.uint8))
        walled=payload(np.where(np.indices((h,w))[1]<w//4,120,rng.integers(40,200,(h,w))).astype(np.uint8))
        big,small=1_500_000,500_000
        def policy_after(size):
            policy=ta.TextureAdaptiveShift(w,h);policy.observe(0,size);return policy
        first=ta.TextureAdaptiveShift(w,h)
        self.assertEqual(first(Frame(0,0,textured,{})),0)                  # no size history yet: lossless
        self.assertEqual(policy_after(big)(Frame(1,1,textured,{})),1)      # all texture, over budget
        self.assertEqual(policy_after(small)(Frame(2,2,textured,{})),0)    # fits the budget: stay lossless
        self.assertEqual(policy_after(big)(Frame(3,3,walled,{})),0)        # 25% flat wall: never quantize
        self.assertGreater(ta.flat_share(walled,w,h),0.2);self.assertLess(ta.flat_share(textured,w,h),0.01)

    def test_saturated_texture_keeps_lossless_despite_exceeding_budget(self):
        import transport_adaptive as ta
        from protocol import Frame
        w,h=1280,720;rng=np.random.default_rng(14)
        a=np.full((h,w,2),128,np.uint8);a[:,:,0]=rng.integers(120,160,(h,w),dtype=np.uint8)
        a[:,1::2,1]=190  # Bright red texture, little RGB headroom.
        policy=ta.TextureAdaptiveShift(w,h);policy.observe(0,1_500_000)
        self.assertLess(ta.flat_share(a.tobytes(),w,h),ta.FLAT_ENTER)
        self.assertEqual(policy(Frame(0,0,a.tobytes(),{})),0)
        self.assertTrue(policy.last['gamut_guard'])
        self.assertEqual(policy.gamut_guard_frames,1)

    def test_real_return_size_calibrates_the_budget(self):
        # Test plan item 5: the selector starts from RETURN_RATIO and follows the real
        # return sizes (lossless-equivalent, so its own precision choice cannot move
        # the estimate), smoothed and bounded; a frame just under the budget with the
        # assumed ratio goes over it once the returns prove larger.
        import transport_adaptive as ta
        from types import SimpleNamespace
        yuyv=np.full(1920*1080*2,128,np.uint8);yuyv[0::2]=np.random.default_rng(3).integers(60,190,1920*1080);textured=yuyv.tobytes()
        sent=ta.LINK_BYTES_PER_SECOND/ta.TARGET_FPS/(1+ta.RETURN_RATIO)*.97
        selector=ta.TextureAdaptiveShift(1920,1080)
        for i in range(40):
            frame=SimpleNamespace(frame_id=i,payload=textured,parameters={})
            shift=selector(frame)
            if i==1:self.assertEqual(shift,0)        # under budget with the assumed 1.05
            selector.observe(shift,int(sent/(ta.SHIFT1_TO_LOSSLESS if shift else 1)))
            selector.observe_return(i,0,int(sent*1.3))
        self.assertAlmostEqual(selector.return_ratio,1.3,delta=.01)
        self.assertEqual(selector.returns_observed,40)
        self.assertTrue(selector.last['over_budget'])
        self.assertEqual(selector(SimpleNamespace(frame_id=40,payload=textured,parameters={})),1)
        # Bounded: an absurd return size moves the estimate at most to the limit.
        selector.observe(1,int(sent));selector.observe_return(40,0,10**12)
        self.assertLessEqual(selector.return_ratio,ta.RETURN_RATIO_LIMITS[1])
        selector.observe_return(999,0,1)           # unknown frame: ignored
        self.assertEqual(selector.returns_observed,41)

    def test_statistics_only_where_they_can_change_the_decision(self):
        # Test plan item 4: under the network budget a frame is lossless without
        # any statistic; with flat areas it is lossless without the colour check.
        import transport_adaptive as ta
        from protocol import Frame
        w,h=1280,720;rng=np.random.default_rng(15)
        texture=np.full((h,w,2),128,np.uint8);texture[:,:,0]=rng.integers(40,200,(h,w),dtype=np.uint8)
        flat=np.full((h,w,2),128,np.uint8)
        policy=ta.TextureAdaptiveShift(w,h)
        self.assertEqual(policy(Frame(0,0,texture.tobytes(),{})),0)          # no size history yet
        policy.observe(0,10_000)
        self.assertEqual(policy(Frame(1,1,texture.tobytes(),{})),0)          # under budget
        self.assertIsNone(policy.last['flat_share']);self.assertEqual(policy.risk_checks,0)
        policy=ta.TextureAdaptiveShift(w,h);policy.observe(0,1_500_000)     # size history over budget
        self.assertEqual(policy(Frame(2,2,flat.tobytes(),{})),0)             # over budget, flat
        self.assertIsNone(policy.last['gamut_risk_share']);self.assertEqual(policy.risk_checks,0)
        self.assertEqual(policy(Frame(3,3,texture.tobytes(),{})),1)          # the only candidate
        self.assertEqual(policy.risk_checks,1)

    def test_tone_and_colour_gain_are_included_in_headroom_guard(self):
        import transport_adaptive as ta
        w,h=1280,720
        a=np.full((h,w,2),128,np.uint8);a[:,:,0]=90;a[:,1::2,1]=190
        raw=a.tobytes()
        self.assertEqual(ta.gamut_risk_share(raw,w,h,dict(mode=5)),0.)
        risk=ta.gamut_risk_share(raw,w,h,dict(mode=5,gain_q8_8=384,knee_out=255,soft_q8_8=256,chroma_q8=256))
        self.assertGreater(risk,ta.GAMUT_ENTER)


@unittest.skipUnless(LIBRARY.is_file(),'native localhost MOCK is not built')
class NativeProcessingExport(unittest.TestCase):
    def test_720p_source_is_processed_at_720p_and_exported_at_1080p(self):
        with tempfile.TemporaryDirectory() as folder:
            source=Path(folder)/'s.mkv'
            with av.open(str(source),'w') as out:
                stream=out.add_stream('ffv1',rate=25);stream.width,stream.height=1280,720;stream.pix_fmt='bgr0'
                for i in range(6):
                    rgb=np.full((720,1280,3),60+i*20,np.uint8);rgb[300:400,500:700]=200
                    frame=av.VideoFrame.from_ndarray(rgb,format='rgb24');frame.pts=i*40;frame.time_base=Fraction(1,1000)
                    for p in stream.encode(frame):out.mux(p)
                for p in stream.encode(None):out.mux(p)
            server=mock(LIBRARY,1920,1080,timeout_ms=4000)
            try:
                real=run_video.Session
                def session(*args,**kwargs):
                    kwargs.update(require_fpga=False,expected_identity=None);return real(*args,**kwargs)
                with patch.object(run_video,'Session',session),patch.object(run_video,'load_identity',return_value={'state':'MOCK_TRANSPORT_ONLY'}):
                    report=run_video.process(source,Path(folder)/'o.mp4',host='127.0.0.1',port=server.status()['port'],transport_quality='auto',native_processing=True)
            finally:
                server.stop();server.close()
            self.assertEqual(report['status'],'PASS',report)
            self.assertEqual((report['processing_geometry'],report['output_geometry']),([1280,720],[1920,1080]))
            self.assertTrue(report['native_processing']);self.assertEqual(report['transport_quality']['profile'],'adaptive')
            # Flat synthetic frames: the adaptive policy keeps every frame lossless.
            trace=[json.loads(l) for l in (Path(folder)/'o.mp4.frames.jsonl').read_text(encoding='utf-8').splitlines()]
            self.assertEqual([t['transport_shift'] for t in trace],[0]*6)
            with av.open(str(Path(folder)/'o.mp4')) as c:
                self.assertEqual((c.streams.video[0].width,c.streams.video[0].height),(1920,1080))
                self.assertEqual(sum(1 for _ in c.decode(video=0)),6)


@unittest.skipUnless(LIBRARY.is_file(),'native localhost MOCK is not built')
class FilePipeline(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.folder=Path(self.temp.name)
        self.source=self.folder/'source.mkv'
        make_video(self.source)
        self.threads={thread.ident for thread in threading.enumerate()}
        self.server=mock(LIBRARY,128,48,timeout_ms=2000)
        self.stack=ExitStack()
        real_session=run_video.Session
        def session(*args,**kwargs):
            kwargs.update(require_fpga=False,expected_identity=None)
            return real_session(*args,**kwargs)
        self.stack.enter_context(patch.object(run_video,'Session',session))
        self.stack.enter_context(patch.object(run_video,'load_identity',return_value={'state':'MOCK_TRANSPORT_ONLY'}))
        self.stack.enter_context(patch.object(run_video,'OUTPUT_PRESETS',((64,48),)))

    def tearDown(self):
        self.stack.close()
        self.server.stop();self.server.close()
        self.temp.cleanup()

    def process(self,name='result.mkv',**kwargs):
        output=self.folder/name
        report=run_video.process(self.source,output,width=64,height=48,wire_codec='raw',
            host='127.0.0.1',port=self.server.status()['port'],**kwargs)
        active=[thread.name for thread in threading.enumerate() if thread.ident not in self.threads
                and thread.name.startswith(('video-decode-pack','video-cancel','video-encode-mux','yuyv-host-send','yuyv-host-encode','yuyv-host-decode'))]
        self.assertFalse(active,'pipeline threads retained after process returned: '+str(active))
        self.assertFalse(list(self.folder.glob('*.part*')))
        return output,report

    def test_export_worker_error_fails_the_run_without_leaking_threads(self):
        # Only the export worker converts full frames (no save_frames), so this
        # fault is raised in that thread and must surface in the report.
        def broken(*args):raise RuntimeError('export conversion broke')
        with patch.object(run_video,'unpack_rgb',broken):
            output,report=self.process(name='broken.mkv')
        self.assertEqual(report['status'],'FAIL');self.assertIn('export conversion broke',report['error'])
        self.assertFalse(output.exists())

    def test_curve_plan_overrides_words_and_sets_the_roi(self):
        from protocol import Output
        wire={}
        class EchoSession:
            def __init__(self,*args,**kwargs):
                self.caps={'state':'MOCK'};self.transport_metrics={};self.summary={};self.sock=socket.socket()
            def exchange(self,frames):
                for f in frames:
                    wire[f.frame_id]=dict(f.parameters)
                    yield Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
            def close(self):self.sock.close()
        with patch.object(run_video,'Session',EchoSession):
            output,report=self.process(name='curves.mkv',parameter_curves=dict(sharpen=[0,None,2.0]),curve_region=(32,0,32,48))
        self.assertEqual(report['status'],'PASS',report)
        self.assertEqual((wire[0]['sharp_q8_8'],wire[2]['sharp_q8_8']),(0,512))
        self.assertTrue(all(w['roi_enable']==1 and w['roi_x']==32 and w['roi_width']==32 and w['roi_height']==48 for w in wire.values()))
        self.assertEqual(report['parameter_curves'],dict(controls=['sharpen'],region=[32,0,32,48]))
        trace=[json.loads(l) for l in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([r['parameters']['sharp_q8_8'] for r in trace][:3:2],[0,512])

    def test_live_controls_stay_with_each_frame_across_read_ahead(self):
        from image_controls import ImageControls, LiveImageControls
        from protocol import Output
        first=ImageControls(preset='natural',brightness=9,sharpen=65,clarity=0)
        second=ImageControls(preset='balanced',brightness=-6,denoise=25,sharpen=20,clarity=35)
        live=LiveImageControls(first);wire={};previews=[]
        class EchoSession:
            def __init__(self,*args,**kwargs):
                self.caps={'state':'MOCK'};self.transport_metrics={};self.summary={};self.sock=socket.socket()
            def exchange(self,frames):
                held=deque()
                def reply(f):return Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
                for f in frames:
                    wire[f.frame_id]=dict(f.parameters);held.append(f)
                    if f.frame_id==3:live.update(second)
                    if len(held)>=3:yield reply(held.popleft())
                while held:yield reply(held.popleft())
            def close(self):self.sock.close()
        def notify(kind,data):
            if kind=='progress':previews.append(data)
        self.source=self.folder/'live.mkv';make_video(self.source,pts=tuple(range(0,40*40,40)))
        with patch.object(run_video,'Session',EchoSession):
            output,report=self.process(name='live_result.mkv',image_controls=live,notify=notify,
                                       preview_fps=60,realtime_preview=True,max_inflight=3)
        self.assertEqual(report['status'],'PASS',report)
        trace=[json.loads(l) for l in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(trace),40)
        self.assertEqual(trace[0]['image_controls'],first.to_dict())
        self.assertEqual(trace[-1]['image_controls'],second.to_dict())
        self.assertEqual(len(report['image_control_changes']),2)
        for row in trace:
            self.assertEqual(row['parameters'],wire[row['frame_id']])
            expected=first if row['image_controls']==first.to_dict() else second
            self.assertEqual(row['parameters']['sharp_q8_8'],round(expected.sharpen*1024/100))
            self.assertEqual(bool(row['parameters']['clarity']&255),bool(expected.clarity))
            self.assertIsNotNone(row['auto_decision'])
        for preview in previews:
            row=trace[preview['frames']-1]
            self.assertEqual(preview['parameters'],row['parameters'])
            self.assertEqual(preview['image_controls'],row['image_controls'])

    def test_manual_controls_use_existing_native_wire_and_leave_transport_lossless(self):
        from image_controls import ImageControls
        settings=ImageControls(preset='balanced',brightness=10,denoise=30,
                               sharpen=40,clarity=20,color_preservation=80)
        output,report=self.process(name='controls_wire.mkv',image_controls=settings)
        self.assertEqual(report['status'],'PASS',report)
        trace=[json.loads(l) for l in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual(len(trace),4)
        for row in trace:
            self.assertEqual(row['parameters']['sharp_q8_8'],410)
            self.assertEqual(row['parameters']['chroma_q8'],205)
            self.assertEqual(row['parameters']['noise_floor'],4)
            self.assertEqual(row['image_controls'],settings.to_dict())
            self.assertEqual(row['transport_shift'],0)

    def test_session_reading_ahead_to_its_limit(self):
        # Contract: a Session may pull up to frames_ahead_limit(max_inflight)
        # frames before yielding a result (a slow board; on the real board the
        # 5th frame overflowed a queue sized without the released-slot frame).
        # run_video's per-frame side queue must hold them all.
        # (The localhost MOCK cannot be slowed on Windows: its 100 us sleeps round to 0.)
        from protocol import frames_ahead_limit,Output
        depth=frames_ahead_limit(6);seen=[]
        class ReadAheadSession:
            def __init__(self,*args,max_inflight=6,**kwargs):
                self.caps={'state':'OWNED'};self.transport_metrics={};self.summary={}
                self.sock=socket.socket()
            def exchange(self,frames):
                held=deque()
                def reply(frame):
                    return Output(frame.frame_id,frame.pts,frame.payload,frame.time_base_num,frame.time_base_den,1,0,0,0,0)
                for frame in frames:
                    held.append(frame);seen.append(len(held))
                    if len(held)==depth:yield reply(held.popleft())
                while held:yield reply(held.popleft())
            def close(self):self.sock.close()
        self.source=self.folder/'long.mkv';make_video(self.source,pts=tuple(range(0,24*40,40)))
        with patch.object(run_video,'Session',ReadAheadSession):
            output,report=self.process(name='ahead.mkv',max_inflight=6)
        self.assertEqual(report['status'],'PASS',report)
        self.assertEqual(report['frames'],24)
        self.assertEqual(max(seen),depth)

    def test_knob_change_is_applied_at_hand_off_and_timed(self):
        # Test plan item 3: settings are applied when the Session takes a frame;
        # the report gives the latency and the frames keep the parameters they were sent with.
        from protocol import frames_ahead_limit,Output
        from image_controls import ImageControls,LiveImageControls
        depth=frames_ahead_limit(6);sent={}
        class EchoSession:
            def __init__(self,*args,**kwargs):
                self.caps={'state':'OWNED'};self.transport_metrics={};self.summary={};self.sock=socket.socket()
            def exchange(self,frames):
                held=deque()
                for frame in frames:
                    sent[frame.frame_id]=dict(frame.parameters);held.append(frame)
                    if len(held)==depth:
                        f=held.popleft();yield Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
                while held:
                    f=held.popleft();yield Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
            def close(self):self.sock.close()
        live=LiveImageControls(ImageControls());seen=[]
        def notify(kind,data):
            if kind=='progress':
                seen.append((data['frames'],data['settings_revision']))
                if data['frames']==6:live.update(ImageControls(brightness=20))
        self.source=self.folder/'long.mkv';make_video(self.source,pts=tuple(range(0,24*40,40)))
        with patch.object(run_video,'Session',EchoSession):
            output,report=self.process(name='knob.mkv',max_inflight=6,image_controls=live,preview_fps=60,
                                       realtime_preview=True,notify=notify)
        self.assertEqual(report['status'],'PASS',report)
        change=[c for c in report['image_control_changes'] if c.get('revision')==1]
        self.assertEqual(len(change),1);change=change[0]
        for key in ('frozen_ms','returned_ms','displayed_ms'):self.assertGreaterEqual(change[key],0)
        self.assertGreaterEqual(change['returned_ms'],change['frozen_ms'])
        first=change['frame_id']
        self.assertTrue(all(sent[i]['brightness']!=sent[first-1]['brightness'] for i in range(first,24)) or first==0)
        self.assertEqual([r for _,r in seen][-1],1)

    def test_detail_focus_moves_both_sides_together(self):
        # GUI T4: a click moves the 1:1 window while frames are on the board. An
        # echoing board returns each frame unchanged, so every preview's source
        # and result crops must be identical even when the focus moved in between.
        from protocol import frames_ahead_limit,Output
        depth=frames_ahead_limit(6)
        class EchoSession:
            def __init__(self,*args,**kwargs):
                self.caps={'state':'OWNED'};self.transport_metrics={};self.summary={};self.sock=socket.socket()
            def exchange(self,frames):
                held=deque()
                for frame in frames:
                    held.append(frame)
                    if len(held)==depth:
                        f=held.popleft();yield Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
                while held:
                    f=held.popleft();yield Output(f.frame_id,f.pts,f.payload,f.time_base_num,f.time_base_den,1,0,0,0,0)
            def close(self):self.sock.close()
        focus=[.5,.5];seen=[]
        def notify(kind,data):
            if kind=='progress':
                seen.append((tuple(data['preview_window']),np.array_equal(data['source'],data['result'])))
                focus[:]=[0.,0.] if len(seen)%2 else [1.,1.]
        self.source=self.folder/'long.mkv';make_video(self.source,pts=tuple(range(0,24*40,40)))
        with patch.object(run_video,'Session',EchoSession),patch.object(run_video,'PREVIEW_LIMIT',(16,12)):
            output,report=self.process(name='focus.mkv',max_inflight=6,preview_detail=True,preview_focus=focus,
                                       preview_fps=60,realtime_preview=True,notify=notify)   # paced: every frame previewed
            self.assertEqual(run_video.preview_window(64,48,(0.,0.)),(0,0,16,12))
            self.assertEqual(run_video.preview_window(64,48,(1.,1.)),(48,36,16,12))
        self.assertEqual(report['status'],'PASS',report)
        self.assertGreater(len(seen),3)
        self.assertTrue(all(same for _,same in seen),seen)
        self.assertGreater(len({window for window,_ in seen}),1)   # the window really moved
        self.assertEqual(run_video.preview_window(1280,720,(1.,0.)),(320,0,960,540))

    def test_v5_auto_policy_runs_in_sender_order_with_v5_records(self):
        make_video(self.source,pts=(120,160,240,280,360,400))
        updates=[]
        real=run_video.AutoOptimizerV5
        class Optimizer(real):
            def update(self,timestamp,*args,**kwargs):
                updates.append((timestamp,threading.current_thread().name,len(args)))
                return super().update(timestamp,*args,**kwargs)
        with patch.object(run_video,'AutoOptimizerV5',Optimizer):
            output,report=self.process(name='v5.mkv',auto_analysis_interval=2)
        self.assertEqual(report['status'],'PASS',report)
        self.assertEqual(report['auto_policy'],run_video.AUTO_POLICY_V5)
        saved=json.loads(Path(str(output)+'.json').read_text(encoding='utf-8'))
        self.assertEqual(saved['algorithm_sources_sha256'],{name:hashlib.sha256((run_video.ROOT/name).read_bytes()).hexdigest()
            for name in ('auto_v5.py','exposure_v4.py','image_controls.py','run_video.py')})
        # The ordered decode/pack producer thread runs the optimizer in frame order.
        self.assertEqual(updates,[(0,'video-decode-pack',4),(120,'video-decode-pack',4),(240,'video-decode-pack',4)])
        trace=[json.loads(line) for line in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertTrue(all(row['auto_decision']['policy']==run_video.AUTO_POLICY_V5 for row in trace))
        self.assertTrue(all(row['parameters']['mode'] in (4,5) for row in trace))

    def test_vfr_order_hashes_auto_interval_and_export(self):
        make_video(self.source,pts=(120,160,240,280,360,400))
        updates=[]
        real_controller=run_video.ExposureControllerV4
        class Controller(real_controller):
            def update(self,timestamp,*args,**kwargs):
                updates.append((timestamp,threading.current_thread().name))
                return super().update(timestamp,*args,**kwargs)
        with patch.object(run_video,'ExposureControllerV4',Controller):
            output,report=self.process(auto_analysis_interval=2,auto_policy='v4')
        self.assertEqual(report['status'],'PASS',report)
        self.assertEqual(report['frames'],6)
        self.assertEqual(updates,[(0,'video-decode-pack'),(120,'video-decode-pack'),(240,'video-decode-pack')])
        trace=[json.loads(line) for line in Path(str(output)+'.frames.jsonl').read_text(encoding='utf-8').splitlines()]
        self.assertEqual([row['frame_id'] for row in trace],list(range(6)))
        self.assertEqual([row['pts'] for row in trace],[0,40,120,160,240,280])
        self.assertEqual([row['auto_decision']['pts_ms'] for row in trace],[0,0,120,120,240,240])
        with av.open(str(self.source)) as source:
            for frame,row in zip(source.decode(video=0),trace):
                payload=run_video.pack_rgb(frame.to_ndarray(format='rgb24'))
                expected=hashlib.sha256(payload).hexdigest()
                self.assertEqual(row['input_sha256'],expected)
                self.assertEqual(row['output_sha256'],expected)
        with av.open(str(output)) as result:
            self.assertEqual([frame.pts*frame.time_base for frame in result.decode(video=0)],
                [Fraction(value,1000) for value in (0,40,120,160,240,280)])

    def test_audio_packets_survive_concurrent_mux(self):
        make_video(self.source,audio=True)
        original=audio_packets(self.source)
        output,report=self.process(auto=False)
        self.assertEqual(report['status'],'PASS',report)
        self.assertEqual(report['frames'],4)
        self.assertEqual(audio_packets(output),original)

    def test_cancel_while_preparation_queue_is_full(self):
        make_video(self.source,pts=tuple(index*40 for index in range(32)))
        packed=threading.Event();cancel=threading.Event();calls=0
        real_pack=run_video.pack_rgb
        def pack(rgb):
            nonlocal calls
            result=real_pack(rgb);calls+=1
            if calls==5:packed.set()
            return result
        # The consumer (Session request side) holds its first frame until the
        # producer has packed 5 frames, i.e. its bounded queue is full, then cancels.
        real_frame=run_video.Frame
        def frame(*args,**kwargs):
            if not packed.wait(3):raise RuntimeError('frame preparation did not run ahead of the consumer')
            cancel.set()
            return real_frame(*args,**kwargs)
        with patch.object(run_video,'pack_rgb',pack),patch.object(run_video,'Frame',frame):
            output,report=self.process(cancel=cancel)
        self.assertTrue(packed.is_set())
        self.assertEqual(report['status'],'CANCELLED',report)
        self.assertFalse(output.exists())

    def test_producer_failure_is_reported_and_cleans_threads(self):
        calls=0;real_fit=run_video.fit_rgb
        def fit(frame,*args):
            nonlocal calls
            calls+=1
            if calls==3:raise ValueError('producer conversion failed')
            return real_fit(frame,*args)
        with patch.object(run_video,'fit_rgb',fit):
            output,report=self.process(auto=False)
        self.assertEqual(report['status'],'FAIL',report)
        self.assertIn('producer conversion failed',report['error'])
        self.assertFalse(output.exists())

    def test_downstream_failure_stops_a_prefetching_producer(self):
        make_video(self.source,pts=tuple(index*40 for index in range(32)))
        packed=threading.Event();calls=0;real_pack=run_video.pack_rgb
        def pack(rgb):
            nonlocal calls
            result=real_pack(rgb);calls+=1
            if calls==10:packed.set()
            return result
        def unpack(*args):
            if not packed.wait(3):raise RuntimeError('preparation did not fill while output was blocked')
            raise ValueError('downstream conversion failed')
        with patch.object(run_video,'pack_rgb',pack),patch.object(run_video,'unpack_rgb',unpack):
            output,report=self.process(auto=False)
        self.assertTrue(packed.is_set())
        self.assertEqual(report['status'],'FAIL',report)
        self.assertIn('downstream conversion failed',report['error'])
        self.assertFalse(output.exists())

    def test_missing_negative_and_duplicate_pts_fail_in_producer(self):
        real_fit=run_video.fit_rgb
        for index,(call,value,message) in enumerate(((1,None,'Missing PTS'),(1,-1,'Nonmonotonic PTS'),(2,0,'Nonmonotonic PTS'))):
            calls=0
            def fit(frame,*args):
                nonlocal calls
                calls+=1
                result=real_fit(frame,*args)
                if calls==call:frame.pts=value
                return result
            with self.subTest(value=value),patch.object(run_video,'fit_rgb',fit):
                output,report=self.process('pts_'+str(index)+'.mkv',auto=False)
                self.assertEqual(report['status'],'FAIL',report)
                self.assertIn(message,report['error'])
                self.assertFalse(output.exists())


if __name__=='__main__':unittest.main()
