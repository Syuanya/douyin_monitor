from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from app.core.storage.sqlite_store import SCHEMA_VERSION, SQLiteStore


class SQLiteStoreTest(unittest.TestCase):
    def test_sqlite_store_initializes_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)

            store.ensure_schema()

            self.assertTrue(store.path.exists())
            self.assertEqual(store.get_metadata("schema_version"), str(SCHEMA_VERSION))

    def test_sqlite_store_persists_task_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            records = [{"task_id": "t1", "title": "Task", "status": "运行中"}]

            store.save_task_records(records)

            self.assertEqual(store.task_record_count(), 1)
            self.assertEqual(store.load_task_records(), records)

    def test_sqlite_store_persists_parse_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            records = [{"time": "2026-01-01 00:00:00", "success": 1, "failed": 0}]

            store.save_parse_history(records)

            self.assertEqual(store.parse_history_count(), 1)
            loaded = store.load_parse_history()
            self.assertEqual(loaded[0]["success"], 1)
            self.assertTrue(loaded[0]["history_id"])

    def test_sqlite_store_persists_download_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            download_id = store.upsert_download_record(
                {
                    "url": "https://example.test/file.mp4",
                    "save_path": str(temp_dir) + "/file.mp4",
                    "kind": "test",
                    "status": "pending",
                }
            )

            store.update_download_record(download_id, status="completed")

            self.assertEqual(store.download_record_count(["completed"]), 1)
            self.assertEqual(store.load_download_records(download_id=download_id)[0]["status"], "completed")

    def test_sqlite_store_marks_interrupted_downloads_recoverable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            download_id = store.upsert_download_record(
                {
                    "url": "https://example.test/file.mp4",
                    "save_path": str(temp_dir) + "/file.mp4",
                    "kind": "test",
                    "status": "running",
                }
            )

            changed = store.mark_interrupted_downloads_recoverable()

            self.assertEqual(changed, 1)
            self.assertEqual(store.get_download_record(download_id)["status"], "recoverable")

    def test_sqlite_store_download_pagination_cleanup_and_backup(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            for index in range(3):
                store.upsert_download_record(
                    {
                        "download_id": f"d{index}",
                        "url": f"https://example.test/{index}.mp4",
                        "save_path": str(Path(temp_dir) / f"{index}.mp4"),
                        "kind": "test",
                        "label": f"video-{index}",
                        "status": "completed" if index < 2 else "failed",
                    }
                )

            self.assertEqual(len(store.load_download_records(limit=2, offset=1)), 2)
            self.assertEqual(len(store.load_download_records(query="video-1")), 1)
            backup = store.backup_database(Path(temp_dir) / "backups")
            self.assertTrue(Path(backup).exists())
            deleted = store.delete_download_records(statuses=["completed"])
            self.assertEqual(deleted, 2)
            self.assertEqual(store.download_record_count(), 1)
