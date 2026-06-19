from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from scripts.migrate_to_sqlite import migrate


class MigrateToSQLiteTest(unittest.TestCase):
    def test_migrate_json_runtime_data_to_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config = root / "config"
            config.mkdir()
            (config / "douyin_content_monitor.json").write_text(
                json.dumps({"accounts": [{"account_id": "a1", "homepage_url": "https://www.douyin.com/user/x"}]}),
                encoding="utf-8",
            )
            (config / "task_records.json").write_text(
                json.dumps({"records": [{"task_id": "t1", "title": "Task"}]}),
                encoding="utf-8",
            )
            (config / "parse_history.json").write_text(
                json.dumps({"records": [{"time": "2026-01-01", "success": 1, "failed": 0}]}),
                encoding="utf-8",
            )
            (config / "download_records.json").write_text(
                json.dumps({"records": [{"download_id": "d1", "url": "https://example.test/file.mp4", "save_path": "file.mp4", "status": "failed"}]}),
                encoding="utf-8",
            )

            result = migrate(root)

            self.assertEqual(result["accounts"], 1)
            self.assertEqual(result["tasks"], 1)
            self.assertEqual(result["parse_history"], 1)
            self.assertEqual(result["downloads"], 1)
