import unittest
from pathlib import Path


class WindowsPackagingTest(unittest.TestCase):
    def test_windows_packaging_scaffold_exists(self):
        self.assertTrue(Path("scripts/build_windows_release.py").is_file())
        self.assertTrue(Path("packaging/windows/douyin_monitor.spec").is_file())
        self.assertTrue(Path("packaging/windows/installer.iss").is_file())
        self.assertTrue(Path("build_windows_release.bat").is_file())

    def test_packaging_script_removes_runtime_data(self):
        text = Path("scripts/build_windows_release.py").read_text(encoding="utf-8")
        self.assertIn("cookies.secure.json", text)
        self.assertIn("douyin_content_monitor.json", text)
        self.assertIn('"data"', text)


if __name__ == "__main__":
    unittest.main()
