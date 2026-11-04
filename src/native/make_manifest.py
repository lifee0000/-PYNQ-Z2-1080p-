"""Record an EXPERIMENTAL native/YUYV build identity, never a PASS claim.

Run only after compiling the library for the target ARM/Linux architecture and
placing the generated same-name BIT/HWH and real component-derived register map
inside the isolated yuv50 directory. No hardware loading or test bypass occurs.
"""
import argparse
import hashlib
import json
from pathlib import Path


def validate_arm_sources(root, compiled):
    """Reject changed, removed AND newly added sources after the ARM build."""
    current_sources = {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root/'native').rglob('*'))
        if path.is_file() and (path.suffix in ('.c','.cpp','.h') or path.name=='build_native.py')}
    if current_sources != compiled['source_sha256']:
        changed = sorted(name for name in current_sources.keys() | compiled['source_sha256'].keys()
            if current_sources.get(name) != compiled['source_sha256'].get(name))
        raise ValueError('Native sources changed after ARM compilation: ' + ', '.join(changed))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--bit", type=Path, required=True)
    p.add_argument("--registers", type=Path, required=True)
    p.add_argument("--library", type=Path, required=True)
    args = p.parse_args()
    root = args.root.resolve()
    build = root/'output/file_process_rice03.build.json'
    implementation = json.loads(build.read_text(encoding='utf-8'))
    if implementation['top'] != 'video_enhance_yuyv422_v4_split_core':
        raise ValueError('Wrong implemented HLS core')
    gate = implementation['timing_gate']
    if gate['setup_slack_ns'] < 0 or gate['hold_slack_ns'] < 0 or gate['drc_errors']:
        raise ValueError('Implementation timing/DRC did not pass')
    arm_record=root/'native/arm_build.json'
    compiled=json.loads(arm_record.read_text(encoding='utf-8'))
    if compiled.get('machine')!='armv7l' or not compiled.get('sources_unchanged_during_build'):
        raise ValueError('Missing actual ARM compile provenance')
    validate_arm_sources(root, compiled)
    if hashlib.sha256(args.library.read_bytes()).hexdigest()!=compiled['native_sha256']:
        raise ValueError('ARM library differs from recorded build')
    sources = [root / "native" / name for name in (
        "board_bootstrap.py", "binding.py", "protocol.py", "codec.py", "codec_exports.cpp",
        "build_native.py", "rebuild_arm.py", "y50_native.cpp", "y50_native.h", "wire_hash.h",
        "PROTOCOL_V5.md", "PROTOCOL_V6.md", "PROTOCOL_V7.md", "near_reference.h", "rice_exports.cpp", "rice02_fast.h", "rice03_near_fast.h", "rice03_decode_fast.h", "tans_reference.h", "tans_tables.h", "tans02_fast.h", "rice_codec.py", "rice_reference/rice_codec.cpp", "rice_reference/rice03_codec.cpp")]
    vendor = root / "native/vendor/lz4"
    for name in ("lz4.c", "lz4.h", "xxhash.c", "xxhash.h", "LICENSE"):
        if not (vendor / name).is_file():
            raise FileNotFoundError(f"Missing pinned codec source/license: {vendor / name}")
    sources += sorted(path for path in vendor.rglob("*") if path.is_file())
    roles = {"bit_file": args.bit.resolve(), "hwh_file": args.bit.with_suffix(".hwh").resolve(),
             "register_file": args.registers.resolve(), "native_library": args.library.resolve()}
    for key in ('bit_file','hwh_file','register_file'):
        path = roles[key]
        if implementation['artifacts'].get(str(path.relative_to(root)).replace('\\','/')) != hashlib.sha256(path.read_bytes()).hexdigest():
            # Windows-generated manifest paths may have backslashes.
            normalized = {k.replace('\\','/'):v for k,v in implementation['artifacts'].items()}
            if normalized.get(path.relative_to(root).as_posix()) != hashlib.sha256(path.read_bytes()).hexdigest():
                raise ValueError('Implemented artifact mismatch: '+key)
    files = {}
    for path in [*sources, *roles.values(),build,arm_record]:
        if not path.is_relative_to(root):
            raise ValueError("all experimental artifacts must be inside --root")
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    result = {"schema": 2, "state": "EXPERIMENTAL_UNQUALIFIED", "native_abi":10,
              "top": "video_enhance_yuyv422_v4_split_core", "pixel_format": "YUYV422_BT709_FULL_YUV_V4_SPLIT",
              "protocol_version": 7, "max_geometry": [1920, 1080], "wire_codecs": ["raw", "rice03"], "output_codecs":["raw","tans02"],"return_codec":"tans02", "checksum": "XXH32_WIRE_SEED0",
              **{name: path.relative_to(root).as_posix() for name, path in roles.items()}, "files": files}
    target = root / "native_yuyv.experimental.json"
    target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(target)


if __name__ == "__main__":
    main()
