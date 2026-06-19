from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.runtime.download_recovery_service import DownloadRecoveryService
from app.core.storage.sqlite_store import SQLiteStore


class DownloadRecoveryServiceTest(unittest.TestCase):
    def test_recoverable_filters_existing_completed_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "file.mp4"
            store = SQLiteStore(temp_dir)
            service = DownloadRecoveryService(store)
            service.start(url="https://example.test/file.mp4", save_path=str(path), kind="test")

            self.assertEqual(len(service.recoverable()), 1)

            path.write_bytes(b"done")

            self.assertEqual(service.recoverable(), [])

    def test_recovery_service_records_progress_and_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "file.mp4"
            store = SQLiteStore(temp_dir)
            service = DownloadRecoveryService(store)
            download_id = service.start(url="https://example.test/file.mp4", save_path=str(path), kind="test")

            service.mark_progress(download_id, 10, 100)
            record = store.get_download_record(download_id)
            self.assertEqual(record["bytes_downloaded"], 10)
            self.assertEqual(record["total_bytes"], 100)

            path.write_bytes(b"finished")
            service.mark_completed(download_id)
            record = store.get_download_record(download_id)
            self.assertEqual(record["status"], "completed")
            self.assertEqual(record["bytes_downloaded"], len(b"finished"))
            self.assertTrue(record["finished_at"])

    def test_initialize_recovery_state_marks_inflight_records(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = SQLiteStore(temp_dir)
            store.upsert_download_record(
                {
                    "url": "https://example.test/file.mp4",
                    "save_path": str(Path(temp_dir) / "file.mp4"),
                    "status": "running",
                }
            )
            service = DownloadRecoveryService(store)

            changed = service.initialize_recovery_state()

            self.assertEqual(changed, 1)
            self.assertEqual(service.recoverable()[0]["status"], "recoverable")
