"""Start/stop only this app's temporary matched board service through Jupyter."""
from pathlib import Path
from urllib.parse import quote,urlsplit
import base64,hashlib,json,threading,time,uuid,sys
from jupyter_link import JupyterClient,JupyterError,execute_code,terminal_output,terminal_result
from identity import load_identity
from session_receipts import ReleaseJournal, write_json_atomic

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT/'native'))
from protocol import status

class TerminalUnavailable(RuntimeError):
    """The terminal path failed before any board code could run; the kernel path is safe instead."""

# Runs ahead of START_CODE/STOP_CODE when they go up as a file: take the runtime archive
# uploaded beside the script and remove both uploads before anything else happens.
TERMINAL_PRELUDE=r'''import sys as _sys
from pathlib import Path as _Path
_me=_Path(_sys.argv[0]).resolve();_zip=_me.with_suffix('.zip')
_blob=_zip.read_bytes() if _zip.is_file() else None
for _f in (_zip,_me):
    try:_f.unlink()
    except FileNotFoundError:pass
'''

class ManagedBoard:
    # Measurement switches only (A/B tests); the native service reads them at start.
    NATIVE_ENV_KEYS={'P6_PREDICTIVE_WAIT':('0','1'),'P6_PIN_THREADS':('0','1'),'P6_DECODER_BANDS':('3','4'),'P6_LEAN_PYNQ':('0','1')}
    # c.NotebookApp.notebook_dir of the PYNQ image: where the contents API writes uploads.
    NOTEBOOK_ROOT='/home/xilinx/jupyter_notebooks'

    def __init__(self,host='192.168.2.99',password='xilinx',jupyter_port=9090,port=5010,poll_us=100,large_socket_buffers=True,native_env=None,lease_seconds=120,channel='auto'):
        self.host,self.port=host,port
        # 'auto': Jupyter terminal, else the original kernel path; the others force one (A/B).
        if channel not in ('auto','terminal','kernel'):raise ValueError('channel must be auto, terminal or kernel')
        self.channel=channel;self.last_channel=None;self.terminal_fallback=None
        if poll_us not in (20,100,200,500):raise ValueError('Unsupported hardware poll interval')
        self.poll_us=poll_us
        # Board-side idle lease: lease_guard stops the service after this long without a session.
        if not 10<=lease_seconds<=600:raise ValueError('lease_seconds must be 10..600')
        self.lease_seconds=lease_seconds
        self.large_socket_buffers=bool(large_socket_buffers)
        self.native_env=dict(native_env or {})
        if any(v not in self.NATIVE_ENV_KEYS.get(k,()) for k,v in self.native_env.items()):
            raise ValueError('native_env accepts only '+', '.join(f'{k} in {v}' for k,v in self.NATIVE_ENV_KEYS.items()))
        self.client=JupyterClient(f'http://{host}:{jupyter_port}',10)
        self.password=password;self.specs=None;self.owned=None;self.attached=False
        self.pending_kernels=set()
        self.identity=load_identity(ROOT)

    def login(self):
        if self.specs is None:
            self.specs=self.client.login(self.password);self.password=None

    def run(self,code,timeout,payload=None):
        """Run START_CODE/STOP_CODE: through a Jupyter terminal when possible, else in a kernel with the payload inline."""
        if self.channel!='kernel':
            try:return self.run_terminal(code,timeout,payload)
            except TerminalUnavailable as exc:
                if self.channel=='terminal':raise
                self.terminal_fallback=str(exc)
        blob='None' if payload is None else 'base64.b64decode(%r,validate=True)'%base64.b64encode(payload).decode('ascii')
        result=self.execute(code.replace('__BLOB__',blob),timeout)
        self.last_channel='KERNEL'
        return result

    def run_terminal(self,code,timeout,payload=None):
        """Run code as a python3 script in a fresh Jupyter terminal.

        A kernel takes ~8 s to start and ~1.2 s to delete, and the 2.5 MB base64 runtime inside a
        cell costs another ~17 s of IPython cell handling on the board; a terminal opens in ~0.1 s
        and the files go up through the contents API in ~0.5 s (evidence/startup_fast_20261101).
        Raises TerminalUnavailable only while no board code can have run.
        """
        tag='p6r_'+uuid.uuid4().hex;nonce=uuid.uuid4().hex
        uploads=[tag+'.py']+([tag+'.zip'] if payload is not None else [])
        script=self.NOTEBOOK_ROOT+'/'+uploads[0];term=ws=None
        try:
            try:
                self.login()
                if payload is not None:
                    self.client.json_request('PUT','api/contents/'+uploads[1],data=dict(type='file',format='base64',
                        content=base64.b64encode(payload).decode('ascii')),expected=(200,201))
                self.client.json_request('PUT','api/contents/'+uploads[0],data=dict(type='file',format='text',
                    content=TERMINAL_PRELUDE+code.replace('__BLOB__','_blob')),expected=(200,201))
                term=self.client.json_request('POST','api/terminals',expected=(200,201)).get('name')
                if not isinstance(term,str) or not term:raise JupyterError('Jupyter created a terminal without a name')
                ws=self.client.connect_terminal(term,12)
            except Exception as exc:
                raise TerminalUnavailable(f'{type(exc).__name__}: {exc}') from None
            # -I: no script directory or user site on sys.path. The markers carry the nonce
            # only in the output, never in the echoed command line.
            ws.send(json.dumps(['stdin',f'M={nonce}; if test -f {script}; then python3 -I -u {script}; '
                                'echo P6R_EXIT_$M=$?; else echo P6R_MISSING_$M; fi; exit\r']))
            status,text=terminal_output(ws,nonce,timeout)
            if status is None:raise TerminalUnavailable('uploaded script not found under '+self.NOTEBOOK_ROOT)
            result=terminal_result(text,status)
            self.last_channel='TERMINAL'
            return result
        finally:
            if ws is not None:
                try:ws.close()
                except Exception:pass
            if term is not None:
                try:self.client.request('DELETE','api/terminals/'+quote(term),max_bytes=1024,expected=(200,204))
                except Exception:pass  # already gone after `exit`
            for name in uploads:
                try:self.client.request('DELETE','api/contents/'+name,max_bytes=1024,expected=(200,204))
                except Exception:pass  # the script removes its own uploads first

    def channel_record(self):
        return dict(board_channel=self.last_channel,**({'terminal_fallback':self.terminal_fallback} if self.terminal_fallback else {}))

    def execute(self,code,timeout=45):
        self.login()
        kid=None;ws=None
        try:
            kid=self.client.create_kernel(self.client.choose_kernel(self.specs,None))
            self.pending_kernels.add(kid)
            ws=self.client.connect_channels(kid,uuid.uuid4().hex,12)
            return execute_code(ws,code,timeout)
        finally:
            if ws is not None:ws.close()
            if kid is not None:
                try:
                    self.client.delete_kernel(kid)
                    self.pending_kernels.discard(kid)
                except Exception:
                    # Keep the exact owned ID for another cleanup attempt;
                    # do not replace a successful hardware reply with this.
                    pass

    def start(self):
        try:
            current=status(self.host,self.port,1)
        except (OSError,ConnectionError):current=None
        if current is not None:
            if current.get('identity')!=self.identity or current.get('backend')!='FPGA_MMIO' or current.get('state')!='IDLE':
                raise RuntimeError('开发板已有其他版本或忙碌的程序，请先结束那个程序。')
            self.attached=True
            return dict(status='ATTACHED_EXISTING_MATCHED_SERVICE',owned=False,capabilities=current)
        record=json.loads((ROOT/'board_runtime.json').read_text(encoding='utf-8'))
        data=(ROOT/'board_runtime.zip').read_bytes()
        digest=hashlib.sha256(data).hexdigest()
        if record['identity']!=self.identity or record['archive_sha256']!=digest:
            raise ValueError('电脑端板端包不匹配，请重新打包完整工程。')
        self.login()
        owner=uuid.uuid4().hex
        context=dict(owner=owner,identity=self.identity,archive_sha256=digest,host=self.host,port=self.port,poll_us=self.poll_us,large_socket_buffers=self.large_socket_buffers,native_env=self.native_env,idle_seconds=self.lease_seconds)
        code=START_CODE.replace('__CONTEXT__',repr(context))
        self.owned=context  # Keep recovery identity even if the response is lost.
        result=self.run(code,55,payload=data)
        self.owned.update(result['runtime'])
        result.update(self.channel_record())
        return result

    def stop(self):
        if self.owned is None:
            return dict(status='EXISTING_SERVICE_NOT_STOPPED' if self.attached else 'NO_OWNED_SERVICE')
        result=self.run(STOP_CODE.replace('__CONTEXT__',repr(self.owned)),35)
        result.update(self.channel_record())
        self.owned=None
        for kid in tuple(self.pending_kernels):
            try:
                self.client.delete_kernel(kid)
                self.pending_kernels.discard(kid)
            except Exception:pass
        result['pending_owned_jupyter_kernels']=sorted(self.pending_kernels)
        return result

