from __future__ import annotations

import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


DOWNLOAD_STATUS_PENDING = "pending"
DOWNLOAD_STATUS_RUNNING = "running"
DOWNLOAD_STATUS_COMPLETED = "completed"
DOWNLOAD_STATUS_FAILED = "failed"
DOWNLOAD_STATUS_CANCELLED = "cancelled"
DOWNLOAD_STATUS_RECOVERABLE = "recoverable"


@dataclass(slots=True)
class DownloadRecord:
    download_id: str
    url: str
    save_path: str
    kind: str = "media"
    label: str = ""
    status: str = DOWNLOAD_STATUS_PENDING
    bytes_downloaded: int = 0
    total_bytes: int = 0
    error: str = ""
    task_id: str = ""
    retry_payload: dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""
    finished_at: str = ""


class DownloadRecoveryService:
    """Persist download attempts so interrupted .part files are recoverable.

    The service deliberately does not spawn network work by itself. It records
    enough state for UI/task-center retry flows and for startup health checks to
    surface recoverable downloads after an application crash or forced exit.
    """

    def __init__(self, sqlite_store: Any | None = None, *, max_records: int = 1000):
        self.sqlite_store = sqlite_store
        self.max_records = max(50, int(max_records or 1000))
        self._mark_interrupted_as_recoverable()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def start(
        self,
        *,
        url: str,
        save_path: str,
        kind: str = "media",
        label: str = "",
        task_id: str = "",
        retry_payload: dict[str, Any] | None = None,
    ) -> str:
        now = self._now()
        download_id = uuid.uuid5(uuid.NAMESPACE_URL, f"{url}\n{save_path}").hex
        part_size = self._part_size(save_path)
        record = DownloadRecord(
            download_id=download_id,
            url=str(url or ""),
            save_path=str(save_path or ""),
            kind=str(kind or "media"),
            label=str(label or os.path.basename(str(save_path or "")) or "download"),
            status=DOWNLOAD_STATUS_RUNNING,
            bytes_downloaded=part_size,
            task_id=str(task_id or ""),
            retry_payload=dict(retry_payload or {}),
            created_at=now,
            updated_at=now,
        )
        self._save_record(record)
        return download_id

    def progress(self, download_id: str, *, bytes_downloaded: int = 0, total_bytes: int = 0) -> None:
        record = self.get(download_id)
        if record is None:
            return
        record.status = DOWNLOAD_STATUS_RUNNING
        record.bytes_downloaded = max(0, int(bytes_downloaded or 0))
        record.total_bytes = max(0, int(total_bytes or 0))
        record.updated_at = self._now()
        self._save_record(record)

    def finish(self, download_id: str) -> None:
        record = self.get(download_id)
        if record is None:
            return
        now = self._now()
        final_size = self._file_size(record.save_path)
        record.status = DOWNLOAD_STATUS_COMPLETED
        record.bytes_downloaded = final_size or record.bytes_downloaded
        record.total_bytes = final_size or record.total_bytes
        record.error = ""
        record.updated_at = now
        record.finished_at = now
        self._save_record(record)

    def fail(self, download_id: str, error: str, *, recoverable: bool = True) -> None:
        record = self.get(download_id)
        if record is None:
            return
        now = self._now()
        part_size = self._part_size(record.save_path)
        record.status = DOWNLOAD_STATUS_RECOVERABLE if recoverable and part_size > 0 else DOWNLOAD_STATUS_FAILED
        record.bytes_downloaded = part_size or record.bytes_downloaded
        record.error = str(error or "download failed")
        record.updated_at = now
        record.finished_at = now if record.status == DOWNLOAD_STATUS_FAILED else ""
        self._save_record(record)

    def cancel(self, download_id: str) -> None:
        record = self.get(download_id)
        if record is None:
            return
        record.status = DOWNLOAD_STATUS_RECOVERABLE if self._part_size(record.save_path) > 0 else DOWNLOAD_STATUS_CANCELLED
        record.updated_at = self._now()
        self._save_record(record)

    def get(self, download_id: str) -> DownloadRecord | None:
        store = self.sqlite_store
        if store is None:
            return None
        try:
            raw = store.get_download_record(str(download_id or ""))
        except Exception:
            return None
        return self._from_dict(raw) if isinstance(raw, dict) else None

    def recoverable(self, limit: int = 100) -> list[DownloadRecord]:
        store = self.sqlite_store
        if store is None:
            return []
        try:
            rows = store.load_download_records(statuses=[DOWNLOAD_STATUS_RECOVERABLE, DOWNLOAD_STATUS_RUNNING, DOWNLOAD_STATUS_PENDING], limit=limit)
        except Exception:
            return []
        records = [self._from_dict(row) for row in rows if isinstance(row, dict)]
        return [record for record in records if record is not None and self._part_size(record.save_path) > 0]

    def _mark_interrupted_as_recoverable(self) -> None:
        store = self.sqlite_store
        if store is None:
            return
        try:
            store.mark_interrupted_downloads_recoverable()
        except Exception:
            return

    def _save_record(self, record: DownloadRecord) -> None:
        store = self.sqlite_store
        if store is None:
            return
        try:
            payload = asdict(record)
            saver = getattr(store, "save_download_record", None)
            if callable(saver):
                saver(payload, max_records=self.max_records)
                return
            upsert = getattr(store, "upsert_download_record", None)
            if callable(upsert):
                upsert(payload)
        except Exception:
            return

    @classmethod
    def _from_dict(cls, raw: dict[str, Any]) -> DownloadRecord | None:
        try:
            values = {field_name: raw.get(field_name) for field_name in DownloadRecord.__dataclass_fields__}
            values["download_id"] = str(values.get("download_id") or uuid.uuid4().hex)
            values["url"] = str(values.get("url") or "")
            values["save_path"] = str(values.get("save_path") or "")
            values["retry_payload"] = values.get("retry_payload") if isinstance(values.get("retry_payload"), dict) else {}
            for key in ("bytes_downloaded", "total_bytes"):
                try:
                    values[key] = max(0, int(values.get(key) or 0))
                except (TypeError, ValueError):
                    values[key] = 0
            return DownloadRecord(**values)
        except Exception:
            return None

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return os.path.getsize(path) if os.path.isfile(path) else 0
        except OSError:
            return 0

    @classmethod
    def _part_size(cls, path: str) -> int:
        return cls._file_size(str(path or "") + ".part")
