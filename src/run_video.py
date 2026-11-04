"""V4 physical FPGA file client; no CPU image-processing fallback.

PC decodes/packs, estimates bounded statistics, and encodes. All spatial/tone
pixels are returned by the identified V4 FPGA core. Optional CPU TNR is absent.
"""
from pathlib import Path
from fractions import Fraction
from datetime import datetime,timezone
from contextlib import nullcontext
import argparse,hashlib,json,os,queue,sys,threading,time,traceback,uuid
import av
import numpy as np
from signal_curves import apply_curves, plan_roi
from PIL import Image,ImageOps,ImageDraw

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'native'))
from protocol import Session,Frame,DEFAULTS,PIXEL_FORMAT,ENCODE_AHEAD,frames_ahead_limit
from identity import load_identity
from pixels import pack_rgb,unpack_rgb,FORMAT_BACKEND
from exposure_v4 import analyze_yuyv_v4,ExposureControllerV4,AUTO_POLICY
from auto_v5 import AutoOptimizerV5,AUTO_POLICY_V5,detail_profile
from image_controls import controls_snapshot,apply_controls,LiveImageControls
from transport_quality import encode_input as transport_input,describe as transport_description
from transport_adaptive import TextureAdaptiveShift
from media_frame import fit_rgb,export_frame,tag_bt709
from geometry import OUTPUT_PRESETS,DEFAULT_OUTPUT
from native_pixels_bridge import STATISTICS_AVAILABLE

def sha(data):return hashlib.sha256(data).hexdigest()

def sha_file(path,cancel=None):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        while data:=stream.read(1024*1024):
            if cancel is not None and cancel.is_set():raise InterruptedError('Cancelled')
            digest.update(data)
    return digest.hexdigest()

# GUI preview size: 1080p comes back every 2nd row/pair (was 640x360, every 3rd), and the
# detail view shows a 960x540 crop 1:1. Preview only; exports and board pixels are untouched.
PREVIEW_LIMIT=(960,540)

