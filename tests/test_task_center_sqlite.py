from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.runtime.task_center import TaskCenter
from app.core.storage.sqlite_store import SQLiteStore


class TaskCenterSQLiteTest(unittest.TestCase):
    def test_task_center_migrates_json_to_sqlite_and_mirrors_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            storage_path = config_dir / "task_records.json"
            storage_path.write_text(
                json.dumps(
                    {
                        "records": [
                            {
                                "task_id": "t1",
                                "title": "Old task",
                                "category": "测试",
                                "status": "完成",
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = SQLiteStore(str(root))

            center = TaskCenter(storage_path=str(storage_path), sqlite_store=store)

            self.assertEqual(store.task_record_count(), 1)
            self.assertEqual(center.snapshot()[0]["task_id"], "t1")

            center.start("New task")

            self.assertGreaterEqual(store.task_record_count(), 2)
            mirror = json.loads(storage_path.read_text(encoding="utf-8"))
            self.assertEqual(mirror["records"][0]["title"], "New task")