class BoardSession:
    """Keep one app-owned board service between videos while the window is open.

    Starting the service costs ~44 s and stopping it ~16 s, against 6-12 s of
    processing per clip (evidence/board_keepalive_20261101). The service's own
    idle lease (LEASE_SECONDS) still frees the board if the app dies; the app
    releases it itself after RELEASE_SECONDS idle, well before that lease can
    end it under a starting run, and when the window closes.
    """
    LEASE_SECONDS=600
    RELEASE_SECONDS=420

    def __init__(self,factory=ManagedBoard,probe=None):
        self.factory=factory;self.probe=probe or (lambda host,port:status(host,port,1))
        self.lock=threading.RLock();self.board=None;self.key=None
        self.idle_since=None;self.release_pending=False;self.last_release=None
        self.video_uses=0;self.receipts=ReleaseJournal()

    @property
    def active(self):return self.board is not None

    def idle_seconds(self):
        return None if self.idle_since is None else time.monotonic()-self.idle_since

    def _state(self,host,port,wait=8.):
        # A session that just ended may still be releasing its slots (OWNED).
        end=time.monotonic()+wait
        while True:
            try:state=self.probe(host,port)
            except (OSError,ConnectionError):return None
            if state.get('state')!='OWNED' or time.monotonic()>=end:return state
            time.sleep(.1)

    def acquire(self,host,password,port,poll_us,for_video=False):
        """Return (board, setup record): the kept service when it is still idle and matched, else a new one."""
        with self.lock:
            key=(host,port,poll_us)
            if self.board is not None and self.key!=key:self.release()
            if self.board is not None:
                state=self._state(host,port)
                if (state is not None and state.get('state')=='IDLE' and state.get('backend')=='FPGA_MMIO'
                        and state.get('identity')==self.board.identity):
                    self.idle_since=None
                    setup=dict(status='REUSED_KEPT_SERVICE',owned=self.board.owned is not None,capabilities=state)
                    return self.board,self._video_setup(setup,for_video)
                # Ended by its lease or a board restart, or faulted: stop whatever is ours, start afresh.
                self.release()
            board=self.factory(host,password,port=port,poll_us=poll_us,lease_seconds=self.LEASE_SECONDS)
            self.board,self.key,self.idle_since=board,key,None
            self.video_uses=0
            try:return board,self._video_setup(board.start(),for_video)
            except BaseException:
                # A lost reply may leave a started service: keep its identity for release.
                if board.owned is None and not board.attached:self.board=self.key=None
                else:self.release_pending=True
                raise

    def _video_setup(self,setup,for_video):
        setup=dict(setup)
        setup['service_owner']=(self.board.owned or {}).get('owner')
        if for_video:
            first=self.video_uses==0;self.video_uses+=1
            setup['video_index']=self.video_uses
            setup['service_origin']=('COLD_START' if setup['status']=='STARTED_TEMPORARY_MATCHED_FPGA_SERVICE' else
                'ATTACHED_EXISTING' if setup['status']=='ATTACHED_EXISTING_MATCHED_SERVICE' else
                'PREWARMED_FIRST_USE' if first else 'REUSED_PREVIOUS_VIDEO')
        return setup

    def warm(self,host,password,port,poll_us):
        """Start the service ahead of the first run; a still usable kept one keeps its idle clock."""
        with self.lock:
            since=self.idle_since
            _,setup=self.acquire(host,password,port,poll_us)
            if setup.get('status')=='REUSED_KEPT_SERVICE':
                self.idle_since=since if since is not None else time.monotonic()
            else:self.keep(host,port)
            return setup

    def keep(self,host,port):
        """After a finished or cancelled run: keep the service if it is idle again, else release it."""
        with self.lock:
            state=self._state(host,port) if self.board is not None else None
            if state is not None and state.get('state')=='IDLE':
                self.idle_since=time.monotonic()
                return dict(status='KEPT_FOR_NEXT_VIDEO',state='IDLE',owned=self.board.owned is not None,
                            release_after_idle_seconds=self.RELEASE_SECONDS,lease_seconds=self.LEASE_SECONDS)
            return self.release()

    def release(self):
        """Stop the kept service through the confirmed stop path; raise if the stop is not confirmed."""
        with self.lock:
            if self.board is None:
                if self.receipts.pending_count and self.last_release:
                    result=dict(self.last_release);result['release_receipts']=self.receipts.flush();self.last_release=result
                    return result
                return dict(status='NO_OWNED_SERVICE')
            owner=(self.board.owned or {}).get('owner');identity=self.board.identity
            try:result=self.board.stop()
            except BaseException as exc:
                self.release_pending=True
                self.last_release=dict(status='STOP_NOT_CONFIRMED',error=str(exc) or type(exc).__name__,
                                       idle_lease_seconds=self.LEASE_SECONDS)
                raise
            self.board=self.key=self.idle_since=None;self.release_pending=False
            result['release_receipts']=self.receipts.note_release(owner,identity,result)
            self.last_release=result
            return result

