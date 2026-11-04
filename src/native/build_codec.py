"""Build the standalone lossless transport codec; no hardware or sockets."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--compiler", default=os.environ.get("CXX", "g++"))
    parser.add_argument("--output")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    windows = platform.system() == "Windows"
    output = Path(args.output).resolve() if args.output else root / ("p4_codec.dll" if windows else "libp4_codec.so")
    sources = [root / "codec_exports.cpp", root / "vendor/lz4/lz4.c", root / "vendor/lz4/xxhash.c"]
    upstream = json.loads((root / "vendor/lz4/UPSTREAM.json").read_text(encoding="utf-8"))
    for item in upstream["unmodified_files"]:
        data = (root / "vendor/lz4" / item["file"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != item["sha256"]:
            raise RuntimeError("Bundled upstream source checksum mismatch: " + item["file"])
    output.parent.mkdir(parents=True, exist_ok=True)
    command = [args.compiler, "-std=c++17", "-O3", "-Wall", "-Wextra", "-Wpedantic", "-shared"]
    command += [os.path.relpath(p, output.parent) for p in sources]
    command += ["-o", output.name]
    command += ["-static-libgcc", "-static-libstdc++"] if windows else ["-fPIC"]
    subprocess.run(command, cwd=output.parent, check=True)
    files = sources + [root/'wire_hash.h', root / "vendor/lz4/lz4.h", root / "vendor/lz4/xxhash.h", root / "vendor/lz4/LICENSE"]
    result = {"status": "BUILT_NOT_TESTED", "abi": 1, "lz4_version": "1.10.0",
              "compiler": subprocess.check_output([args.compiler, "--version"], text=True).splitlines()[0],
              "command": command, "platform": platform.platform(), "library": output.name,
              "library_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
              "sources": {str(p.relative_to(root)).replace("\\", "/"): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    output.with_suffix(output.suffix + ".build.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
