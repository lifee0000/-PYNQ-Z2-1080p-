"""Explicit experimental board bootstrap. NOT a legacy RGB worker replacement.

Verified files -> exclusive hardware ownership -> PYNQ download/allocate -> native
I/O + DMA threads. Python performs no image algorithm and no per-frame pixel copy.
An unsafe DMA halt deliberately keeps allocations/mappings alive until board reset.
"""
import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import time
import shutil
import uuid

from binding import ABI, CACHE_OP, Config, Native, wire_capacity
from protocol import PARAMETER_ORDER, PIXEL_FORMAT, RICE_GEOMETRIES, VERSION

TOP = "video_enhance_yuyv422_v4_split_core"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_manifest(path):
    path = Path(path).resolve()
    m = json.loads(path.read_text(encoding="utf-8"))
    if (m.get("schema") != 2 or m.get("state") != "EXPERIMENTAL_UNQUALIFIED"
            or m.get('protocol_version') != VERSION or m.get('native_abi') != ABI
            or m.get("top") != TOP or m.get("pixel_format") != PIXEL_FORMAT):
        raise ValueError("unsupported/mislabelled experimental build manifest")
    root = path.parent
    resolved = {}
    for name, digest in m["files"].items():
        target = (root / name).resolve()
        if not target.is_relative_to(root) or len(digest) != 64 or sha(target) != digest:
            raise ValueError("build identity mismatch or unsafe relative path: " + name)
        resolved[name] = target
    for name in ("native/board_bootstrap.py", "native/binding.py", "native/protocol.py",
                 "native/y50_native.cpp", "native/y50_native.h", "native/rice_exports.cpp", "native/rice_codec.py",
                 "output/file_process_rice03.build.json"):
        if name not in resolved:
            raise ValueError("missing native runtime hash: " + name)
    if resolved["native/board_bootstrap.py"] != Path(__file__).resolve():
        raise ValueError("manifest is not for this runtime location")
    roles = {name: resolved[m[name]] for name in ("bit_file", "hwh_file", "register_file", "native_library")}
    implemented = json.loads(resolved['output/file_process_rice03.build.json'].read_text(encoding='utf-8'))
    gate = implemented['timing_gate']
    if (implemented['top'] != TOP or gate['setup_slack_ns'] < 0 or
            gate['hold_slack_ns'] < 0 or gate['drc_errors']):
        raise ValueError('Hardware implementation gate mismatch')
    if roles["bit_file"].with_suffix(".hwh") != roles["hwh_file"]:
        raise ValueError("same-name BIT/HWH pair required")
    for name in ('bit_file','hwh_file','register_file'):
        relative=roles[name].relative_to(root).as_posix()
        if implemented.get('artifacts',{}).get(relative)!=sha(roles[name]):
            raise ValueError('Routed implementation artifact mismatch: '+name)
    identity = {"manifest_sha256": sha(path), "qualification": "EXPERIMENTAL_UNQUALIFIED",
                "top": TOP, "pixel_format": PIXEL_FORMAT,
                "bit_sha256": sha(roles["bit_file"]), "hwh_sha256": sha(roles["hwh_file"]),
                "register_sha256": sha(roles["register_file"]),
                "native_sha256": sha(roles["native_library"])}
    return roles, identity


def forbid_existing_owner():
    """Read-only checks: never kill another project or hardware owner."""
    for process in Path("/proc").iterdir():
        if not process.name.isdigit() or int(process.name) == os.getpid():
            continue
        try:
            command = (process / "cmdline").read_bytes().replace(b"\0", b" ")
        except (PermissionError, FileNotFoundError, ProcessLookupError):
            continue
        if any(name in command for name in (b"file_process_server.py", b"board_bootstrap.py")):
            raise RuntimeError("another file-processing owner exists, PID " + process.name)
    with socket.socket() as probe:
        probe.settimeout(.25)
        if probe.connect_ex(("127.0.0.1", 5001)) == 0:
            raise RuntimeError("legacy RGB port 5001 is still owned; stop it before overlay download")


