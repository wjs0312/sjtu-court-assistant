import tempfile
import unittest
from pathlib import Path
from app_platform import runtime_paths, prepare_data, terminal_command, font_family


class PlatformTests(unittest.TestCase):
    def test_mac_app_uses_writable_user_data_not_app_bundle(self):
        data, resources = runtime_paths('darwin', True, Path('/Applications/助手.app/Contents/MacOS/助手'),
                                        Path('/Applications/助手.app/Contents/Resources'), Path('/source'), Path('/Users/tester'))
        self.assertEqual(data, Path('/Users/tester/Library/Application Support/SJTU-Booking'))
        self.assertEqual(resources, Path('/Applications/助手.app/Contents/Resources'))

    def test_windows_portable_directory_remains_unchanged(self):
        data, resources = runtime_paths('win32', True, Path('/portable/助手.exe'),Path('/internal'),Path('/source'),Path('/users/test'))
        self.assertEqual(data,Path('/portable'))
        self.assertEqual(resources,Path('/portable'))

    def test_initial_data_copy_never_overwrites_existing_config(self):
        with tempfile.TemporaryDirectory() as folder:
            resources=Path(folder)/'resources';data=Path(folder)/'data';resources.mkdir()
            (resources/'config.portable.toml').write_text('public',encoding='utf-8')
            (resources/'venue_catalog.json').write_text('{}',encoding='utf-8')
            prepare_data(data,resources)
            self.assertEqual((data/'config.toml').read_text(),'public')
            (data/'config.toml').write_text('my settings',encoding='utf-8')
            prepare_data(data,resources)
            self.assertEqual((data/'config.toml').read_text(),'my settings')

    def test_mac_legacy_mode_opens_terminal_without_windows_flags(self):
        command, options=terminal_command(['/Applications/场地助手.app/Contents/MacOS/场地助手','--cli','check'],'darwin')
        self.assertEqual(command[:2],['osascript','-e'])
        self.assertIn('--cli check',command[2])
        self.assertEqual(options,{})

    def test_native_chinese_font(self):
        self.assertEqual(font_family('darwin'),'PingFang SC')
        self.assertEqual(font_family('win32'),'Microsoft YaHei UI')


if __name__=='__main__':unittest.main()
