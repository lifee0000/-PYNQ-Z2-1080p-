"""Bind the actual finished YUYV BIT/HWH/registers; never represents board acceptance."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from contract import PARAMETER_ORDER,PIXEL_FORMAT,TOP

ROOT=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    # Tie the already completed C/RTL simulation to the exact sources/IP
    # consumed by this implementation, rather than accepting a stale Pass.
    proof=json.loads((ROOT/'evidence/hls_verification.json').read_text(encoding='utf-8'))
    for name,digest in proof['sha256'].items():
        p=ROOT/Path(name.replace('\\','/'))
        if not p.is_file() or sha(p)!=digest:
            raise ValueError('HLS source/proof hash mismatch: '+name)
    bit=ROOT/"output/file_process_yuyv422.bit"
    hwh=ROOT/"output/file_process_yuyv422.hwh"
    registers=ROOT/"output/yuyv422_v4.registers.json"
    reg=json.loads(registers.read_text(encoding="utf-8"))
    if reg["top"]!=TOP or reg["pixel_format"]!=PIXEL_FORMAT or reg["axis_data_bits"]!=16:
        raise ValueError("Wrong register identity")
    if reg["ip_sha256"]!=sha(ROOT/"output/video_enhance_yuyv422_v4_split_core.zip"):
        raise ValueError("Exported IP changed after register extraction")
    root=ET.parse(hwh).getroot()
    modules={m.attrib.get("INSTANCE"):m for m in root.iter("MODULE")}
    core=modules["video_processing_slot"]
    if core.attrib.get("MODTYPE")!=TOP or core.attrib.get("VLNV")!=f"xilinx.com:hls:{TOP}:1.0":
        raise ValueError("HWH core top or VLNV mismatch")
    def parameters(module):
        return {p.attrib["NAME"].lower():p.attrib["VALUE"] for p in module.iter("PARAMETER")
                if 'NAME' in p.attrib and 'VALUE' in p.attrib}
    dma=parameters(modules["axi_vdma_file_process"])
    for key in ("c_m_axis_mm2s_tdata_width","c_s_axis_s2mm_tdata_width"):
        if int(dma[key])!=16:
            raise ValueError(f"HWH stream width incorrect: {key}={dma[key]}")
    for key in ('c_include_mm2s_dre','c_include_s2mm_dre'):
        if int(dma[key]) != 1:
            raise ValueError('Even-width frame line alignment requires DRE: '+key)
    ps=parameters(modules['processing_system7'])
    required_ps={'pcw_use_s_axi_acp':1,'pcw_use_s_axi_hp0':0,
        'pcw_use_default_acp_user_val':1,'pcw_s_axi_acp_aruser_val':31,'pcw_s_axi_acp_awuser_val':31}
    for key,value in required_ps.items():
        if int(ps[key],0)!=value:raise ValueError('ACP PS attribute mismatch: '+key)
    adapter=modules['acp_cache_attributes']
    if adapter.attrib.get('MODTYPE')!='axi_acp_cache':raise ValueError('Missing AXI cache attribute adapter')
    def bus(module,name):
        return next(b.attrib['BUSNAME'] for b in module.iter('BUSINTERFACE') if b.attrib['NAME']==name)
    if bus(modules['axi_smartconnect_memory'],'M00_AXI')!=bus(adapter,'S_AXI'):
        raise ValueError('ACP adapter input topology mismatch')
    if bus(adapter,'M_AXI')!=bus(modules['processing_system7'],'S_AXI_ACP'):
        raise ValueError('ACP adapter output topology mismatch')
    memory_interface=dict(kind='ACP_COHERENT',cache_value=15,aruser=31,awuser=31,
        ps_parameters=required_ps,adapter_sha256=sha(ROOT/'rtl/axi_acp_cache.v'),
        reference='https://docs.amd.com/r/en-US/ug585-zynq-7000-SoC-TRM/ACP-Requests')
    bdfile=ROOT/'build/file_fpga/file_process_yuyv422.srcs/sources_1/bd/file_process_yuyv422_bd/file_process_yuyv422_bd.bd'
    bd=json.loads(bdfile.read_text(encoding='utf-8'))['design']['addressing']
    dma_maps={}
    for space in ('Data_MM2S','Data_S2MM'):
        segment=bd['/axi_vdma_file_process']['address_spaces'][space]['segments']['SEG_acp_cache_attributes_reg0']
        if (str(segment.get('is_excluded','FALSE')).upper()!='FALSE' or
            int(segment['offset'],0)!=0 or segment['range']!='512M'):
            raise ValueError('Missing, excluded or incorrect DMA memory map: '+space)
        dma_maps[space]=segment
    memory_interface['dma_memory_maps']=dma_maps
    memory_interface['bd_sha256']=sha(bdfile)
    actual={}
    for register in core.iter("REGISTER"):
        fields={p.attrib["NAME"]:p.attrib["VALUE"] for p in register.findall("PROPERTY")}
        if register.attrib["NAME"] in reg["registers"]:
            actual[register.attrib["NAME"]]=int(fields["ADDRESS_OFFSET"],0)
    if actual!=reg["registers"]:
        raise ValueError(f"HWH registers differ from generated driver header: {actual}")
    expected={"video_processing_slot":0x43C20000,"axi_vdma_file_process":0x43000000,
              "axi_gpio_processing_reset":0x41270000}
    address_map={}
    for memory in root.iter("MEMRANGE"):
        name=memory.attrib.get("INSTANCE")
        if name in expected:
            address_map[name]=dict(base=int(memory.attrib["BASEVALUE"],0),
                high=int(memory.attrib["HIGHVALUE"],0))
    if {name:item["base"] for name,item in address_map.items()}!=expected:
        raise ValueError(f"HWH address map mismatch: {address_map}")
    source_files=[ROOT/"rtl/axi_acp_cache.v",ROOT/"hls/spatial_v4.cpp",ROOT/"hls/spatial_v4.h",ROOT/"hls/testbench.cpp",
        ROOT/"hls/vectors.h",ROOT/"reference.py",ROOT/"build_hls.tcl",ROOT/"tcl/build_file_process_yuyv422.tcl",
        ROOT/"prepare_vivado.py",ROOT/"finalize_vivado.py",ROOT/"build_vivado_windows.ps1"]
    reports=[ROOT/"reports/file_process_yuyv422"/name for name in
        ("timing.rpt","utilization.rpt","drc.rpt","timing_gate.json")]
    timing=json.loads(reports[-1].read_text(encoding="utf-8"))
    if timing["setup_slack_ns"]<0 or timing["hold_slack_ns"]<0 or timing["drc_errors"]!=0:
        raise ValueError("Hardware implementation timing/DRC gate did not pass")
    hls=ROOT/"build/yuyv422_v4_split_hls/solution1"
    cosim=hls/"sim/report/video_enhance_yuyv422_v4_split_core_cosim.rpt"
    if not re.search(r"Verilog\|\s*Pass\|",cosim.read_text(encoding="utf-8")):
        raise ValueError("Missing HLS RTL cosimulation Pass")
    pipeline=hls/"syn/report/video_enhance_yuyv422_v4_split_core_Pipeline_PAIRS_csynth.xml"
    ii=int(ET.parse(pipeline).getroot().findtext(".//PipelineII"))
    if ii!=2:
        raise ValueError(f"Pixel loop II is {ii}, not 2")
    artifacts=[bit,hwh,registers,ROOT/"output/video_enhance_yuyv422_v4_split_core.zip",cosim,pipeline,*reports]
    manifest=dict(schema=1,state="BUILT_NOT_BOARD_VALIDATED",top=TOP,pixel_format=PIXEL_FORMAT,
        axis_data_bits=16,bytes_per_pixel=2,memory_interface=memory_interface,parameter_order=list(PARAMETER_ORDER),
        address_map=address_map,registers=reg["registers"],pair_loop_ii=ii,pixels_per_iteration=2,
        timing_gate=timing,claim_end_to_end_50fps=False,
        artifacts={str(p.relative_to(ROOT)):sha(p) for p in artifacts},
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in source_files})
    (ROOT/"output/file_process_yuyv422.build.json").write_text(json.dumps(manifest,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(dict(status="YUYV_HARDWARE_BUILT_NOT_BOARD_VALIDATED",**manifest)))


if __name__=="__main__":
    main()
