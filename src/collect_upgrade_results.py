from pathlib import Path
import json,shutil
ROOT=Path(__file__).resolve().parent;WS=ROOT.parents[1];dest=WS/'P4_UP'
assert json.loads((ROOT/'evidence/full_videos.json').read_text())['status']=='PASS'
assert json.loads((ROOT/'evidence/soak_300s/soak.json').read_text())['status']=='PASS'
assert json.loads((ROOT/'evidence/final_board_state.json').read_text())['status']=='STOPPED_DMA_HALTED_CORE_RESET'
shutil.copytree(ROOT/'results',dest/'results/upgrade_20261024',dirs_exist_ok=True)
shutil.copytree(ROOT/'evidence',dest/'V4/evidence',dirs_exist_ok=True)
shutil.copytree(ROOT/'evidence',dest/'evidence/upgrade_20261024',dirs_exist_ok=True)
# Include late-created run/review helpers too; omit build and interpreter caches.
for p in ROOT.glob('*.py'):shutil.copy2(p,dest/'V4'/p.name)
shutil.copy2(ROOT/'evidence/final_board_state.json',dest/'evidence/final_board_state.json')
print('Collected completed actual-board outputs and evidence')
