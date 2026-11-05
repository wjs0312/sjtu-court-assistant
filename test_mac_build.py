import tempfile
import unittest
from pathlib import Path, PurePosixPath
from build_macos import build_command
from package_mac_source import package_source


class MacBuildTests(unittest.TestCase):
    def test_bundle_includes_browser_and_public_defaults(self):
        command=build_command(PurePosixPath('/project'),PurePosixPath('/cache/browser'),'arm64')
        self.assertIn('--windowed',command)
        self.assertEqual(command[command.index('--target-arch')+1],'arm64')
        self.assertIn('/cache/browser:browsers',command)
        self.assertIn('/project/config.portable.toml:.',command)
        self.assertNotIn('/project/config.toml:.',command)

    def test_source_archive_does_not_include_personal_session(self):
        import zipfile
        with tempfile.TemporaryDirectory() as folder:
            archive=package_source(Path(folder))
            with zipfile.ZipFile(archive) as z:
                names=z.namelist()
                self.assertTrue(any(n.endswith('一键生成DMG.command') for n in names))
                self.assertFalse(any('/.auth/' in n or '.user-settings.json' in n for n in names))
                entry=next(e for e in z.infolist() if e.filename.endswith('.command'))
                self.assertTrue((entry.external_attr>>16)&0o111)


if __name__=='__main__':unittest.main()
