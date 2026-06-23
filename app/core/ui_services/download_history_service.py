from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import format_bytes


class DownloadHistoryService:
    """Download history query, recovery and export workflow independent of Flet."""

    def __init__(self, app: Any):
        self.app = app

    @staticmethod
    def selected_statuses(status_filter: str) -> list[str] | None:
        if status_filter == "recoverable":
            return ["recoverable", "failed", "cancelled", "pending", "running"]
        if status_filter == "failed":
            return ["failed"]
        if status_filter == "completed":
            return ["completed"]
        if status_filter == "cancelled":
            return ["cancelled"]
        if status_filter == "running":
            return ["running", "pending"]
        return None

    def records(self, status_filter: str = "all", limit: int = 200) -> list[dict[str, Any]]:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None:
            return []
        return store.load_download_records(statuses=self.selected_statuses(status_filter), limit=limit)

    def counts(self) -> dict[str, int]:
        store = getattr(self.app.services, "sqlite_store", None)
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if store is None:
            return {"total": 0, "recoverable": 0, "failed": 0, "completed": 0, "failed_cancelled": 0}
        failed = store.download_record_count(["failed"])
        cancelled = store.download_record_count(["cancelled"])
        return {
            "total": store.download_record_count(),
            "recoverable": len(recovery.recoverable(limit=500)) if recovery is not None else 0,
            "failed": failed,
            "completed": store.download_record_count(["completed"]),
            "failed_cancelled": failed + cancelled,
        }

    async def recover_one(self, record: dict[str, Any], *, headers: dict[str, str] | None, proxy: str | None, resume_enabled: bool) -> bool:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if recovery is None:
            return False
        return bool(await recovery.recover_one(record, headers=headers, proxy=proxy, resume_enabled=resume_enabled))

    async def recover_all(self, *, headers: dict[str, str] | None, proxy: str | None, resume_enabled: bool) -> dict[str, Any]:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if recovery is None:
            return {"total": 0, "success_count": 0, "failed_count": 0}
        return await recovery.recover_all(headers=headers, proxy=proxy, resume_enabled=resume_enabled)

    def clear_completed(self) -> int:
        store = getattr(self.app.services, "sqlite_store", None)
        return store.delete_download_records(statuses=["completed"]) if store is not None else 0

    def clear_failed_cancelled(self) -> int:
        store = getattr(self.app.services, "sqlite_store", None)
        return store.delete_download_records(statuses=["failed", "cancelled"]) if store is not None else 0

    def export_csv(self, records: list[dict[str, Any]] | None = None) -> str:
        records = records if records is not None else self.records(limit=1000)
        export_dir = os.path.join(self.app.run_path, "downloads", "download_history_exports")
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"download_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["ID", "类型", "标题", "状态", "已下载", "总大小", "错误", "URL", "保存路径", "创建时间", "更新时间", "完成时间"])
            for record in records:
                writer.writerow(
                    [
                        record.get("download_id") or "",
                        record.get("kind") or "",
                        record.get("label") or "",
                        record.get("status") or "",
                        record.get("bytes_downloaded") or 0,
                        record.get("total_bytes") or 0,
                        record.get("error") or "",
                        record.get("url") or "",
                        record.get("save_path") or "",
                        record.get("created_at") or "",
                        record.get("updated_at") or "",
                        record.get("finished_at") or "",
                    ]
                )
        return path

    @staticmethod
    def progress_text(record: dict[str, Any]) -> str:
        downloaded = int(record.get("bytes_downloaded") or 0)
        total = int(record.get("total_bytes") or 0)
        if total > 0:
            return f"{format_bytes(downloaded)} / {format_bytes(total)}"
        if downloaded > 0:
            return format_bytes(downloaded)
        return "-"

    @staticmethod
    def status_label(status: str) -> str:
        return {
            "completed": "完成",
            "failed": "失败",
            "cancelled": "已取消",
            "recoverable": "可恢复",
            "running": "运行中",
            "pending": "等待中",
        }.get(status, status or "-")

    @staticmethod
    def detail_lines(record: dict[str, Any]) -> list[str]:
        return [
            f"ID：{record.get('download_id') or '-'}",
            f"类型：{record.get('kind') or '-'}",
            f"标题：{record.get('label') or '-'}",
            f"状态：{record.get('status') or '-'}",
            f"进度：{DownloadHistoryService.progress_text(record)}",
            f"URL：{record.get('url') or '-'}",
            f"路径：{record.get('save_path') or '-'}",
            f"错误：{record.get('error') or '-'}",
            f"创建：{record.get('created_at') or '-'}",
            f"更新：{record.get('updated_at') or '-'}",
            f"完成：{record.get('finished_at') or '-'}",
        ]

    @staticmethod
    def location_for_path(path: str) -> str:
        return str(Path(path).parent if path and Path(path).suffix else Path(path))