def process_managed(source,output,*,password='xilinx',host='192.168.2.99',port=5010,poll_us=100,
                    notify=lambda kind,data:None,session=None,**options):
    """Keep the GUI worker alive until its owned service has safely stopped.

    With a BoardSession a finished or cancelled run keeps the idle service for
    the next video instead; a failed run still stops it."""
    from run_video import process
    begin=time.perf_counter();result=None;cleanup=None;setup=None;pixels_done=None
    board=None if session is not None else ManagedBoard(host,password,port=port,poll_us=poll_us)
    setup_seconds=0.
    try:
        notify('connecting_board',{})
        board,setup=session.acquire(host,password,port,poll_us,for_video=True) if session is not None else (board,board.start())
        setup_seconds=time.perf_counter()-begin
        notify('board_acquired',dict(setup=setup,ready_seconds=setup_seconds))
        result=process(source,output,host=host,port=port,
            notify=lambda kind,data:notify(kind,data) if kind!='done' else None,**options)
        pixels_done=time.perf_counter()-begin
    finally:
        cleanup_start=time.perf_counter()
        keep=session is not None and result is not None and result.get('status') in ('PASS','CANCELLED')
        if not keep:notify('stopping_board',{})
        try:cleanup=session.keep(host,port) if keep else session.release() if session is not None else board.stop()
        except BaseException as exc:
            cleanup=dict(status='STOP_NOT_CONFIRMED',error=str(exc),
                         idle_lease_seconds=session.LEASE_SECONDS if session is not None else 120)
        if result is not None:
            # Interrupted exports retain their trace but do not pass through
            # run_video's successful-export flags. Preserve that distinction.
            trace=Path(str(Path(output).resolve())+'.frames.jsonl')
            result.setdefault('output_video_written',False)
            result.setdefault('trace_written',bool(result.get('trace_frames') and trace.is_file()))
            result['board_cleanup']=cleanup
            result['board_setup']=dict(status=(setup or {}).get('status'),seconds=setup_seconds)
            for key in ('service_origin','video_index','service_owner'):
                if key in (setup or {}):result['board_setup'][key]=setup[key]
            result['board_setup_seconds']=setup_seconds
            result['board_cleanup_seconds']=time.perf_counter()-cleanup_start
            # Seconds from the start request: board ready, last pixel back, board kept/stopped.
            result['lifecycle_seconds']=dict(board_ready=setup_seconds,pixels_done=pixels_done,
                                             board_kept_or_stopped=time.perf_counter()-begin)
            result['total_wall_seconds_including_board_lifecycle']=time.perf_counter()-begin
            result['fps_including_board_lifecycle']=result['frames']/max(time.perf_counter()-begin,1e-9)
            result['lifecycle_measurement_scope']='START_REQUEST_TO_THIS_VIDEO_BOARD_KEPT_OR_STOPPED; FINAL_WINDOW_RELEASE_IS_SEPARATE'
            if cleanup.get('status')=='STOP_NOT_CONFIRMED':
                result['status']='FAIL';result['error']='Board cleanup not confirmed: '+cleanup['error']
            if (session is not None and cleanup.get('status')=='KEPT_FOR_NEXT_VIDEO'
                    and (result.get('output_video_written') or result.get('trace_written'))):
                session.receipts.register(output,result,(setup or {}).get('service_owner'),board.identity)
            else:write_json_atomic(Path(str(Path(output).resolve())+'.json'),result)
            notify('done',result)
    return result

