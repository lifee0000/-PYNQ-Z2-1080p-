"""Compile the independent native data plane. Board: python3 build_native.py.

Host Windows requires a GNU/Clang C++ compiler with Winsock and std::thread.
No hardware build/overlay load/server start is performed by this command.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import sys
import subprocess


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--compiler", default=os.environ.get("CXX", "g++"))
    p.add_argument("--output")
    p.add_argument("--sanitize", action="store_true")
    p.add_argument('--neon-hash',action='store_true',help='Experimental; Cortex-A9 measurements favoured scalar')
    args = p.parse_args()
    root = Path(__file__).resolve().parent
    windows = platform.system() == "Windows"
    output = (Path(args.output) if args.output else root / ("y50_native.dll" if windows else "liby50_native.so")).resolve()
    sources = [root / "y50_native.cpp", root / "codec_exports.cpp",
               root / "vendor/lz4/lz4.c", root / "vendor/lz4/xxhash.c",root / "rice_exports.cpp"]
    for source in sources:
        if not source.is_file():
            raise FileNotFoundError(f"Missing pinned native source: {source}")
    cmd = [args.compiler, "-std=c++17", "-O3", "-Wall", "-Wextra", "-Wpedantic",
           "-pthread", "-shared", *[os.path.relpath(source, output.parent) for source in sources],
           "-o", output.name]
    if windows:
        cmd += ["-static-libgcc", "-static-libstdc++", "-lws2_32"]
    else:
        cmd += ["-fPIC"]
        # Instruction selection for the actually detected Cortex-A9; no clock change.
        cpu=Path('/proc/cpuinfo').read_text() if Path('/proc/cpuinfo').is_file() else ''
        if platform.machine().startswith('armv7') and 'neon' in cpu and '0xc09' in cpu and sys.byteorder=='little':
            cmd += ['-mcpu=cortex-a9','-mfpu=neon','-mfloat-abi=hard']
    if args.neon_hash and not windows:cmd.append('-DP4_ENABLE_ARM_NEON=1')
    if args.sanitize:
        cmd += ["-fsanitize=address,undefined", "-fno-omit-frame-pointer", "-O1"]
    output.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(cmd, cwd=output.parent, check=True)
    print(json.dumps({"status": "COMPILED_ONLY_NOT_HARDWARE_VALIDATED", "command": cmd,
                      "platform": platform.platform(), "library": str(output.resolve()),
                      "protocol_version": 7, "codecs": ["raw", "rice03", "tans02"],
                      "checksum": "XXH32_WIRE_SEED0"}))


if __name__ == "__main__":
    main()
