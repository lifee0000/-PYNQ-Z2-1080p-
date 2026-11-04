"""Assemble new full release while preserving the sealed 20261023 delivery."""
from pathlib import Path
import shutil,json
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1];dst=WS/'P4_UP'
assert not dst.exists()
shutil.copytree(WS/'P4_NET',dst)
history=dst/'history_20261023';history.mkdir()
for name in ('REPORT_CN.md','PUBLIC_VIDEO_REPORT_CN.md','QUALIFICATION.json','MANIFEST.json'):
    p=dst/name
    if p.exists():shutil.move(str(p),str(history/name))
# This is a newly created staging folder; replace only its copied old app.
app=dst/'V4/Windows_App'
assert app.resolve().is_relative_to(dst.resolve()) and dst.name=='P4_UP'
shutil.rmtree(app)
for source in ROOT.rglob('*'):
    if not source.is_file():continue
    rel=source.relative_to(ROOT)
    if rel.parts[0] in {'build','evidence','results','experiments'} or '__pycache__' in rel.parts or source.suffix=='.pyc':continue
    target=dst/'V4'/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
(dst/'V4/experiments').mkdir(exist_ok=True)
shutil.copytree(ROOT/'experiments',dst/'V4/experiments',dirs_exist_ok=True)
(dst/'V4/experiments/README.md').write_text('历史试验与被替代候选，供追溯；当前入口为工程根目录 START.cmd。\n全帧强制压缩和静态窗口曾使复杂人物画面变慢；不建议把这些候选覆盖当前程序。\n',encoding='utf-8')
print(dst)
