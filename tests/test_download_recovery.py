from __future__ import annotations

import unittest

from app.core.runtime.download_recovery import DOWNLOAD_STATUS_COMPLETED, DOWNLOAD_STATUS_RECOVERABLE, DownloadRecoveryService
from app.core.storage.sqlite_store import SQLiteStore


class DownloadRecoveryTest(unittest.TestCase):
    def test_download_recovery_lifecycle(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = SQLiteStore(str(tmp_path))
            service = DownloadRecoveryService(store)
            target = tmp_path / "downloads" / "video.mp4"
            target.parent.mkdir()
            part = tmp_path / "downloads" / "video.mp4.part"
            part.write_bytes(b"partial")

            download_id = service.start(url="https://example.com/video.mp4", save_path=str(target), kind="video", label="video")
            service.progress(download_id, bytes_downloaded=7, total_bytes=20)
            service.fail(download_id, "network timeout")

            record = service.get(download_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.status, DOWNLOAD_STATUS_RECOVERABLE)
            self.assertEqual(service.recoverable()[0].download_id, download_id)

            part.unlink()
            target.write_bytes(b"complete")
            service.finish(download_id)
            record = service.get(download_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.status, DOWNLOAD_STATUS_COMPLETED)

    def test_interrupted_downloads_marked_recoverable(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            store = SQLiteStore(str(tmp_path))
            service = DownloadRecoveryService(store)
            target = tmp_path / "a.bin"
            (tmp_path / "a.bin.part").write_bytes(b"x")
            download_id = service.start(url="https://example.com/a.bin", save_path=str(target))

            restarted = DownloadRecoveryService(store)
            record = restarted.get(download_id)
            self.assertIsNotNone(record)
            self.assertEqual(record.status, DOWNLOAD_STATUS_RECOVERABLE)


if __name__ == "__main__":
    unittest.main()
