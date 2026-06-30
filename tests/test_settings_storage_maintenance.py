from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.ui_services.settings_storage_service import SettingsStorageService


class SettingsStorageMaintenanceTest(unittest.TestCase):
    def test_scan_reports_temp_zero_byte_and_empty_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "downloads"
            root.mkdir()
            (root / "video.mp4.part").write_bytes(b"12345")
            (root / "empty.mp4").write_bytes(b"")
            (root / "empty_dir").mkdir()
            service = SettingsStorageService(SimpleNamespace(run_path=tmp))

            result = asyncio.run(service.scan_maintenance(str(root)))

            self.assertTrue(result.ok)
            self.assertEqual(result.temp_files, 1)
            self.assertEqual(result.temp_bytes, 5)
            self.assertEqual(result.zero_byte_files, 1)
            self.assertEqual(result.empty_dirs, 1)
            self.assertIn("临时残留 1 个", result.summary())

    def test_cleanup_deletes_only_temp_residue(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "downloads"
            root.mkdir()
            temp_file = root / "video.mp4.download"
            keep_file = root / "video.mp4"
            temp_file.write_bytes(b"123")
            keep_file.write_bytes(b"456")
            service = SettingsStorageService(SimpleNamespace(run_path=tmp))

            result = asyncio.run(service.cleanup_temp_files(str(root)))

            self.assertTrue(result.ok)
            self.assertEqual(result.deleted_files, 1)
            self.assertFalse(temp_file.exists())
            self.assertTrue(keep_file.exists())
            self.assertIn("已清理临时残留 1 个", result.summary())


if __name__ == "__main__":
    unittest.main()
