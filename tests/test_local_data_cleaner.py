from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.privacy.local_data_cleaner import LocalDataCleaner


class LocalDataCleanerTest(unittest.TestCase):
    def test_dry_run_does_not_delete_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config"
            config.mkdir()
            cookie = config / "cookies.json"
            cookie.write_text("{}", encoding="utf-8")

            result = LocalDataCleaner(root).clean(dry_run=True)

            self.assertEqual(result.failed, 0)
            self.assertTrue(cookie.exists())
            self.assertIn(str(cookie.resolve()), result.paths)

    def test_clean_removes_whitelisted_runtime_files_but_not_downloads(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "config").mkdir()
            (root / "downloads").mkdir()
            settings = root / "config" / "user_settings.json"
            media = root / "downloads" / "keep.mp4"
            settings.write_text("{}", encoding="utf-8")
            media.write_text("video", encoding="utf-8")

            result = LocalDataCleaner(root).clean(dry_run=False)

            self.assertEqual(result.failed, 0)
            self.assertFalse(settings.exists())
            self.assertTrue(media.exists())

    def test_database_is_only_removed_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "data").mkdir()
            db = root / "data" / "douyin_monitor.sqlite3"
            db.write_text("db", encoding="utf-8")

            LocalDataCleaner(root).clean(dry_run=False)
            self.assertTrue(db.exists())

            LocalDataCleaner(root).clean(dry_run=False, include_database=True)
            self.assertFalse(db.exists())
