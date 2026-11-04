"""Save only host compile/mock evidence. No board/network address is contacted."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import py_compile
import subprocess
import sys
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compiler", default="C:/msys64/mingw64/bin/g++.exe")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    evidence = root / "evidence"
    evidence.mkdir(exist_ok=True)
    report = {"schema": 1, "evidence_kind": "HOST_NATIVE_TRANSPORT_MOCK_ONLY",
              "board_connected": False, "overlay_loaded": False,
              "hardware_dma_tested": False, "claims_50fps": False,
              "platform": platform.platform(), "steps": []}
    for source in root.glob("*.py"):
        py_compile.compile(str(source), doraise=True)
    for name, command in (
            ("compile", [sys.executable, "build_native.py", "--compiler", args.compiler]),
            ("mock_tests", [sys.executable, "-X", "utf8", "test_native_mock.py"])):
        started = time.perf_counter()
        run = subprocess.run(command, cwd=root, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                             text=True, encoding="utf-8", errors="replace", timeout=60)
        log = evidence / (name + ".log")
        log.write_text(run.stdout, encoding="utf-8")
        report["steps"].append({"name": name, "command": command, "returncode": run.returncode,
                                "elapsed_seconds": time.perf_counter() - started,
                                "log": log.name, "sha256": hashlib.sha256(log.read_bytes()).hexdigest()})
        if run.returncode:
            report["passed"] = False
            (evidence / "host_checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            raise RuntimeError(name + " failed")
    report["passed"] = True
    report["mock_tests"] = 8
    report["source_sha256"] = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in sorted(root.iterdir()) if path.is_file()
                               and path.suffix in (".py", ".cpp", ".h", ".md", ".dll", ".so")}
    target = evidence / "host_checks.json"
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"passed": True, "mock_tests": 8, "real_board_tests": 0, "report": str(target)}))


if __name__ == "__main__":
    main()
