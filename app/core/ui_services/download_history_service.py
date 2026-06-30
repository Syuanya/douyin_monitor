from __future__ import annotations

import csv
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from ..runtime.operation_models import (
    OperationStatus,
    download_status_label,
    inspect_file_state,
    is_download_recoverable,
    normalize_download_status,
)
from ..runtime.task_center import classify_failure
from .common import format_bytes


class DownloadHistoryService:
    """Download history query, recovery and export workflow independent of Flet."""

    def __init__(self, app: Any):
        self.app = app

    @staticmethod
    def selected_statuses(status_filter: str) -> list[str] | None:
        if status_filter == "recoverable":
            return [OperationStatus.RECOVERABLE.value]
        if status_filter == "failed":
            return [OperationStatus.FAILED.value]
        if status_filter == "completed":
            return [OperationStatus.COMPLETED.value]
        if status_filter == "cancelled":
            return [OperationStatus.CANCELLED.value]
        if status_filter == "running":
            return [OperationStatus.RUNNING.value]
        if status_filter == "pending":
            return [OperationStatus.PENDING.value]
        if status_filter == "missing_file":
            # This is a derived UI-only state; it is filtered after query.
            return [OperationStatus.COMPLETED.value]
        return None

    def records(self, status_filter: str = "all", limit: int = 200, query: str = "", offset: int = 0) -> list[dict[str, Any]]:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None:
            return []
        query = str(query or "").strip()
        limit = max(1, int(limit or 200))
        offset = max(0, int(offset or 0))
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if status_filter == "recoverable" and recovery is not None and hasattr(recovery, "recoverable") and not query and offset == 0:
            return [self.enriched_record(record) for record in list(recovery.recoverable(limit=limit) or [])]
        fetch_limit = limit
        if status_filter in {"recoverable", "missing_file"}:
            # Derived filters may discard many rows; fetch a wider window to keep the UI useful.
            fetch_limit = max(limit * 5, 500)
        records = store.load_download_records(
            statuses=self.selected_statuses(status_filter),
            limit=fetch_limit,
            offset=offset,
            query=query,
        )
        if status_filter == "recoverable":
            records = [record for record in records if self.is_recoverable(record)]
        elif status_filter == "missing_file":
            records = [record for record in records if self.is_missing_completed_file(record)]
        return [self.enriched_record(record) for record in records[:limit]]

    def count(self, status_filter: str = "all", query: str = "") -> int:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None:
            return 0
        query = str(query or "").strip()
        if status_filter == "recoverable":
            if query:
                return len(self.records(status_filter="recoverable", limit=5000, query=query))
            recovery = getattr(self.app.services, "download_recovery_service", None)
            return len(recovery.recoverable(limit=5000)) if recovery is not None and hasattr(recovery, "recoverable") else 0
        if status_filter == "missing_file":
            return len(self.records(status_filter="missing_file", limit=5000, query=query))
        try:
            return int(store.download_record_count(self.selected_statuses(status_filter), query=query))
        except TypeError:
            # Compatibility for older store objects in tests or embedded use.
            return len(self.records(status_filter=status_filter, limit=5000, query=query))

    def counts(self, query: str = "") -> dict[str, int]:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None:
            return {"total": 0, "recoverable": 0, "failed": 0, "completed": 0, "cancelled": 0, "running": 0, "pending": 0, "failed_cancelled": 0, "missing_file": 0}
        query = str(query or "").strip()
        failed = self.count("failed", query=query)
        cancelled = self.count("cancelled", query=query)
        return {
            "total": self.count("all", query=query),
            "recoverable": self.count("recoverable", query=query),
            "failed": failed,
            "completed": self.count("completed", query=query),
            "cancelled": cancelled,
            "running": self.count("running", query=query),
            "pending": self.count("pending", query=query),
            "missing_file": self.count("missing_file", query=query),
            "failed_cancelled": failed + cancelled,
        }

    def is_recoverable(self, record: dict[str, Any]) -> bool:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        checker = getattr(recovery, "_is_recoverable", None)
        if callable(checker):
            try:
                return bool(checker(record))
            except Exception:
                return False
        return is_download_recoverable(record)

    def is_missing_completed_file(self, record: dict[str, Any]) -> bool:
        if str(record.get("status") or "") != "completed":
            return False
        return inspect_file_state(record).missing_completed

    async def recover_one(self, record: dict[str, Any], *, headers: dict[str, str] | None, proxy: str | None, resume_enabled: bool) -> dict[str, Any]:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        center = getattr(self.app.services, "task_center", None)
        if recovery is None:
            return {"success": False, "reason": "下载恢复服务不可用"}
        title = str(record.get("label") or Path(str(record.get("save_path") or "")).name or "恢复下载记录")
        task_id = ""
        if center is not None and hasattr(center, "start"):
            try:
                task_id = center.start(
                    f"恢复下载：{title}",
                    "下载恢复",
                    detail="准备恢复 1 条下载记录",
                    total=1,
                    retry_action="download_recover_one",
                    retry_payload={"download_ids": [str(record.get("download_id") or "")]},
                ) or ""
            except Exception:
                task_id = ""
        try:
            if hasattr(recovery, "recover_one_result"):
                result = await recovery.recover_one_result(record, headers=headers, proxy=proxy, resume_enabled=resume_enabled)
            else:
                ok = await recovery.recover_one(record, headers=headers, proxy=proxy, resume_enabled=resume_enabled)
                result = {"success": bool(ok), "reason": "恢复下载完成" if ok else "恢复下载失败"}
        except Exception as exc:
            result = {"success": False, "reason": str(exc) or exc.__class__.__name__}
        if center is not None and task_id:
            try:
                if result.get("success"):
                    center.progress(task_id, completed=1, success_count=1, failed_count=0)
                    center.finish(task_id, success=True, detail="恢复下载完成")
                else:
                    center.progress(task_id, completed=1, success_count=0, failed_count=1)
                    center.finish(task_id, success=False, detail=str(result.get("reason") or "恢复下载失败"))
            except Exception:
                pass
        result.setdefault("task_id", task_id)
        return result

    async def recover_all(self, *, headers: dict[str, str] | None, proxy: str | None, resume_enabled: bool, concurrency: int = 2) -> dict[str, Any]:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if recovery is None:
            return {"total": 0, "success_count": 0, "failed_count": 0, "success": False, "reason": "下载恢复服务不可用"}
        safe_concurrency = max(1, min(5, int(concurrency or 1)))
        return await recovery.recover_all(headers=headers, proxy=proxy, resume_enabled=resume_enabled, concurrency=safe_concurrency)

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
            writer.writerow(["ID", "关联任务", "类型", "标题", "状态", "文件状态", "失败分类", "已下载", "总大小", "错误", "URL", "保存路径", "创建时间", "更新时间", "完成时间"])
            for record in records:
                failure = self.failure_meta(record)
                writer.writerow(
                    [
                        record.get("download_id") or "",
                        record.get("task_id") or "",
                        record.get("kind") or "",
                        record.get("label") or "",
                        record.get("status") or "",
                        self.file_state_label(record),
                        failure.get("category") or "",
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
            pct = downloaded / total * 100 if total else 0
            return f"{format_bytes(downloaded)} / {format_bytes(total)}（{pct:.1f}%）"
        if downloaded > 0:
            return format_bytes(downloaded)
        return "-"

    @staticmethod
    def status_label(status: str) -> str:
        return download_status_label(status) or "-"

    def file_state_label(self, record: dict[str, Any]) -> str:
        return inspect_file_state(record).label

    def enriched_record(self, record: dict[str, Any]) -> dict[str, Any]:
        payload = dict(record)
        status = normalize_download_status(payload.get("status"))
        file_state = inspect_file_state(payload)
        failure = self.failure_meta(payload)
        payload["status"] = status
        payload["status_label"] = download_status_label(status)
        payload["file_state"] = file_state.key
        payload["file_state_label"] = file_state.label
        payload["is_recoverable"] = is_download_recoverable(payload)
        payload["is_missing_completed_file"] = file_state.missing_completed
        if failure:
            payload["failure_category"] = failure.get("category", "")
            payload["failure_next_step"] = failure.get("next_step", "")
        return payload

    @staticmethod
    def failure_meta(record: dict[str, Any]) -> dict[str, str]:
        error = str(record.get("error") or "")
        if not error:
            return {}
        return classify_failure(error)

    @staticmethod
    def failure_categories_text(categories: dict[str, int] | None) -> str:
        if not categories:
            return ""
        return "；失败归类：" + "，".join(f"{name} {count}" for name, count in sorted(categories.items()))

    def recovery_result_message(self, result: dict[str, Any]) -> str:
        failed = int(result.get("failed_count") or 0)
        task_hint = f"，任务ID {result.get('task_id')}" if result.get("task_id") else ""
        concurrency = int(result.get("concurrency") or 1)
        categories_text = self.failure_categories_text(result.get("failure_categories") if isinstance(result.get("failure_categories"), dict) else {})
        return f"恢复完成：总计 {result.get('total') or 0}，成功 {result.get('success_count') or 0}，失败 {failed}，并发 {concurrency}{categories_text}{task_hint}"

    def detail_lines(self, record: dict[str, Any]) -> list[str]:
        failure = self.failure_meta(record)
        lines = [
            f"ID：{record.get('download_id') or '-'}",
            f"关联任务：{record.get('task_id') or '-'}",
            f"类型：{record.get('kind') or '-'}",
            f"标题：{record.get('label') or '-'}",
            f"状态：{record.get('status') or '-'}",
            f"文件状态：{self.file_state_label(record)}",
            f"进度：{DownloadHistoryService.progress_text(record)}",
            f"URL：{record.get('url') or '-'}",
            f"路径：{record.get('save_path') or '-'}",
            f"错误：{record.get('error') or '-'}",
        ]
        if failure:
            lines.append(f"失败归类：{failure.get('category') or '-'}")
            lines.append(f"建议处理：{failure.get('next_step') or '-'}")
        lines.extend(
            [
                f"创建：{record.get('created_at') or '-'}",
                f"更新：{record.get('updated_at') or '-'}",
                f"完成：{record.get('finished_at') or '-'}",
            ]
        )
        return lines

    @staticmethod
    def location_for_path(path: str) -> str:
        return str(Path(path).parent if path and Path(path).suffix else Path(path))