def configure(roles, identity, args):
    from pynq import Overlay, MMIO, allocate
    import numpy as np

    # PYNQ writes <bit stem>.bin into /lib/firmware during download. Use an
    # owned unique stem so an existing user firmware file is never replaced.
    # Keep the verified BIT/HWH unchanged; these temporary identical copies are
    # removed with the app-owned session directory.
    load_bit = roles["bit_file"].with_name("p6_session_" + uuid.uuid4().hex + ".bit")
    load_hwh = load_bit.with_suffix(".hwh")
    shutil.copyfile(roles["bit_file"], load_bit)
    shutil.copyfile(roles["hwh_file"], load_hwh)
    if sha(load_bit) != identity['bit_sha256'] or sha(load_hwh) != identity['hwh_sha256']:
        raise ValueError('Temporary overlay copy differs from verified build')
    firmware = Path('/lib/firmware') / load_bit.with_suffix('.bin').name
    if firmware.exists():raise ValueError('Owned firmware name unexpectedly exists')
    overlay = Overlay(str(load_bit), download=False)
    # Three slice decoders in the delivered build; a fourth when the bitstream has one.
    decoders=tuple(name for name in ('rice_decoder_0','rice_decoder_1','rice_decoder_2','rice_decoder_3') if name in overlay.ip_dict)
    if decoders not in (('rice_decoder_0','rice_decoder_1','rice_decoder_2'),('rice_decoder_0','rice_decoder_1','rice_decoder_2','rice_decoder_3')):
        raise ValueError('HWH must contain three or four consecutive slice decoders')
    codec_names=decoders+('rice_encoder',)
    for name in (args.vdma_name, args.core_name, args.reset_name,*codec_names):
        if name not in overlay.ip_dict:
            raise ValueError("HWH missing expected IP " + name)
    core_ip = overlay.ip_dict[args.core_name]
    if TOP not in core_ip.get("type", ""):
        raise ValueError("HWH core VLNV is not the new 16-bit YUYV top")
    dma_params = overlay.ip_dict[args.vdma_name].get("parameters", {})
    for name in ("C_M_AXIS_MM2S_TDATA_WIDTH", "C_S_AXIS_S2MM_TDATA_WIDTH"):
        value = dma_params.get(name)
        if value is None or int(str(value), 0) != 16:
            raise ValueError("HWH must prove 16-bit AXIS VDMA: " + name + "=" + str(value))
    register_map = json.loads(roles["register_file"].read_text(encoding="utf-8"))
    for name in ('C_INCLUDE_MM2S_DRE','C_INCLUDE_S2MM_DRE'):
        if int(str(dma_params.get(name,0)),0) != 1:
            raise ValueError('VDMA requires DRE for tightly packed arbitrary even width')
    if register_map.get("top") != TOP or register_map.get("pixel_format") != PIXEL_FORMAT:
        raise ValueError("generated register map top/format mismatch")
    registers = register_map["registers"]
    required = (*PARAMETER_ORDER, "frame_count", "stream_errors")
    if set(required) - set(registers):
        raise ValueError("generated register map is incomplete")
    for name in required:
        if isinstance(registers[name], str):
            registers[name] = int(registers[name], 0)
        if type(registers[name]) is not int or registers[name] < 0x10 or registers[name] % 4:
            raise ValueError("invalid AXI-Lite offset " + name)
    implementation=json.loads(roles['bit_file'].with_suffix('.build.json').read_text())
    policy=implementation.get('memory_interface',{}).get('kind','HP_EXPLICIT_MAINTENANCE')
    if args.coherent_acp and policy!='ACP_COHERENT':
        raise ValueError('Coherent cached DMA requires the proven ACP hardware build')
    if args.coherent_acp:
        memory=implementation['memory_interface']
        if (memory.get('cache_value')!=15 or memory.get('aruser')!=31 or memory.get('awuser')!=31):
            raise ValueError('ACP cache/inner/shareable attributes are not the verified contract')
        if len(memory.get('master_maps',{}))!=2*len(decoders)+4:
            raise ValueError('P6 requires ten verified ACP master address spaces')
        for name,segment in memory['master_maps'].items():
            if (int(segment.get('offset','-1'),0)!=0 or segment.get('range')!='512M' or
                    str(segment.get('is_excluded','FALSE')).upper()!='FALSE'):
                raise ValueError('ACP DMA address map missing or excluded: '+name)
    if args.hp_packets and policy not in ('HP_DEVICE_FRAMES_EXPLICIT_CPU_SYNC','HYBRID_ACP_PACKETS_HP_FRAMES'):raise ValueError('HP cached packets require identified HP hardware')
    if policy in ('HP_DEVICE_FRAMES_EXPLICIT_CPU_SYNC','HYBRID_ACP_PACKETS_HP_FRAMES') and not args.hp_packets:raise ValueError('This build requires --hp-packets')
    if args.hp_packets:
        master_maps=implementation.get('memory_interface',{}).get('master_maps',{})
        # VDMA read/write, encoder in/out and every decoder's in/out.
        if len(master_maps)!=2*len(decoders)+4:raise ValueError('HP build must prove every DMA/codec address space')
        if policy=='HYBRID_ACP_PACKETS_HP_FRAMES' and (implementation['memory_interface'].get('cache_value')!=15 or implementation['memory_interface'].get('aruser')!=31 or implementation['memory_interface'].get('awuser')!=31):raise ValueError('Hybrid coherent packet attributes mismatch')
        for name,segment in master_maps.items():
            if int(segment.get('offset','-1'),0)!=0 or segment.get('range')!='512M' or str(segment.get('is_excluded','FALSE')).upper()!='FALSE':
                raise ValueError('HP DDR memory map invalid: '+name)
            if policy=='HYBRID_ACP_PACKETS_HP_FRAMES':
                is_packet=(name.startswith('rice_decoder_') and name.endswith('/Data_m_axi_inmem')) or name=='rice_encoder/Data_m_axi_outmem'
                expected='/acp_cache_attributes/S_AXI/reg0' if is_packet else '/processing_system7/S_AXI_HP0/HP0_DDR_LOWOCM'
                if segment.get('address_block')!=expected:raise ValueError('Hybrid master route mismatch: '+name)
    if policy=='ACP_COHERENT' and not args.coherent_acp:
        raise ValueError('This candidate requires --coherent-acp, not HP cache policy')
    expected_decoder={'input_r':0x10,'output_r':0x1c,'encoded_size':0x28,'capacity_bytes':0x30,'slice_index':0x38,'decoded_size':0x40,'error_code':0x50}
    expected_encoder={'input_r':0x10,'output_r':0x1c,'method':0x28,'capacity_bytes':0x30,'quant_shift':0x38,'encoded_size':0x40,'error_code':0x50,'width':0x60,'height':0x68}
    for name in codec_names:
        record=implementation['codec_ips'][name]
        if overlay.ip_dict[name]['type']!=record['vlnv'] or record['registers']!=(expected_encoder if name=='rice_encoder' else expected_decoder):
            raise ValueError('Codec HWH/register contract mismatch: '+name)
    for name,record in implementation['address_map'].items():
        if overlay.ip_dict[name]['phys_addr']!=record['base']:
            raise ValueError('HWH physical address mismatch: '+name)
    try:
        overlay.download()
    finally:
        # FPGA manager has consumed this file when download returns. Only this
        # random session name is eligible for removal; no shared firmware name.
        if firmware.is_file() and not firmware.is_symlink():firmware.unlink()
    mappings = []
    for name in (args.vdma_name, args.core_name, args.reset_name,*codec_names):
        ip = overlay.ip_dict[name]
        mappings.append(MMIO(ip["phys_addr"], ip["addr_range"]))
    size = args.max_width * args.max_height * 2
    packet_capacity=wire_capacity(args.max_width, args.max_height)

    def allocate_slots(slots):
        buffers=[]
        try:
            for index,n in enumerate([size]*(2*slots)+[packet_capacity]*(2*slots)):
                # The installed XRT allocator maps cacheable BOs even when False
                # is requested. Raw frames are therefore device-only while in the
                # pipeline, and are synchronized only on an actual CPU transition.
                cached=True
                b=allocate(shape=(n,),dtype=np.uint8,cacheable=cached)
                buffers.append(b)
                if hasattr(b,'cacheable') and bool(b.cacheable)!=cached:raise ValueError('CMA cache policy not honoured')
        except BaseException:
            for b in buffers:b.freebuffer()
            raise
        return buffers
    # Six 1080p slots need about 100 MB of CMA. If the board's pool is smaller,
    # fall back to three slots once and report it; never shrink a frame buffer.
    try:
        buffers=allocate_slots(args.slots)
    except (MemoryError,RuntimeError) as exc:
        if args.slots!=6:raise
        print(json.dumps({"event":"CMA_SIX_SLOTS_UNAVAILABLE_RETRY_THREE","error":str(exc),
                          "bytes_requested":12*(size+packet_capacity)}),flush=True)
        args.slots=3
        buffers=allocate_slots(3)
    callback_errors = []
    if args.hp_packets:
        for b in buffers:
            b.flush()
            b.invalidate()

    @CACHE_OP
    def cache(_user, index, op):
        try:
            if not 0 <= index < args.slots:
                raise ValueError("invalid DMA slot")
            length=op>>8;op=op&255
            if args.hp_packets:
                if not 0<length<=packet_capacity:raise ValueError('packet cache length invalid')
                # Same device API as PynqBuffer.flush/invalidate, with the
                # logical packet extent. No temporary view can own/free DMA.
                if op==3:
                    b=buffers[index+2*args.slots]
                    if not b.coherent:b.device.flush(b.bo,b.offset,b.virtual_address,length)
                elif op in (4,5):
                    b=buffers[index+3*args.slots]
                    if not b.coherent:b.device.invalidate(b.bo,b.offset,b.virtual_address,length)
                elif op==6:
                    b=buffers[index]
                    if not b.coherent:b.device.flush(b.bo,b.offset,b.virtual_address,length)
                elif op==7:
                    b=buffers[index+args.slots]
                    if not b.coherent:b.device.invalidate(b.bo,b.offset,b.virtual_address,length)
                else:raise ValueError('HP explicit ownership requires operation 3 through 7')
                return 0
            if op == 0:
                buffers[index].flush()
            elif op in (1, 2):
                buffers[index+args.slots].invalidate()
            else:
                raise ValueError("invalid cache operation")
            return 0
        except BaseException as exc:
            callback_errors.append(str(exc))
            return -1
    identity_json = json.dumps(identity, ensure_ascii=True, sort_keys=True).encode()
    cfg = Config(abi=ABI, slot_count=args.slots, max_width=args.max_width, max_height=args.max_height,
                 port=args.port, dma_timeout_ms=args.dma_timeout_ms,
                 socket_timeout_ms=args.socket_timeout_ms, capacity_bytes=size,
                 cacheable=(4 if policy=='HYBRID_ACP_PACKETS_HP_FRAMES' else 3) if args.hp_packets else 2 if args.coherent_acp else int(args.cacheable), cache_op=cache,
                 identity_json=identity_json, bind_ipv4=args.bind.encode(),
                 codec_mmio_bytes=0x100,wire_capacity_bytes=packet_capacity)
    cfg.vdma, cfg.core, cfg.reset_gpio = [m.array.ctypes.data for m in mappings[:3]]
    cfg.vdma_bytes, cfg.core_bytes, cfg.gpio_bytes = [m.array.nbytes for m in mappings[:3]]
    # A/B switch: run a four-decoder bitstream with three bands (the fourth stays idle).
    active=3 if os.environ.get('P6_DECODER_BANDS')=='3' else len(decoders)
    for i in range(active):cfg.decoder[i]=mappings[i+3].array.ctypes.data
    cfg.encoder=mappings[3+len(decoders)].array.ctypes.data
    cfg.decoder_count=active
    for i, name in enumerate(PARAMETER_ORDER):
        cfg.parameter_offsets[i] = registers[name]
    cfg.frame_count_offset = registers["frame_count"]
    cfg.stream_errors_offset = registers["stream_errors"]
    for i in range(args.slots):
        cfg.input[i], cfg.output[i] = buffers[i].ctypes.data, buffers[i+args.slots].ctypes.data
        cfg.input_physical[i], cfg.output_physical[i] = buffers[i].device_address, buffers[i+args.slots].device_address
        cfg.wire_input[i],cfg.wire_output[i]=buffers[i+2*args.slots].ctypes.data,buffers[i+3*args.slots].ctypes.data
        cfg.wire_input_physical[i],cfg.wire_output_physical[i]=buffers[i+2*args.slots].device_address,buffers[i+3*args.slots].device_address
    # One reset release for the whole pipeline. Per-frame GPIO resets would
    # abort other slots' independent decoder/encoder AXI transactions.
    mappings[2].write(4,0)
    mappings[2].write(0,1)
    time.sleep(.001)
    native = Native(roles["native_library"], cfg,
                    (overlay, mappings, buffers, cache, identity_json, callback_errors))
    return native, buffers


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--manifest", required=True)
    p.add_argument("--slots", type=int, choices=(3,6), default=6)
    p.add_argument("--port", type=int, default=5010)
    p.add_argument("--max-geometry", choices=[f"{w}x{h}" for w, h in RICE_GEOMETRIES], default="1920x1080",
                   help="largest session frame; sizes every CMA frame and packet buffer")
    p.add_argument("--bind", default="192.168.2.99")
    memory=p.add_mutually_exclusive_group()
    memory.add_argument("--hp-packets",action="store_true",help="HP DDR with device-owned frames and explicit bounded CPU synchronization")
    memory.add_argument("--cacheable", action="store_true", help="explicit HP cache maintenance")
    memory.add_argument("--coherent-acp", action="store_true", help="requires identified ACP hardware; cached CMA, no flush/invalidate")
    p.add_argument("--dma-timeout-ms", type=int, default=2000)
    p.add_argument("--socket-timeout-ms", type=int, default=10000)
    p.add_argument("--poll-us",type=int,choices=(20,100,200,500),default=20)
    p.add_argument("--large-socket-buffers",action='store_true')
    p.add_argument("--vdma-name", default="axi_vdma_file_process")
    p.add_argument("--core-name", default="video_processing_slot")
    p.add_argument("--reset-name", default="axi_gpio_processing_reset")
    args = p.parse_args()
    args.max_width, args.max_height = map(int, args.max_geometry.split('x'))
    os.environ['P6_POLL_US']=str(args.poll_us)
    os.environ['P6_FORCE_SOCKET_BUFFERS']='1' if args.large_socket_buffers else '0'
    roles, identity = verify_manifest(args.manifest)
    import fcntl
    # This lock protects native bootstrap instances; process/port checks also
    # guard the existing independently deployed RGB service before download.
    lock = open("/run/pynq_yuyv_native.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    forbid_existing_owner()
    native, buffers = configure(roles, identity, args)
    stopping = False

    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    print(json.dumps({"event": "NATIVE_YUYV_EXPERIMENTAL_STARTED", **native.status()}), flush=True)
    try:
        while not stopping:
            time.sleep(.2)
    finally:
        try:
            native.stop()
            print(json.dumps({"event": "STOPPED", **native.status()}), flush=True)
            native.close()
        except RuntimeError as exc:
            print(json.dumps({"event": "UNSAFE_DMA_RETAINING_BUFFERS", "error": str(exc)}), flush=True)
            # A failed halt must not release CMA or the MMIO mappings. Require
            # board power reset; SIGTERM/SIGINT remain cooperative and retain.
            while True:
                time.sleep(1)
        for buffer in buffers:
            buffer.freebuffer()
    lock.close()


if __name__ == "__main__":
    main()
