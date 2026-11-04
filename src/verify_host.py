"""Reproduce host proof only; deliberately never starts HLS/Vivado or a board."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cxx", default=shutil.which("g++") or "g++")
    parser.add_argument("--vitis-include", type=Path, default=Path("D:/FPGA/2026.1/Vitis/include"))
    args = parser.parse_args()
    out=ROOT/"evidence";out.mkdir(exist_ok=True)
    report=dict(schema=1, evidence_kind="HOST_NUMPY_AND_NATIVE_CPP_WITH_VENDOR_TYPES",
        no_vivado_or_board_started=True, claim_50fps=False, steps=[])
    def run(name, argv):
        start=time.perf_counter()
        completed=subprocess.run([str(v) for v in argv], cwd=ROOT,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace", timeout=180)
        log=out/f"{name}.log";log.write_text(completed.stdout, encoding="utf-8")
        report["steps"].append(dict(name=name, argv=[str(v) for v in argv], returncode=completed.returncode,
            elapsed_s=time.perf_counter()-start, log=str(log.relative_to(ROOT)),
            log_sha256=hashlib.sha256(log.read_bytes()).hexdigest()))
        if completed.returncode:
            raise RuntimeError(f"{name} failed; see {log}")
        return completed.stdout
    run("vectors", [sys.executable, ROOT/"generate_vectors.py", "--source-vectors", ROOT/"source_vectors.json"])
    with (out/"host_tests.log").open("w", encoding="utf-8") as log:
        suite=unittest.defaultTestLoader.discover(str(ROOT), pattern="test_spatial.py")
        result=unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    report["host_tests"]=dict(tests=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), passed=result.wasSuccessful(), log="evidence/host_tests.log")
    if not result.wasSuccessful():
        raise RuntimeError("Host reference suite failed")
    run("compiler_version", [args.cxx, "--version"])
    run("native_compile", [args.cxx, "-std=c++17", "-O1", "-Wno-unknown-pragmas",
        "-I", args.vitis_include, "hls/spatial_v4.cpp", "hls/testbench.cpp", "-o", "evidence/native_csim.exe"])
    stdout=run("native_cpp", [out/"native_csim.exe"])
    if "YUYV_ALL_REFERENCE_VECTORS_PASS 148 + 2 full720p + 5 invalid" not in stdout:
        raise RuntimeError("Missing native acceptance sentinel")
    report["native_cpp"]=dict(reference_vectors=148, full_720p_frames=2,
        invalid_rejected=5, valid_pixels=1902648, exact_pixels=True,
        not_vendor_csim=True, not_rtl_cosim=True, not_synthesis=True)
    replay=out/"replay";replay.mkdir(exist_ok=True)
    run("replay_vectors", [sys.executable, ROOT/"generate_vectors.py", "--tests", ROOT/"source_vectors.json",
        "--output-dir", replay])
    if (replay/"vectors.h").read_bytes() != (ROOT/"hls/vectors.h").read_bytes():
        raise RuntimeError("Source-vector replay was not byte-identical")
    report["source_vectors_replay_exact"]=True
    report["identity"]={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(ROOT.rglob("*")) if path.is_file() and
        "evidence" not in path.relative_to(ROOT).parts and "__pycache__" not in path.relative_to(ROOT).parts
        and path.suffix in (".py", ".cpp", ".h", ".tcl", ".json", ".md")}
    report["vendor_header_sha256"]={name:hashlib.sha256((args.vitis_include/name).read_bytes()).hexdigest()
        for name in ("ap_int.h", "ap_axi_sdata.h", "hls_stream.h")}
    report["passed"]=True
    (out/"host_verification.json").write_text(json.dumps(report, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({"passed":True, "host_tests":result.testsRun, "native_cpp":report["native_cpp"],
        "report":str(out/"host_verification.json")}))


if __name__=="__main__":
    main()
