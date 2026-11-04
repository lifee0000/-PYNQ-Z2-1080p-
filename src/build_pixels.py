from pathlib import Path
import argparse,hashlib,json,subprocess,sys,platform
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--compiler',default='C:/msys64/mingw64/bin/g++.exe');a=p.parse_args()
out=root/'native_pixels/p4_pixels.dll'
cmd=[a.compiler,'-std=c++17','-O3','-Wall','-Wextra','-Werror','-pthread','-shared','-static',
     'pixels_native.cpp','-o',out.name]
# MinGW's linker cannot encode this user's non-ASCII workspace output path.
# Relative paths keep the compiler command ASCII without moving the project.
subprocess.run(cmd,check=True,cwd=root/'native_pixels')
r=dict(status='COMPILED_NOT_YET_PARITY_VERIFIED',command=cmd,cwd='native_pixels',machine=platform.machine(),
       source_sha256=hashlib.sha256((root/'native_pixels/pixels_native.cpp').read_bytes()).hexdigest(),
       library_sha256=hashlib.sha256(out.read_bytes()).hexdigest())
(root/'native_pixels/build.json').write_text(json.dumps(r,indent=2),encoding='utf-8')
print(json.dumps(r))