START_CODE=r'''
from pathlib import Path
from zipfile import ZipFile
import base64,hashlib,io,json,os,platform,stat,subprocess,sys,tempfile,time
c=__CONTEXT__;blob=__BLOB__
assert hashlib.sha256(blob).hexdigest()==c['archive_sha256']
assert platform.machine() in ('armv7l','armv8l'), 'This runtime targets PYNQ-Z2 ARM32'
# Inspect command arguments only. A running HDMI or file program must retain
# ownership of the FPGA until its user ends it; never reconfigure underneath it.
for proc in Path('/proc').iterdir():
    if not proc.name.isdigit() or int(proc.name)==os.getpid():continue
    try:argv=(proc/'cmdline').read_bytes().split(b'\0')
    except (FileNotFoundError,PermissionError):continue
    owned_scripts={'run_video_a.py','run_video_abc.py','file_process_server.py','board_bootstrap.py'}
    assert not any(Path(os.fsdecode(arg)).name in owned_scripts for arg in argv if arg), 'Another FPGA program is running'
root=Path(tempfile.gettempdir())/('pynq_v4_session_'+c['owner'])
assert not root.exists()
root.mkdir(mode=0o700);(root/'.owner').write_text(c['owner'])
with ZipFile(io.BytesIO(blob)) as z:
    assert len(z.namelist())==len(set(z.namelist()))
    assert sum(i.file_size for i in z.infolist())<32*1024*1024
    for item in z.infolist():
        assert not item.is_dir() and not item.filename.startswith('/') and '\\' not in item.filename
        assert (root/item.filename).resolve().is_relative_to(root)
        assert stat.S_IFMT(item.external_attr>>16)!=stat.S_IFLNK
    z.extractall(root)
sys.path.insert(0,str(root/'native'))
from board_bootstrap import verify_manifest,forbid_existing_owner
from protocol import status
_,identity=verify_manifest(root/'native_yuyv.experimental.json');assert identity==c['identity']
forbid_existing_owner()
build=json.loads((root/'output/file_process_rice03.build.json').read_text())
policy='--hp-packets' if build.get('memory_interface',{}).get('kind') in ('HP_DEVICE_FRAMES_EXPLICIT_CPU_SYNC','HYBRID_ACP_PACKETS_HP_FRAMES') else '--coherent-acp' if build.get('memory_interface',{}).get('kind')=='ACP_COHERENT' else '--cacheable'
# The verified bootstrap runs unchanged through runpy, after pynq 3.1.1's notebook-only
# imports (IPython.display, tqdm.notebook) get inert stand-ins that raise on any call:
# ~4.4 s less service start, identical parsed overlay (evidence/startup_fast_20261101).
# pkg_resources stays real (Overlay registers driver entry points). P6_LEAN_PYNQ=0: as before.
LEAN_LAUNCH="""
import importlib.abc,importlib.machinery,importlib.util,runpy,sys,types
from pathlib import Path
spec=importlib.util.find_spec('pynq')
if spec is not None and (Path(spec.origin).parents[1]/'pynq-3.1.1.dist-info').is_dir():
    class Inert(types.ModuleType):
        __path__=[]
        def __getattr__(self,name):
            if name.startswith('__'):raise AttributeError(name)
            return Inert(self.__name__+'.'+name)
        def __call__(self,*args,**kwargs):raise RuntimeError(self.__name__+' is not available in the headless board service')
    class Finder(importlib.abc.MetaPathFinder,importlib.abc.Loader):
        NAMES=('IPython','tqdm.notebook')
        def find_spec(self,name,path=None,target=None):
            if any(name==n or name.startswith(n+'.') for n in self.NAMES):return importlib.machinery.ModuleSpec(name,self,is_package=True)
        def create_module(self,spec):return Inert(spec.name)
        def exec_module(self,module):pass
    sys.meta_path.insert(0,Finder())
    print('{"event": "LEAN_PYNQ_IMPORT", "stand_ins": ["IPython", "tqdm.notebook"]}',flush=True)
sys.argv=sys.argv[1:];sys.path[0]=str(Path(sys.argv[0]).resolve().parent)
runpy.run_path(sys.argv[0],run_name='__main__')
"""
launch=['python3','-u']+(['-c',LEAN_LAUNCH] if c.get('native_env',{}).get('P6_LEAN_PYNQ')!='0' else [])
with (root/'service.log').open('w') as log:
    child=subprocess.Popen(launch+[str(root/'native/board_bootstrap.py'),'--manifest',
        str(root/'native_yuyv.experimental.json'),'--bind',c['host'],'--port',str(c['port']),policy,'--poll-us',str(c.get('poll_us',20))]+(['--large-socket-buffers'] if c.get('large_socket_buffers') else []),
        cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,
        env={**os.environ,**c.get('native_env',{})})
(root/'service.pid').write_text(str(child.pid))
with (root/'lease.log').open('w') as log:
    guard=subprocess.Popen(['python3','-u',str(root/'native/lease_guard.py'),'--root',str(root),
        '--owner',c['owner'],'--pid',str(child.pid),'--host',c['host'],'--port',str(c['port']),'--idle-seconds',str(c.get('idle_seconds',120))],
        cwd=root,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
(root/'guard.pid').write_text(str(guard.pid))
end=time.monotonic()+30
while time.monotonic()<end:
    if child.poll() is not None:raise RuntimeError((root/'service.log').read_text()[-4000:])
    try:
        state=status(c['host'],c['port'],1)
        assert state['identity']==identity and state['state']=='IDLE' and state['backend']=='FPGA_MMIO'
        break
    except (OSError,ConnectionError):time.sleep(.1)
else:raise RuntimeError('Board service start deadline; idle lease needs inspection')
time.sleep(.15)
assert guard.poll() is None,'Idle lease guard failed to start'
print('__REVIEW_RESULT__='+json.dumps(dict(status='STARTED_TEMPORARY_MATCHED_FPGA_SERVICE',owned=True,
    runtime=dict(root=str(root),pid=child.pid,guard_pid=guard.pid),capabilities=state)),flush=True)
'''

