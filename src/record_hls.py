"""Record actual local HLS reports; no board, networking or bitstream operations."""
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from zipfile import ZipFile

ROOT=Path(__file__).resolve().parent
TOP="video_enhance_yuyv422_v4_split_core"


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    solution=ROOT/"build/yuyv422_v4_split_hls/solution1"
    synth=solution/f"syn/report/{TOP}_csynth.xml"
    pairs=solution/f"syn/report/{TOP}_Pipeline_PAIRS_csynth.xml"
    cosim=solution/f"sim/report/{TOP}_cosim.rpt"
    csim=solution/f"csim/report/{TOP}_csim.log"
    rtl_log=solution/f"sim/report/verilog/{TOP}.log"
    archive=ROOT/f"output/{TOP}.zip"
    with ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError("IP archive CRC error")
        headers=[name for name in z.namelist() if name.endswith("_hw.h")]
        if len(headers)!=1:raise ValueError("Expected one generated IP driver header")
        header_name=headers[0];header_bytes=z.read(header_name)
        registers={name.lower():int(value,16) for name,value in re.findall(
            rf"#define\s+X{TOP.upper()}_CTRL_ADDR_(\w+)_DATA\s+(0x[0-9a-fA-F]+)",
            header_bytes.decode("utf-8"))}
    sentinel="YUYV_ALL_REFERENCE_VECTORS_PASS 148 + 2 full720p + 5 invalid"
    for path in (csim,rtl_log):
        if sentinel not in path.read_text(encoding="utf-8",errors="replace"):
            raise ValueError(f"Missing test completion in {path}")
    cosim_text=cosim.read_text(encoding="utf-8",errors="replace")
    match=re.search(r"Verilog\|\s*Pass\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|\s*(\d+)\|",cosim_text)
    if not match:raise ValueError("RTL cosim not Pass or latency report malformed")
    latency_min,latency_avg,latency_max,interval_min,interval_avg,interval_max,cycles=map(int,match.groups())
    p=ET.parse(pairs).getroot();ii=int(p.findtext(".//PipelineII"))
    if ii!=2:raise ValueError(f"Pair loop II changed: {ii}")
    xml=ET.parse(synth).getroot()
    resources={e.tag:int(e.text) for e in xml.find("AreaEstimates/Resources")}
    available={e.tag:int(e.text) for e in xml.find("AreaEstimates/AvailableResources")}
    resource_pct={key:100*resources[key]/available[key] for key in resources if available[key]}
    clock=float(xml.findtext("UserAssignments/TargetClockPeriod"))
    estimate=float(xml.findtext("PerformanceEstimates/SummaryOfTimingAnalysis/EstimatedClockPeriod"))
    if estimate>clock:raise ValueError("HLS estimated clock exceeds target")
    vectors=json.loads((ROOT/"hls/vectors.json").read_text(encoding="utf-8"))
    expected_registers=set(vectors["cases"][0]["params"])|{"width","height","frame_count","stream_errors"}
    if set(registers)!=expected_registers or "noise_floor_uv" not in registers:
        raise ValueError("New split input interface differs from actual exported IP")
    for name,expected in vectors["source_sha256"].items():
        if sha(ROOT/name)!=expected:raise ValueError(f"Source no longer matches vectors: {name}")
    inputs=[synth,pairs,cosim,csim,rtl_log,archive,ROOT/"evidence/host_verification.json",
        ROOT/"hls/spatial_v4.cpp",ROOT/"hls/spatial_v4.h",ROOT/"hls/testbench.cpp",ROOT/"hls/vectors.h",
        ROOT/"hls/vectors.json",ROOT/"reference.py",ROOT/"reference_v3_frozen.py",ROOT/"build_hls.tcl"]
    report=dict(schema=1,status="LOCAL_HLS_CSIM_SYNTH_RTL_PASS_NOT_BOARD_VALIDATED",
        top=TOP,pixel_format="YUYV422_BT709_FULL_YUV_V4_SPLIT",evidence_kind="HLS_SIMULATION_AND_SYNTHESIS_ESTIMATE",
        no_board_operations=True,no_vivado_implementation=True,no_project_package_created=True,
        vectors=148,full_720p_frames=2,full_720p_modes=[0,3],invalid_rejections=5,exact_pixels=1902648,
        pair_loop_ii=ii,pixels_per_iteration=2,requested_clock_ns=clock,estimated_clock_ns=estimate,
        resources_hls_estimate=resources,resource_percent=resource_pct,
        generated_ip_registers=registers,generated_header_in_ip=header_name,
        generated_header_sha256=hashlib.sha256(header_bytes).hexdigest(),
        register_qualification="EXPORTED_IP_ONLY_NOT_MATCHED_TO_BIT_HWH",
        rtl_latency_cycles=dict(min=latency_min,avg=latency_avg,max=latency_max),
        rtl_interval_cycles=dict(min=interval_min,avg=interval_avg,max=interval_max),
        rtl_complete_run_cycles=cycles,max_observed_transaction_ms_at_target=latency_max*clock/1e6,
        claim_end_to_end_50fps=False,
        limits=["No BIT/HWH, P&R timing or board run in this scope",
            "Host model and RTL use fixed synthetic vectors, not processed user video",
            "Impulse detection may remove a truly isolated intentional one-pixel feature",
            "ROI/frame boundaries are preserved or replicated and are not promised impulse removal",
            "Spatial filter cannot guarantee denoising severe noise or temporal consistency"],
        sha256={str(path.relative_to(ROOT)):sha(path) for path in inputs})
    (ROOT/"evidence/hls_verification.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report))


if __name__=="__main__":main()
