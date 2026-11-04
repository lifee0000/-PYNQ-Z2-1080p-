"""Deterministic real-Tk acceptance for manual controls, with no board access.

Exercises the installed window, persistence, mode capability states, and a real
offline video run. Screenshots are not used as evidence of an unlocked desktop.
"""
import json
import os
from pathlib import Path
import time
from unittest.mock import patch


def check(folder):
    import gui
    from image_controls import ImageControls, load_profile, save_profile
    import av
    import numpy as np

    folder = Path(folder).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    report = dict(status='RUNNING', scope='REAL_TK_AND_REAL_OFFLINE_NO_BOARD', checks=[], no_board_connection=True)
    errors = []
    previous_path = os.environ.get('PYNQ_VIDEO_SETTINGS_PATH')
    os.environ['PYNQ_VIDEO_SETTINGS_PATH'] = str(folder / 'remembered.json')
    # Lossless input with texture, colour and several brightness levels.
    source = folder / 'controls_input.mkv'
    with av.open(str(source), 'w') as out:
        stream = out.add_stream('ffv1', rate=25)
        stream.width, stream.height, stream.pix_fmt = 320, 180, 'bgr0'
        y, x = np.indices((180, 320))
        for i in range(3):
            rgb = np.empty((180, 320, 3), np.uint8)
            rgb[:, :, 0] = 40 + (x // 2 + i * 10) % 140
            rgb[:, :, 1] = 50 + (y + x // 4) % 120
            rgb[:, :, 2] = 60 + (x // 4 + y // 3) % 100
            f = av.VideoFrame.from_ndarray(rgb, format='rgb24')
            f.pts = i
            for packet in stream.encode(f):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)

    def run(root, state):
        def tick():
            root.update()
        def until(condition, seconds=30):
            limit = time.monotonic() + seconds
            while not condition():
                tick(); time.sleep(.01)
                assert time.monotonic() < limit, 'Timed out waiting for the GUI'
            tick()
        def passed(name, **details):
            report['checks'].append(dict(name=name, **details))
        def bounds(widget, parent=root):
            return [widget.winfo_rootx()-parent.winfo_rootx(), widget.winfo_rooty()-parent.winfo_rooty(),
                    widget.winfo_width(), widget.winfo_height()]
        try:
            panel = state['image_panel']
            root.state('normal')   # the window opens maximised; the size checks need a normal one
            for size in ('1240x900', '1000x760', '980x720'):
                root.geometry(size); tick()
                targets = [*state['canvases'], state['start_button'], state['cancel_button'], panel.choice]
                def descendants(widget):
                    for child in widget.winfo_children():
                        if child.winfo_toplevel() == root and child.winfo_ismapped():
                            yield child
                            yield from descendants(child)
                # Also catch less obvious clipping of connection/quality controls.
                for widget in descendants(root):
                    x, y, w, h = bounds(widget)
                    assert x >= 0 and y >= 0 and x+w <= root.winfo_width()+1 and y+h <= root.winfo_height()+1, (size, str(widget), bounds(widget))
                geometries = [bounds(w) for w in targets]
                for x, y, w, h in geometries:
                    assert x >= 0 and y >= 0 and x+w <= root.winfo_width()+1 and y+h <= root.winfo_height()+1, (size, geometries)
                assert min(g[2] for g in geometries[:2]) >= 250
                assert min(g[3] for g in geometries[:2]) >= 120, (size, geometries)
                passed('layout_' + size, bounds=geometries)
            transport = state['quality'].get()
            panel.preset.set('自然'); panel.choose_preset()
            assert panel.settings() == ImageControls(preset='natural')
            panel.open(); tick()
            assert len(panel.scales) == 5
            for name, value in [('brightness', 12), ('denoise', 30), ('sharpen', 40), ('clarity', 20), ('color_preservation', 80)]:
                panel.scales[name].set(value); tick()
                assert getattr(panel.settings(), name) == value, (name, panel.settings())
                assert not panel.follow[name].get()
            tuned = panel.settings()
            assert state['quality'].get() == transport
            panel.persist()
            assert load_profile(folder / 'remembered.json') == tuned
            custom = folder / 'custom.json'
            with patch('image_controls_ui.filedialog.asksaveasfilename', return_value=str(custom)):
                panel.save_as()
            panel.restore()
            assert panel.settings() == ImageControls()
            with patch('image_controls_ui.filedialog.askopenfilename', return_value=str(custom)):
                panel.load()
            assert panel.settings() == tuned
            bad = folder / 'invalid.json'; bad.write_text('{"schema":99}', encoding='utf-8')
            with patch('image_controls_ui.filedialog.askopenfilename', return_value=str(bad)), patch('image_controls_ui.messagebox.showerror') as error:
                panel.load(); assert error.called
            assert panel.settings() == tuned
            passed('five_sliders_save_load_atomic_invalid_restore_and_transport_independence')

            state['mode'].set('4 锐化'); state['select_mode'](); tick()
            assert panel.scales['denoise'].instate(['disabled'])
            assert panel.scales['color_preservation'].instate(['disabled'])
            assert not panel.scales['sharpen'].instate(['disabled'])
            panel.restore(); tick()
            assert state['auto'].get() and state['mode'].get().startswith('5 ')
            panel.set_settings(tuned)
            panel.window.withdraw()
            passed('mode_capabilities_and_full_auto_restore')

            state['backend'].set('离线 CPU 参考（无需开发板）'); state['change_backend']()
            state['resolution'].set('1280 × 720（720p）')
            state['detail'].set(True)
            state['preview_focus'][:] = [.8, .7]
            with patch('gui.filedialog.askopenfilename', return_value=str(source)):
                state['select_source']()
            until(lambda: not state['start_button'].instate(['disabled']))
            state['output'].set(str(folder / 'gui_offline.mp4'))
            state['start_button'].invoke()
            until(lambda: state['display_metrics']['last_processed_frame_count'] >= 1)
            assert state['mode_choice'].instate(['disabled'])
            assert not panel.scales['clarity'].instate(['disabled'])
            # A real Tk edit during the CPU run, through the same live object
            # supplied to the FPGA path. At least the final frame must use it.
            panel.scales['clarity'].set(35); tick()
            later = panel.settings()
            assert later.clarity == 35
            for widget in descendants(root):
                x, y, w, h = bounds(widget)
                assert x >= 0 and y >= 0 and x+w <= root.winfo_width()+1 and y+h <= root.winfo_height()+1, ('running', str(widget), bounds(widget))
            until(lambda: (folder / 'gui_offline.mp4.json').is_file() and not state['is_running'](), 90)
            # Let the queued 'done' event restore disabled widgets.
            until(lambda: not state['start_button'].instate(['disabled']))
            video_report = json.loads((folder / 'gui_offline.mp4.json').read_text(encoding='utf-8'))
            assert video_report['status'] == 'PASS', video_report
            assert video_report['frames'] == 3 and 'v5' in video_report['auto_policy']
            trace = [json.loads(l) for l in (folder / 'gui_offline.mp4.frames.jsonl').read_text(encoding='utf-8').splitlines()]
            assert trace[0]['image_controls'] == tuned.to_dict()
            assert trace[-1]['image_controls'] == later.to_dict()
            assert len(video_report['image_control_changes']) == 2
            assert all(r['parameters']['sharp_q8_8'] == 410 and r['parameters']['chroma_q8'] == 205 for r in trace)
            assert state['images'][0].size == (960, 540) and state['images'][1].size == (960, 540)
            # The finished export can be opened with one click (not clicked here: it would launch a player).
            assert str(state['play_button'].cget('state')) == 'normal' and str(state['folder_button'].cget('state')) == 'normal'
            assert Path(state['finished_output'][0]) == folder / 'gui_offline.mp4'
            passed('real_gui_live_edit_to_offline_v5_processing_and_same_frame_detail', frames=3,
                   preview_size=list(state['images'][0].size), status=state['status'].get())
            panel.persist()
            assert load_profile(folder / 'remembered.json') == later
            passed('last_settings_remembered')
            report['status'] = 'PASS'
        except BaseException as exc:
            import traceback
            report.update(status='FAIL', error=str(exc), traceback=traceback.format_exc())
            errors.append(exc)
        finally:
            if state['is_running']():
                state['cancel_button'].invoke()
                until(lambda: not state['is_running']())
            root.destroy()
            (folder / 'image_controls_ui.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')

    gui._UI_CHECK_HOOK = run
    try:
        gui.main()
    finally:
        gui._UI_CHECK_HOOK = None
        if previous_path is None:
            os.environ.pop('PYNQ_VIDEO_SETTINGS_PATH', None)
        else:
            os.environ['PYNQ_VIDEO_SETTINGS_PATH'] = previous_path
    if errors:
        raise RuntimeError('Image controls GUI check failed: ' + str(errors[0]))
    return report


if __name__ == '__main__':
    import sys
    print(json.dumps(check(sys.argv[1]), ensure_ascii=False))