STOP_CODE=r'''
from pathlib import Path
import json,mmap,os,signal,socket,sys,tempfile,time,shutil
c=__CONTEXT__;root=Path(tempfile.gettempdir())/('pynq_v4_session_'+c['owner'])
if not root.exists():
    print('__REVIEW_RESULT__='+json.dumps(dict(status='OWNED_RUNTIME_ALREADY_REMOVED',temporary_files_removed=True)))
else:
    assert root.resolve()==root and root.parent==Path(tempfile.gettempdir()).resolve()
    assert (root/'.owner').read_text()==c['owner']
    pid=int((root/'service.pid').read_text())
    args=Path('/proc',str(pid),'cmdline')
    if args.exists():
        assert str(root/'native/board_bootstrap.py').encode() in args.read_bytes().split(b'\0')
        sys.path.insert(0,str(root/'native'))
        from protocol import status
        end=time.monotonic()+8
        while True:
            state=status(c['host'],c['port'],1)
            assert state['identity']==c['identity']
            if state['state'] in ('IDLE','FAULT_LATCHED'):break
            assert state['state']=='OWNED','Unsafe DMA: keep buffers and request inspection'
            if time.monotonic()>=end:raise TimeoutError('Hardware owner still active; do not force free')
            time.sleep(.1)
        os.kill(pid,signal.SIGTERM)
    end=time.monotonic()+12
    while Path('/proc',str(pid)).exists() and time.monotonic()<end:time.sleep(.1)
    assert not Path('/proc',str(pid)).exists(),'Cooperative stop did not finish; do not force kill'
    def read_words(base,offsets):
        # Read-only map of the AXI-Lite window: the same /dev/mem path as pynq.MMIO without its ~3.5 s import.
        fd=os.open('/dev/mem',os.O_RDONLY|os.O_SYNC)
        try:
            m=mmap.mmap(fd,0x10000,mmap.MAP_SHARED,mmap.PROT_READ,offset=base)
            try:
                with memoryview(m) as raw,raw.cast('I') as words:return [words[o//4] for o in offsets]
            finally:m.close()
        finally:os.close(fd)
    values=dict(zip(('mm2s_control','mm2s_status','s2mm_control','s2mm_status'),read_words(0x43000000,(0,4,0x30,0x34))))
    assert values['mm2s_status']&1 and values['s2mm_status']&1
    assert not(values['mm2s_control']&1 or values['s2mm_control']&1) and read_words(0x41270000,(0,))[0]==0
    # The guardian polls at 1 Hz and removes the root a few seconds after the service
    # exits (pynq's 3.5 s import used to cover that wait). If it has gone without doing so,
    # or failed before startup completed, this verified root goes here instead. Only after
    # the exact service is gone and hardware is halted.
    try:guard_args=Path('/proc',(root/'guard.pid').read_text().strip(),'cmdline')
    except FileNotFoundError:guard_args=None
    end=time.monotonic()+12
    while root.exists() and time.monotonic()<end:
        if guard_args is None or not guard_args.exists():
            if root.exists():
                assert root.resolve()==root and (root/'.owner').read_text()==c['owner']
                shutil.rmtree(root)
            break
        time.sleep(.1)
    assert not root.exists(),'Lease guardian has not yet cleaned temporary files'
    with socket.socket() as s:assert s.connect_ex((c['host'],c['port']))!=0
    print('__REVIEW_RESULT__='+json.dumps(dict(status='STOPPED_DMA_HALTED_CORE_RESET',
        pid_gone=True,temporary_files_removed=True,registers=values,reset_gpio=0)),flush=True)
'''
