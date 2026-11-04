"""Prepare only the distinct exported YUYV422 IP; derive actual register offsets."""
import hashlib
import json
from pathlib import Path
import re
from zipfile import ZipFile
import xml.etree.ElementTree as ET
from contract import PARAMETER_ORDER, PIXEL_FORMAT, TOP

ROOT=Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    archive=ROOT/"output/video_enhance_yuyv422_v4_split_core.zip"
    identity=sha(archive)
    destination=ROOT/"output/ip_repo"/identity[:12]
    with ZipFile(archive) as z:
        if z.testzip() is not None:
            raise ValueError("Exported HLS IP archive CRC mismatch")
        for member in z.infolist():
            target=(destination/member.filename).resolve()
            if not target.is_relative_to(destination.resolve()):
                raise ValueError("Unsafe IP archive member")
        z.extractall(destination)
    component=destination/"component.xml"
    xml=ET.parse(component).getroot()
    def tag(e):
        return e.tag.rsplit("}",1)[-1]
    component_name=next(e.text for e in xml if tag(e)=="name")
    if component_name!=TOP:
        raise ValueError(f"Unexpected exported IP top {component_name!r}")
    headers=list(destination.glob("drivers/*/src/*_hw.h"))
    if len(headers)!=1:
        raise ValueError("Exactly one generated driver register header required")
    header=headers[0]
    found=dict((name.lower(),int(value,16)) for name,value in re.findall(
        r"#define\s+XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_(\w+)_DATA\s+(0x[0-9a-fA-F]+)",
        header.read_text(encoding="utf-8")))
    required=tuple(PARAMETER_ORDER)+("frame_count","stream_errors")
    if set(found)!=set(required) or len(set(found.values()))!=len(found):
        raise ValueError(f"Generated register set mismatch: {found}")
    if any(value%4 or value>=65536 for value in found.values()):
        raise ValueError("Generated register offset alignment/range invalid")
    controls=dict((name.lower(),int(value,16)) for name,value in re.findall(
        r"#define\s+XVIDEO_ENHANCE_YUYV422_V4_SPLIT_CORE_CTRL_ADDR_(AP_CTRL|GIE|IER|ISR)\s+(0x[0-9a-fA-F]+)",
        header.read_text(encoding="utf-8")))
    report=dict(schema=1,top=TOP,pixel_format=PIXEL_FORMAT,axis_data_bits=16,
        parameter_order=list(PARAMETER_ORDER),registers=found,control_registers=controls,
        register_source="Vitis exported driver header; offsets are extracted, never assumed",
        header=str(header.relative_to(ROOT)),header_sha256=sha(header),
        ip_sha256=identity,component_sha256=sha(component),
        qualification="HLS_IP_REGISTER_MAP_NOT_YET_MATCHED_TO_BIT_HWH")
    (ROOT/"output/yuyv422_v4.registers.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    (ROOT/"output/ip_repo_path.txt").write_text(f"ip_repo/{identity[:12]}\n",encoding="ascii")
    print(json.dumps(dict(status="YUYV_IP_READY",register_map="output/yuyv422_v4.registers.json",**report)))


if __name__=="__main__":
    main()
