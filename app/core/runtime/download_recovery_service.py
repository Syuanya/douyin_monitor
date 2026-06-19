from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Any


RECOVERABLE_STATUSES = ["pending", "running", "recoverable", "failed", "cancelled"]


class DownloadRecoveryService:
    """Persistent download record and recovery facade."""

    def __init__(self, sqlite_store: Any):
        self.sqlite_store = sqlite_store
        self._last_progress_write: dict[str, float] = {}

    def initialize_recovery_state(self) -> int:
        marker = getattr(self.sqlite_store, "mark_interrupted_downloads_recoverable", None)
        if not callable(marker):
            return 0
        return int(marker())

    def start(self, *, url: str, save_path: str, kind: str = "", label: str = "", task_id: str = "", payload: dict[str, Any] | None = None) -> str:
        part_path = str(save_path or "") + ".part"
        bytes_downloaded = self._file_size(part_path)
        data = dict(payload or {})
        data.update(
            {
                "url": str(url or ""),
                "save_path": str(save_path or ""),
                "kind": str(kind or ""),
                "label": str(label or ""),
                "task_id": str(task_id or ""),
                "status": "running",
                "bytes_downloaded": bytes_downloaded,
                "total_bytes": int(data.get("total_bytes") or 0),
                "error": "",
                "finished_at": "",
            }
        )
        return self.sqlite_store.upsert_download_record(
            data
        )

    def mark_completed(self, download_id: str) -> None:
        record = self.sqlite_store.get_download_record(download_id) if hasattr(self.sqlite_store, "get_download_record") else None
        save_path = str((record or {}).get("save_path") or "")
        final_size = self._file_size(save_path)
        self.sqlite_store.update_download_record(
            download_id,
            status="completed",
            error="",
            bytes_downloaded=final_size,
            total_bytes=final_size,
            finished_at=self._now(),
        )

    def mark_failed(self, download_id: str, error: str) -> None:
        self.sqlite_store.update_download_record(download_id, status="failed", error=str(error or ""))

    def mark_cancelled(self, download_id: str) -> None:
        self.sqlite_store.update_download_record(download_id, status="cancelled", error="cancelled")

    def mark_progress(self, download_id: str, bytes_downloaded: int, total_bytes: int = 0) -> None:
        if not download_id:
            return
        now = time.monotonic()
        last = self._last_progress_write.get(download_id, 0.0)
        if now - last < 1.0:
            return
        self._last_progress_write[download_id] = now
        self.sqlite_store.update_download_record(
            download_id,
            status="running",
            bytes_downloaded=max(0, int(bytes_downloaded or 0)),
            total_bytes=max(0, int(total_bytes or 0)),
            error="",
            finished_at="",
        )

    def recoverable(self, limit: int = 100) -> list[dict[str, Any]]:
        records = self.sqlite_store.load_download_records(statuses=RECOVERABLE_STATUSES, limit=limit)
        return [record for record in records if self._is_recoverable(record)]

    async def recover_one(
        self,
        record: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: Any = 180.0,
        proxy: str | None = None,
        resume_enabled: bool = True,
    ) -> bool:
        from ..media.resumable_download import download_http_file

        download_id = str(record.get("download_id") or "")
        url = str(record.get("url") or "")
        save_path = str(record.get("save_path") or "")
        if not download_id or not url or not save_path:
            return False
        self.sqlite_store.update_download_record(download_id, status="running", error="")
        try:
            await download_http_file(
                url,
                save_path,
                headers=headers,
                timeout=timeout,
                proxy=proxy,
                progress_callback=lambda downloaded, total: self.mark_progress(download_id, downloaded, total),
                resume_enabled=resume_enabled,
            )
            self.mark_completed(download_id)
            return True
        except Exception as exc:
            self.mark_failed(download_id, str(exc))
            return False

    async def recover_all(
        self,
        *,
        limit: int = 100,
        headers: dict[str, str] | None = None,
        timeout: Any = 180.0,
        proxy: str | None = None,
        resume_enabled: bool = True,
    ) -> dict[str, Any]:
        records = self.recoverable(limit=limit)
        success_count = 0
        failed_count = 0
        for record in records:
            ok = await self.recover_one(
                record,
                headers=headers,
                timeout=timeout,
                proxy=proxy,
                resume_enabled=resume_enabled,
            )
            if ok:
                success_count += 1
            else:
                failed_count += 1
        return {
            "total": len(records),
            "success_count": success_count,
            "failed_count": failed_count,
            "success": failed_count == 0,
        }

    @staticmethod
    def _is_recoverable(record: dict[str, Any]) -> bool:
        save_path = str(record.get("save_path") or "")
        if not save_path:
            return False
        if os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
            return False
        part_path = save_path + ".part"
        return os.path.exists(part_path) or bool(record.get("url"))

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return os.path.getsize(path) if path and os.path.isfile(path) else 0
        except OSError:
            return 0

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")