def _preview_step(w,h):
    """Integer decimation that fits the GUI preview; keeps YUYV pairs whole."""
    return max(1,-(-w//PREVIEW_LIMIT[0]),-(-h//PREVIEW_LIMIT[1]))

def preview_rgb(payload,w,h,step):
    """RGB preview of a YUYV frame from every step-th row and pair only.

    Each kept pair still converts with its own chroma, so colours match the full
    conversion at those pixels; only the sampling grid is coarser.
    """
    if step==1:return unpack_rgb(payload,w,h)
    pairs=np.frombuffer(payload,np.uint8).reshape(h,w//2,4)[::step,::step]
    small=np.ascontiguousarray(pairs)
    return unpack_rgb(small.tobytes(),small.shape[1]*2,small.shape[0])

def preview_window(w,h,focus=None):
    """Crop (x, y, width, height) shown 1:1 in detail preview; x on a YUYV pair.

    focus: (fx, fy) in 0..1, the frame point the crop is centred on (clamped so
    the crop stays inside the frame); None is the frame centre.
    """
    pw,ph=min(PREVIEW_LIMIT[0],w),min(PREVIEW_LIMIT[1],h)
    fx,fy=focus if focus is not None else (.5,.5)
    x=min(max(round(fx*w-pw/2),0),w-pw);y=min(max(round(fy*h-ph/2),0),h-ph)
    return x&~1,y,pw-(pw&1),ph

def crop_rgb(payload,w,h,window):
    """RGB of one rectangle of a YUYV frame, converting only those rows/pairs."""
    x,y,pw,ph=window
    rows=np.frombuffer(payload,np.uint8).reshape(h,w*2)[y:y+ph,2*x:2*(x+pw)]
    return unpack_rgb(np.ascontiguousarray(rows).tobytes(),pw,ph)

class _Exporter:
    """Bounded RGB conversion, optional upscale, H.264 encode and mux off the result loop.

    In the loop they cost ~10 ms per 1080p frame during which the Session's
    receiver was not reading the board's results. Frames stay in PTS order: one
    worker, FIFO queue. A worker error is raised by the next put/finish.
    """
    DEPTH=8
    def __init__(self,encoded,out,lock,processing,size,time_base,detailed,cancel,threaded=True):
        self.encoded,self.out,self.lock=encoded,out,lock
        self.processing,self.size,self.time_base,self.detailed,self.cancel=processing,size,time_base,detailed,cancel
        self.queue=queue.Queue(maxsize=self.DEPTH);self.error=None;self.threaded=threaded
        # threaded=False encodes inside put(): the earlier in-loop behaviour, kept for A/B.
        self.thread=threading.Thread(target=self._run,name='video-encode-mux',daemon=False) if threaded else None
        if self.thread:self.thread.start()
    def _encode(self,frame,pts):
        start=time.perf_counter()
        rgb=frame if isinstance(frame,np.ndarray) else unpack_rgb(frame,*self.processing)
        # A resize uses the same libswscale Lanczos as the input path, after the FPGA instead of before.
        vf=export_frame(rgb,self.size)
        vf.pts=pts;vf.time_base=self.time_base
        for packet in self.encoded.encode(vf):
            with self.lock:self.out.mux(packet)
        self.detailed['video_encode_mux']+=time.perf_counter()-start
    def _run(self):
        try:
            while True:
                item=self.queue.get()
                if item is None:return
                self._encode(*item)
        except BaseException as exc:
            self.error=exc
    def _put(self,item):
        if not self.threaded:
            if item is not None:self._encode(*item)
            return
        while True:
            if self.error is not None:raise self.error
            if item is not None and self.cancel.is_set():raise InterruptedError('Cancelled')
            try:self.queue.put(item,timeout=.05);return
            except queue.Full:
                if not self.thread.is_alive() and self.error is None:raise RuntimeError('export worker stopped')
    def put(self,frame,pts):self._put((frame,pts))
    def finish(self):
        self._put(None)
        if self.thread:self.thread.join()
        if self.error is not None:raise self.error
    def abort(self):
        if not self.thread:return
        while True:
            try:self.queue.get_nowait()
            except queue.Empty:break
        try:self.queue.put_nowait(None)
        except queue.Full:pass
        self.thread.join(10)

class _FramePreparation:
    """Bounded decode/pack producer; the sender consumes frames in order."""
    def __init__(self,prepare,cancel):
        self.prepare,self.cancel=prepare,cancel
        self.pending=queue.Queue(maxsize=3)
        self.stop=threading.Event()
        self.end=object()
        self.error=None
        self.thread=threading.Thread(target=self._run,name='video-decode-pack',daemon=False)

    def _put(self,item):
        while not self.stop.is_set() and not self.cancel.is_set():
            try:
                self.pending.put(item,timeout=.05)
                return True
            except queue.Full:pass
        return False

    def _run(self):
        try:
            for frame in self.prepare():
                if not self._put(frame):break
        except BaseException as exc:
            self.error=exc
        finally:
            self._put(self.end)

    def __iter__(self):
        while not self.stop.is_set():
            if self.cancel.is_set():raise InterruptedError('Cancelled')
            try:item=self.pending.get(timeout=.05)
            except queue.Empty:continue
            if item is self.end:
                if self.error is not None:raise self.error
                return
            yield item

    def close(self):
        self.stop.set()
        # Only this thread accesses the input container. Join before its with
        # block closes it, including failed exports and interrupted sessions.
        self.thread.join()

def processing_geometry(source_width,source_height,width,height,native=True):
    """FPGA processing size for an output preset.

    A source with no more pixels than 720p is processed at 1280x720 and the
    result is scaled to 1080p afterwards: upscaled pixels carry no detail, the
    FPGA's 3x3 sharpening then acts at the source's own scale, and the 2.25x
    smaller frames afford lossless transport (no near-lossless patches).
    """
    if native and (width,height)==(1920,1080) and (1280,720) in OUTPUT_PRESETS and source_width<=1280 and source_height<=720:
        return 1280,720
    return width,height


def resolve_transport(requested,geometry,wire_codec='rice03'):
    """'auto' is 'adaptive': lossless frames, shift 1 only on all-texture frames over budget.

    Board-modelled 1080p crops showed flat-area patches from BOTH hops at any
    near shift, so every frame with flat areas stays lossless; complex all-
    texture frames (rain forest: 2.9 MB/frame lossless, 15.6 fps) mask a +/-1
    error and are where the network budget runs out (transport_adaptive.py).
    """
    if requested!='auto':return requested
    return 'lossless' if wire_codec=='raw' else 'adaptive'


def process(source,output,*,mode=5,auto=True,max_inflight=6,host='192.168.2.99',port=5010,
            cancel=None,notify=lambda kind,data:None,save_output=True,preview_fps=50,wire_codec='rice03',transport_quality='lossless',realtime_preview=False,save_frames=False,trace_frames=True,auto_analysis_interval=1,width=DEFAULT_OUTPUT[0],height=DEFAULT_OUTPUT[1],auto_policy='v5',native_processing=False,preview_detail=False,host_pipeline=True,preview_focus=None,image_controls=None,return_lossless=None,parameter_curves=None,curve_region=None):
    source,output=Path(source).resolve(),Path(output).resolve()
    auto=bool(auto and mode==5)
    initial_controls=controls_snapshot(image_controls).to_dict()
    if return_lossless is not None and type(return_lossless) is not bool:raise ValueError('return_lossless override must be bool or None')
    if (width,height) not in OUTPUT_PRESETS:raise ValueError('Output resolution must be 1920x1080 or 1280x720')
    requested_transport=transport_quality
    if requested_transport!='auto':transport_description(requested_transport)
    if auto_policy not in ('v4','v5'):raise ValueError('auto_policy must be v4 or v5')
    if isinstance(auto_analysis_interval,bool) or not isinstance(auto_analysis_interval,int) or auto_analysis_interval<1:
        raise ValueError('auto_analysis_interval must be a positive integer')
    if source==output or any(p.exists() for p in (output,Path(str(output)+'.json'),Path(str(output)+'.frames.jsonl'))):
        raise ValueError('Select a new output file; source/output cannot be overwritten')
    if output.suffix.lower() not in ('.mp4','.mkv'):raise ValueError('MP4/MKV output required')
    output.parent.mkdir(parents=True,exist_ok=True)
    cancel=cancel or threading.Event()
    if not 0 <= preview_fps <= 60:raise ValueError('preview_fps 0..60 required')
    identity=load_identity(ROOT)
    token=uuid.uuid4().hex[:10]
    temp=output.with_name('.'+output.stem+'.'+token+'.part'+output.suffix)
    trace=Path(str(output)+'.frames.jsonl')
    report=dict(schema=1,backend='FPGA_MMIO',algorithm='enhance-v4-split-y-uv',
        pixel_format=PIXEL_FORMAT,temporal_filter='DISABLED_NOT_IN_FPGA',
        frame_hash_domains=dict(input='PRE_TRANSPORT_CODEC_YUYV422',output='POST_RETURN_CODEC_YUYV422'),
        auto_statistics_execution='PC',pixel_algorithm_execution='FPGA',
        auto_statistics_backend='NATIVE_HISTOGRAM_NUMPY_NOISE' if STATISTICS_AVAILABLE else 'NUMPY',
        media_resize_backend='LIBSWSCALE_LANCZOS_RGB_LETTERBOX',
        auto_params=auto,auto_policy=(AUTO_POLICY_V5 if auto_policy=='v5' else AUTO_POLICY) if auto else None,auto_analysis_interval=auto_analysis_interval,
        algorithm_sources_sha256={name:sha_file(ROOT/name,cancel) for name in
            ('auto_v5.py','exposure_v4.py','image_controls.py','run_video.py')},
        image_controls_initial=initial_controls,image_control_changes=[],
        input=str(source),input_sha256=sha_file(source,cancel) if trace_frames else None,output=str(output),
        output_video_requested=bool(save_output),format_conversion_backend=FORMAT_BACKEND,
        measurement_scope='DECODE_NETWORK_FPGA_PREVIEW_AND_EXPORT' if save_output else 'DECODE_NETWORK_FPGA_PREVIEW_NO_ENCODER',
        mode=mode,transport_quality=None,transport_request=requested_transport,max_inflight=max_inflight,frames=0,status='RUNNING',
        started_utc=datetime.now(timezone.utc).isoformat(),frame_trace=str(trace) if trace_frames else None,
        trace_frames=bool(trace_frames),
        stage_seconds=dict(decode_pack=0.,auto_analysis=0.,encode=0.),
        detailed_stage_seconds={k:0. for k in ('decode','rgb_conversion','resize','pack',
            'auto_analysis','unpack','video_encode_mux','audio_mux','input_hash','output_trace','selected_evidence','preview_callback')},
        preview_notifications=0,first_result_seconds=None,selected_frame_recording=bool(save_frames),
        playback_pacing='SOURCE_PTS' if realtime_preview else 'MAX_THROUGHPUT',playback_wait_seconds=0.,
        dma_seconds=0.,missing_pts=0,selected_frames=[],identity=identity)
    begin=time.perf_counter();session=None;results=None;preparation=None;watcher=None;watcher_stop=threading.Event()
    detailed=report['detailed_stage_seconds']
    try:
        sink=av.open(str(temp),'w',options={'movflags':'+faststart'} if output.suffix=='.mp4' else {}) if save_output else nullcontext(None)
        trace_context=trace.open('x',encoding='utf-8') if trace_frames else nullcontext(None)
        with av.open(str(source)) as inp, sink as out, trace_context as log:
            vs=inp.streams.video[0]
            # w,h: FPGA processing size; width,height: exported/previewed output size.
            w,h=processing_geometry(vs.width,vs.height,width,height,native_processing)
            transport_quality=resolve_transport(requested_transport,(w,h),wire_codec)
            if return_lossless is not None and transport_quality!='adaptive':raise ValueError('return precision override requires adaptive transport')
            split_return=(return_lossless is not False) and transport_quality=='adaptive' and wire_codec=='rice03'
            report.update(transport_quality=transport_description(transport_quality),output_geometry=[width,height],
                          native_processing=(w,h)!=(width,height))
            if transport_quality=='adaptive':
                report['transport_quality'].update(return_lossless=split_return,
                    max_error_return_codec_hop=0 if split_return else report['transport_quality']['max_error_input_codec_hop'])
            report['return_precision_override']=return_lossless
            tb=vs.time_base or Fraction(1,90000)
            rate=vs.average_rate or vs.guessed_rate or Fraction(25)
            origin=vs.start_time or 0
            encoded=None
            if out is not None:
                encoded=out.add_stream('libx264',rate=rate)
                encoded.width,encoded.height=width,height
                encoded.pix_fmt='yuv420p';encoded.time_base=tb;encoded.codec_context.time_base=tb;tag_bt709(encoded)
                # crf 10 (was 14, before that 18): on exact mist FPGA frames the crf-14 export put
                # 8-px block edges back into flat fog (grid step ratio 1.68 -> 2.53) that viewers saw
                # as colour blocks; crf 10 gives 2.03 and +0.5 dB at ~28 Mbit/s, 68 fps encode
                # (evidence/mist_blocks_20261101/export_ab_mist). Slower presets gained less.
                encoded.options={'crf':'10','preset':'veryfast','bf':'0'}
            ai=inp.streams.audio[0] if inp.streams.audio and out is not None else None
            ao=out.add_stream_from_template(ai) if ai is not None else None
            step=_preview_step(w,h)
            # Detail preview: both sides show the same crop at processing
            # resolution, 1:1; decimated full frames hide pixel-scale enhancement.
            # preview_focus (a 2-item list the GUI updates on a click) moves the
            # crop while the video runs. Each frame keeps the window its source
            # thumbnail used, so its result is cropped at the same place even when
            # the focus moves while it is on the board.
            def window_now():
                if not preview_detail:return None
                return preview_window(w,h,tuple(preview_focus) if preview_focus is not None else None)
            def view(a,win):
                return a[win[1]:win[1]+win[3],win[0]:win[0]+win[2]] if win else a[::step,::step]
            window=window_now()
            report['parameter_curves']=dict(controls=sorted(parameter_curves or {}),region=list(curve_region) if curve_region else None)
            report.update(host_pipeline=bool(host_pipeline),processing_geometry=[w,h],source_geometry=[vs.width,vs.height],preview_decimation=step,source_rate=str(rate),time_base=str(tb),audio='passthrough' if ai else 'none' if save_output else 'not_exported_preview_only')
            # One entry per frame the Session has pulled but not yet yielded.
            # host_pipeline=False reproduces the earlier host path for A/B: no
            # encode-ahead, serial return decode, export inside the result loop.
            encode_ahead=ENCODE_AHEAD if host_pipeline else 0
            lock=threading.Lock();prepared=queue.Queue(maxsize=frames_ahead_limit(max_inflight,encode_ahead))
            controller=AutoOptimizerV5() if auto_policy=='v5' else ExposureControllerV4()
            last_auto=None
            frame_shift=TextureAdaptiveShift(w,h) if transport_quality=='adaptive' else None
            # Auto (adaptive): near-lossless only upstream (the bytes the board's ARM
            # receive path pays most for); every frame comes back lossless, which removed
            # the rain highlight dots of the near-lossless return hop (test plan, item 1).
            session=Session(host,port,w,h,timeout=15,expected_identity=identity,max_inflight=max_inflight,wire_codec=wire_codec,
                            near_shift=transport_description(transport_quality)['near_shift'],encode_ahead=encode_ahead,frame_shift=frame_shift,
                            return_lossless=split_return)
            report['capabilities']=session.caps
            def watch_cancel():
                while not watcher_stop.wait(.05):
                    if cancel.is_set():
                        # Interrupt a blocking receive without racing any MMIO
                        # or freeing DMA memory. The board handles disconnect.
                        try:session.sock.shutdown(2)
                        except OSError:pass
                        return
            watcher=threading.Thread(target=watch_cancel,name='video-cancel',daemon=False);watcher.start()
            def decoded_frames():
                last=None;index=0;timebase_scales={}
                for packet in inp.demux([vs]+([ai] if ai else [])):
                    if cancel.is_set():raise InterruptedError('Cancelled')
                    if ai is not None and packet.stream.index==ai.index:
                        if packet.size and packet.dts is not None:
                            start=time.perf_counter()
                            shift=round(Fraction(origin)*tb/packet.time_base)
                            if packet.pts is not None:packet.pts-=shift
                            packet.dts-=shift;packet.stream=ao
                            with lock:out.mux(packet)
                            detailed['audio_mux']+=time.perf_counter()-start
                        continue
                    start=time.perf_counter();frames=packet.decode()
                    elapsed=time.perf_counter()-start
                    report['stage_seconds']['decode_pack']+=elapsed;detailed['decode']+=elapsed
                    for frame in frames:
                        if cancel.is_set():raise InterruptedError('Cancelled')
                        start=time.perf_counter();rgb,rect=fit_rgb(frame,w,h)
                        detailed['resize' if rect is not None else 'rgb_conversion']+=time.perf_counter()-start
                        p=dict(DEFAULTS);p['mode']=mode
                        if rect is not None:
                            p.update(roi_enable=1,**dict(zip(('roi_x','roi_y','roi_width','roi_height'),rect)))
                        pack_start=time.perf_counter()
                        payload=transport_input(pack_rgb(rgb),w,h,transport_quality)
                        detailed['pack']+=time.perf_counter()-pack_start
                        if frame.pts is None:raise ValueError('Missing PTS; refusing to invent frame timing')
                        frame_time_base=frame.time_base or tb
                        scale=timebase_scales.get(frame_time_base)
                        if scale is None:
                            scale=frame_time_base/tb;timebase_scales[frame_time_base]=scale
                        pts=round(frame.pts*scale)-origin
                        if pts<0 or (last is not None and pts<=last):raise ValueError('Nonmonotonic PTS')
                        report['stage_seconds']['decode_pack']+=time.perf_counter()-start
                        yield index,pts,p,rect,payload,rgb
                        last=pts;index+=1
            preparation=_FramePreparation(lambda:analysed(decoded_frames()),cancel)
            def analysed(frames):
                # Auto analysis, input hash and thumbnail run here, in the ordered
                # decode/pack producer thread, so they overlap the Session's encoder
                # instead of adding 20-25 ms per analysed 1080p frame to it.
                nonlocal last_auto
                for index,pts,p,rect,payload,rgb in frames:
                    decision=None
                    if auto and mode==5:
                        if last_auto is None or index%auto_analysis_interval==0:
                            start=time.perf_counter()
                            stats,noise=analyze_yuyv_v4(payload,w,h,rect)
                            if auto_policy=='v5':
                                # Content height over source height: >1 means the frame was upscaled.
                                upscale=round(256*(rect[3] if rect else h)/max(1,vs.height))
                                values,decision=controller.update(round(pts*tb*1000),stats,noise,
                                    detail_profile(payload,w,h,rect,noise.get('sigma_q8')),upscale)
                            else:
                                values,decision=controller.update(round(pts*tb*1000),stats,noise)
                            elapsed=time.perf_counter()-start
                            report['stage_seconds']['auto_analysis']+=elapsed;detailed['auto_analysis']+=elapsed
                            last_auto=(values,decision)
                        else:
                            values,decision=last_auto
                            # v5 moves its smoothed tone curve every frame between analyses.
                            if hasattr(controller,'advance'):values=controller.advance(round(pts*tb*1000))
                        p.update(values)
                    hash_start=time.perf_counter()
                    # Full-size RGB is kept only for diagnostic PNGs; the preview needs a thumbnail.
                    frame_window=window_now()
                    thumb=(rgb if save_frames else np.ascontiguousarray(view(rgb,frame_window)),frame_window)
                    input_sha=sha(payload) if trace_frames else None
                    detailed['input_hash']+=time.perf_counter()-hash_start
                    yield index,pts,p,decision,input_sha,thumb,payload
            def requests():
                for index,pts,p,decision,input_sha,thumb,payload in preparation:
                    if cancel.is_set():raise InterruptedError('Cancelled')
                    # Live settings (GUI knobs) are applied here, when the Session takes the
                    # frame, not in the producer three queued frames earlier: they only change
                    # the FPGA parameter words, never the pixels (test plan item 3: a knob took
                    # ~400 ms to show at the default window, 9 frames still had old settings).
                    # The revision lets the result loop report when a change reached the
                    # first returned and displayed frame.
                    if isinstance(image_controls,LiveImageControls):
                        controls,revision,changed_at=image_controls.revision_snapshot()
                    else:
                        controls,revision,changed_at=controls_snapshot(image_controls),0,None
                    p=apply_controls(p,controls,automatic=auto)
                    # Parameter-curve editor: per-frame overrides of the words, then the chosen
                    # region alone through the FPGA ROI (inside the letterbox, if any).
                    if parameter_curves:p=apply_curves(p,index,parameter_curves)
                    if curve_region is not None:
                        letterbox=(p['roi_x'],p['roi_y'],p['roi_width'],p['roi_height']) if p.get('roi_enable') else None
                        p=dict(p,**plan_roi(curve_region,(width,height),(w,h),letterbox))
                    control_data=controls.to_dict()
                    control_meta=(revision,changed_at,time.perf_counter())
                    prepared.put_nowait((index,pts,p,decision,input_sha,thumb,control_data,control_meta))
                    yield Frame(index,pts,payload,p,tb.numerator,tb.denominator)
            preparation.thread.start()
            exporter=None
            try:
                if encoded is not None:
                    exporter=_Exporter(encoded,out,lock,(w,h),(width,height),tb,detailed,cancel,threaded=host_pipeline)
                results=session.exchange(requests());next_notify=0.;playback_start=None;playback_pts=None
                stale_after_change={};awaiting_display=[]   # knob latency bookkeeping (see control_meta)
                for result in results:
                    if cancel.is_set():raise InterruptedError('Cancelled')
                    index,pts,p,decision,input_sha,(rgb,window),control_data,control_meta=prepared.get_nowait()
                    if (index,pts)!=(result.frame_id,result.pts):raise RuntimeError('Mismatched frame/PTS')
                    # Record only returned frames, never unprocessed read-ahead.
                    changes=report['image_control_changes']
                    revision,changed_at,frozen_at=control_meta;returned_at=time.perf_counter()
                    if isinstance(image_controls,LiveImageControls):
                        _,live_revision,live_changed=image_controls.revision_snapshot()
                        # A frame frozen before the newest change, returned after it: it still
                        # shows the old settings (read-ahead the change could not reach).
                        if revision<live_revision and live_changed is not None and frozen_at<live_changed:
                            stale_after_change[live_revision]=stale_after_change.get(live_revision,0)+1
                    if not changes or changes[-1]['settings']!=control_data:
                        entry=dict(frame_id=index,settings=control_data,revision=revision)
                        if changed_at is not None and revision:
                            entry.update(frozen_ms=round((frozen_at-changed_at)*1000,1),returned_ms=round((returned_at-changed_at)*1000,1),
                                         stale_frames_after_change=sum(n for r,n in stale_after_change.items() if r<=revision),displayed_ms=None)
                            for r in [r for r in stale_after_change if r<=revision]:del stale_after_change[r]
                            awaiting_display.append((revision,changed_at,entry))
                        changes.append(entry)
                    if realtime_preview:
                        now=time.perf_counter()
                        if playback_start is None:playback_start=now;playback_pts=pts
                        delay=playback_start+float((pts-playback_pts)*tb)-now
                        if delay>0:
                            start=time.perf_counter()
                            if cancel.wait(delay):raise InterruptedError('Cancelled')
                            report['playback_wait_seconds']+=time.perf_counter()-start
                    # Convert the FPGA result to full RGB only for export or diagnostics;
                    # a preview-only run converts just the preview grid (CPU and power).
                    preview_due=bool(preview_fps) and ((realtime_preview and float(rate)<=preview_fps) or time.perf_counter()>=next_notify)
                    start=time.perf_counter()
                    # Full RGB in this loop only for diagnostic PNGs; the exporter
                    # converts its own copy off the result path.
                    enhanced=unpack_rgb(result.payload,w,h) if save_frames else None
                    preview_result=None
                    if preview_due:
                        preview_result=(view(enhanced,window) if enhanced is not None else
                                        crop_rgb(result.payload,w,h,window) if window else preview_rgb(result.payload,w,h,step))
                    detailed['unpack']+=time.perf_counter()-start
                    if exporter is not None:
                        exporter.put(enhanced if enhanced is not None else result.payload,pts)
                    report['stage_seconds']['encode']+=time.perf_counter()-start
                    report['dma_seconds']+=result.dma_ns/1e9
                    hash_start=time.perf_counter()
                    if log is not None:
                        log.write(json.dumps(dict(frame_id=index,pts=pts,time_base=str(tb),parameters=p,
                            image_controls=control_data,
                            auto_decision=decision,input_sha256=input_sha,output_sha256=sha(result.payload),
                            hardware_counters=dict(frame_count=result.completed_frames,stream_errors=result.stream_errors),
                            dma_ns=result.dma_ns,mm2s_status=result.mm2s_status,s2mm_status=result.s2mm_status,
                            transport_shift=result.transport_shift,upload_shift=result.upload_shift))+'\n')
                    detailed['output_trace']+=time.perf_counter()-hash_start
                    report['frames']+=1
                    if report['first_result_seconds'] is None:report['first_result_seconds']=time.perf_counter()-begin
                    if save_frames and index in (0,50,336,500):
                        evidence_start=time.perf_counter()
                        folder=output.parent/(output.stem+'_frames');folder.mkdir(exist_ok=True)
                        Image.fromarray(rgb).save(folder/f'{index:04}_source.png')
                        Image.fromarray(enhanced).save(folder/f'{index:04}_fpga.png')
                        (folder/f'{index:04}_fpga.yuyv').write_bytes(result.payload)
                        pair=Image.new('RGB',(w*2,h+32));pair.paste(Image.fromarray(rgb),(0,32));pair.paste(Image.fromarray(enhanced),(w,32))
                        draw=ImageDraw.Draw(pair);draw.text((10,8),'SOURCE',fill='white');draw.text((w+10,8),'V4 ACTUAL FPGA',fill='white')
                        pair.save(folder/f'{index:04}_comparison.png');report['selected_frames'].append(index)
                        detailed['selected_evidence']+=time.perf_counter()-evidence_start
                    # A PTS-paced 30/50 Hz source already obeys the preview cap.
                    # A second relative timer would discard alternating frames
                    # whenever scheduling jitter places one just before its tick.
                    if preview_due:
                        preview_start=time.perf_counter()
                        shown_at=time.perf_counter()
                        while awaiting_display and awaiting_display[0][0]<=revision:
                            _,changed,entry=awaiting_display.pop(0);entry['displayed_ms']=round((shown_at-changed)*1000,1)
                        notify('progress',dict(frames=report['frames'],elapsed=time.perf_counter()-begin,source=rgb if not save_frames else view(rgb,window),result=preview_result,preview_detail=bool(window),preview_window=window,settings_revision=revision,
                            image_controls=control_data,parameters=dict(p),
                            source_fps=float(rate),source_size=(vs.width,vs.height),output_size=(width,height),processing_size=(w,h),transport_quality=transport_quality))
                        detailed['preview_callback']+=time.perf_counter()-preview_start
                        report['preview_notifications']+=1;next_notify=time.perf_counter()+1/preview_fps
                report['session_summary']=session.summary
                report['transport_metrics']=session.transport_metrics
                if frame_shift is not None:
                    report['adaptive_transport_guard']=dict(gamut_guard_frames=frame_shift.gamut_guard_frames,risk_checks=frame_shift.risk_checks,
                        return_ratio=round(frame_shift.return_ratio,4),returns_observed=frame_shift.returns_observed,
                        last_decision=frame_shift.last, scope='BOUNDED_COLOR_HEADROOM_HEURISTIC')
                if report['frames']==0:raise ValueError('No decoded frames')
                if exporter is not None:
                    exporter.finish();exporter=None
                    for packet in encoded.encode(None):out.mux(packet)
            finally:
                if exporter is not None:exporter.abort()
                preparation.stop.set()
                watcher_stop.set()
                watcher.join()
                for owner in (results,session):
                    if owner is not None:
                        try:owner.close()
                        except BaseException as exc:report.setdefault('cleanup_errors',[]).append(str(exc))
                results=session=None
                preparation.close()
        if save_output:os.rename(temp,output)
        report.update(status='PASS',output_video_written=bool(save_output),output_sha256=sha_file(output) if save_output and trace_frames else None,trace_written=bool(trace_frames))
    except BaseException as exc:
        if preparation is not None and preparation.error is not None and isinstance(exc,OSError):
            exc=preparation.error
        # Some exceptions (queue.Full/Empty, bare AssertionError) have no message;
        # always name the type and keep the traceback so a FAIL is diagnosable.
        report.update(status='CANCELLED' if cancel.is_set() or isinstance(exc,(InterruptedError,KeyboardInterrupt)) else 'FAIL',
                      error=str(exc) or type(exc).__name__,error_traceback=traceback.format_exception(exc)[-6:])
    finally:
        watcher_stop.set()
        if watcher is not None:watcher.join(2)
        for owner in (results,session):
            if owner is not None:
                try:owner.close()
                except BaseException as exc:
                    report.setdefault('cleanup_errors',[]).append(str(exc));report['status']='FAIL'
        if report.get('cleanup_errors'):report['status']='FAIL'
        temp.unlink(missing_ok=True)
        report.update(elapsed_seconds=time.perf_counter()-begin,finished_utc=datetime.now(timezone.utc).isoformat())
        report['processing_fps']=report['frames']/max(report['elapsed_seconds'],1e-9)
        Path(str(output)+'.json').write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
        notify('done',report)
    return report

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',type=int,choices=range(6),default=5)
    p.add_argument('--fixed',action='store_true',help='Use uniform fixed parameters instead of automatic statistics')
    p.add_argument('--auto-policy',choices=('v5','v4'),default='v5',help='v5: one-click full auto (scene-adaptive sharpening/contrast); v4: exposure and denoise only')
    scheduling=p.add_mutually_exclusive_group()
    scheduling.add_argument('--serial',action='store_true',help='Force one frame in flight')
    scheduling.add_argument('--pipeline',action='store_true',help='Allow up to three compressed frames; raw fallback serializes')
    p.add_argument('--wire-codec',choices=('rice03','raw','lz4'),default='rice03',help='Lossless Rice03 to FPGA, hardware Rice02 return; enhancement always runs in FPGA')
    p.add_argument('--transport-quality',choices=('auto','lossless','adaptive','fine','preview','fast'),default='auto',help='Near transport: auto (default, as in the GUI) = adaptive: lossless except all-texture frames over the network budget, which use <=1; lossless is exact on every frame; fine <=1 sample level per hop; preview <=2; fast <=4 (flat areas can show patches). Every frame is processed by FPGA.')
    p.add_argument('--resolution',choices=('1080p','720p'),default='1080p',help='Output resolution; sources are Lanczos-letterboxed to it')
    p.add_argument('--native-720p',action='store_true',help='Optional: process sources up to 720p on the FPGA at native 1280x720 (lossless, faster), then upscale; default processes at the output size')
    p.add_argument('--host',default='192.168.2.99');p.add_argument('--port',type=int,default=5010)
    p.add_argument('--preview-only',action='store_true',help='Process and record frame evidence without encoding an output video')
    p.add_argument('--realtime',action='store_true',help='Pace preview by source PTS; throughput tests leave this disabled. Never skips FPGA frames.')
    p.add_argument('--save-frames',action='store_true',help='Write diagnostic PNG/raw frames in the processing loop; disabled for production preview')
    p.add_argument('--managed',action='store_true',help='Start a matched temporary board service and stop it after processing')
    args=p.parse_args()
    def progress(kind,data):
        if kind=='progress':print(json.dumps(dict(event=kind,frames=data['frames'],elapsed=data['elapsed'])),flush=True)
    runner=process
    options={}
    if args.managed:
        from board_link import process_managed
        runner=process_managed
        options['password']=os.environ.get('PYNQ_JUPYTER_PASSWORD','xilinx')
        options['poll_us']=20
    window=1 if args.serial or (args.wire_codec=='raw' and not args.pipeline) else 6
    r=runner(args.input,args.output,mode=args.mode,auto=not args.fixed,max_inflight=window,host=args.host,port=args.port,notify=progress,save_output=not args.preview_only,wire_codec=args.wire_codec,transport_quality=args.transport_quality,native_processing=args.native_720p,realtime_preview=args.realtime,save_frames=args.save_frames,trace_frames=not args.realtime,auto_analysis_interval=4,
             width=1920 if args.resolution=='1080p' else 1280,height=1080 if args.resolution=='1080p' else 720,auto_policy=args.auto_policy,**options)
    print(json.dumps({k:r[k] for k in ('status','frames','elapsed_seconds','processing_fps')},ensure_ascii=False),flush=True)
    raise SystemExit(0 if r['status']=='PASS' else 1)

if __name__=='__main__':main()
