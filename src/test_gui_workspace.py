"""Workspace lookup: the development manual_tests folder and the delivered folder (输入视频 / 输出视频)."""
from pathlib import Path
from unittest import mock
import sys, tempfile, unittest
import gui


class WorkspaceTest(unittest.TestCase):
    def test_delivered_folder_is_found_from_the_exe_and_its_named_folders_are_used(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); (root/'输入视频').mkdir(); (root/'启动程序.cmd').write_text('@echo off', encoding='ascii')
            exe = root/'程序'/'PYNQVideoV4.exe'; exe.parent.mkdir(); exe.write_bytes(b'')
            with mock.patch.object(sys, 'frozen', True, create=True), mock.patch.object(sys, 'executable', str(exe)):
                workspace = gui.manual_workspace()
            self.assertEqual(workspace, root)
            self.assertTrue((root/'输出视频').is_dir() and (root/'对比截图').is_dir())
            self.assertEqual([gui.workspace_folder(workspace, k).name for k in ('inputs', 'outputs', 'comparisons')], ['输入视频', '输出视频', '对比截图'])

    def test_development_workspace_keeps_its_folder_names(self):
        with tempfile.TemporaryDirectory() as folder:
            tests = Path(folder)/'manual_tests'; tests.mkdir(); (tests/'materials.json').write_text('{}', encoding='utf-8')
            (tests/'输入视频').mkdir()
            self.assertEqual(gui.workspace_folder(tests, 'inputs'), tests/'inputs')


class WorkbenchChoicesTest(unittest.TestCase):
    def test_processing_choice_is_kept_beside_the_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            with mock.patch.dict('os.environ', {'PYNQ_VIDEO_SETTINGS_PATH': str(Path(folder) / 'profile.json')}):
                self.assertEqual(gui.load_workbench_choices(), {})
                gui.save_workbench_choice(backend='offline')
                self.assertEqual(gui.workbench_choices_path().name, 'profile.workbench.json')
                self.assertEqual(gui.load_workbench_choices(), {'backend': 'offline', 'schema': 1})
                gui.workbench_choices_path().write_text('not json', encoding='utf-8')
                self.assertEqual(gui.load_workbench_choices(), {})      # a damaged file is ignored


class LaunchPrewarmTest(unittest.TestCase):
    def test_only_interactive_windows_warm_the_board_at_launch(self):
        def check(app, state): pass
        def opted_in(app, state): pass
        opted_in.allow_launch_prewarm = True
        for hook, allowed in ((None, True), (check, False), (opted_in, True)):
            with mock.patch.object(gui, '_UI_CHECK_HOOK', hook):
                self.assertEqual(gui.launch_prewarm_allowed(), allowed)


if __name__ == '__main__':
    unittest.main()
