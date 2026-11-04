"""Real-Tk comparison acceptance, using isolated settings and no board connection."""
import json
import os
from pathlib import Path


def check(folder):
    import gui
    from PIL import Image
    from preview_compare import VIEWS,MODES
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    report=dict(status='RUNNING',scope='REAL_TK_COMPARISON_UI_NO_BOARD',checks=[],no_board_connection=True)
    errors=[]
    previous=os.environ.get('PYNQ_VIDEO_SETTINGS_PATH')
    os.environ['PYNQ_VIDEO_SETTINGS_PATH']=str(folder/'isolated_profile.json')
    def run(root,state):
        try:
            root.update()
            state['compare_button'].invoke();root.update()
            viewer=state['open_comparison']();root.update()
            assert viewer.pair is not None and viewer.sample_mode and len(viewer.samples)==6
            assert viewer.pair[2]['display_label']=='实板核验样张'
            report['checks'].append('sample_entry_and_provenance')
            viewer.view.set(VIEWS[1]);viewer.change_view();root.update()
            assert viewer.photo.width()==viewer.last_crop[2] and viewer.photo.height()==viewer.last_crop[3]
            viewer.view.set(VIEWS[3]);viewer.change_view();root.update()
            assert viewer.photo.width()==viewer.last_crop[2]*4 and viewer.photo.height()==viewer.last_crop[3]*4
            report['checks'].append('true_one_to_one_and_four_times')
            from types import SimpleNamespace
            old_crop=viewer.last_crop
            x,y,w,h=viewer.rect
            viewer.choose_focus(SimpleNamespace(x=x+w*.15,y=y+h*.2));root.update()
            assert viewer.last_crop!=old_crop
            report['checks'].append('same_location_detail_selection')
            viewer.export(folder/'physical_qualified_sample.png')
            viewer.show_live();viewer.view.set(VIEWS[1]);viewer.change_view()
            before=Image.new('RGB',(80,60),(20,30,40));after=Image.new('RGB',(80,60),(40,60,80))
            meta=dict(frames=1,processing_size=[80,60],native_full_frame=True,display_label='CPU 参考')
            viewer.set_live(before,after,meta);root.update()
            viewer.frozen.set(True);viewer.change_freeze()
            viewer.set_live(before,Image.new('RGB',(80,60),(90,100,110)),dict(meta,frames=2));root.update()
            assert viewer.pair[2]['frames']==1 and viewer.latest[2]['frames']==2
            viewer.export(folder/'frozen_frame.png')
            exported=json.loads((folder/'frozen_frame.png.json').read_text(encoding='utf-8'))
            assert exported['metadata']['frames']==1 and exported['metadata']['display_label']=='CPU 参考'
            report['checks'].append('freeze_export_keeps_original_frame_and_backend')
            viewer.show_original(True);root.update();assert viewer.peek
            viewer.show_original(False);viewer.frozen.set(False);viewer.change_freeze();root.update()
            assert viewer.pair[2]['frames']==2
            report['checks'].append('peek_and_resume')
            state['detail'].set(False);root.update();assert not bool(state['live_preview'])
            viewer.change_view();root.update();assert bool(state['live_preview'])
            state['detail'].set(False);root.update();assert not bool(state['live_preview'])
            report['checks'].append('live_detail_request_without_tk_calls_in_worker')
            viewer.mode.set(MODES[1]);viewer.redraw();root.update()
            assert viewer.photo.width()==172
            viewer.destroy();root.update()
            state['compare_button'].invoke();root.update()
            assert state['open_comparison']().winfo_exists()
            report['checks'].append('close_reopen')
            report['status']='PASS'
        except BaseException as exc:
            import traceback
            errors.append(exc);report.update(status='FAIL',error=str(exc),traceback=traceback.format_exc())
        finally:
            root.destroy()
            (folder/'comparison_ui.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    gui._UI_CHECK_HOOK=run
    try:gui.main()
    finally:
        gui._UI_CHECK_HOOK=None
        if previous is None:os.environ.pop('PYNQ_VIDEO_SETTINGS_PATH',None)
        else:os.environ['PYNQ_VIDEO_SETTINGS_PATH']=previous
    if errors:raise RuntimeError('Comparison UI check failed: '+str(errors[0]))
    return report

if __name__=='__main__':
    import sys
    print(json.dumps(check(sys.argv[1]),ensure_ascii=True))
