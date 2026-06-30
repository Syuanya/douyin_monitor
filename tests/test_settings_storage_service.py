import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.ui_services.settings_storage_service import SettingsStorageService


class SettingsStorageServiceTest(unittest.TestCase):
    def test_inspect_reports_writable_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = SettingsStorageService(SimpleNamespace(run_path=tmp))
            result = asyncio.run(service.inspect(str(Path(tmp) / "downloads")))
            self.assertTrue(result.ok)
            self.assertTrue(result.writable)
            self.assertTrue(result.exists)
            self.assertIsNotNone(result.free_gb)
            self.assertIn("存储目录可用", result.summary())

    def test_blank_path_uses_default_download_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            service = SettingsStorageService(SimpleNamespace(run_path=tmp))
            result = asyncio.run(service.inspect(""))
            self.assertTrue(result.ok)
            self.assertIn("douyin_content", result.path)


if __name__ == "__main__":
    unittest.main()
