from __future__ import annotations

import asyncio
from typing import Any

from ..runtime.task_center import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING,
    classify_failure,
)


class TaskCenterFacadeService:
    """UI-independent task-center workflow and state projection."""

    def __init__(self, app: Any):
        self.app = app

    def records(self, limit: int = 500) -> list[dict[str, Any]]:
        center = getattr(self.app.services, "task_center", None)
        if center is None or not hasattr(center, "snapshot"):
            return []
        try:
            return list(center.snapshot(limit) or [])
        except Exception:
            return []

    @staticmethod
    def counts(records: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(records),
            "running": len([record for record in records if record.get("status") == TASK_STATUS_RUNNING]),
            "waiting": len([record for record in records if record.get("status") == TASK_STATUS_WAITING]),
            "failed": len([record for record in records if record.get("status") == TASK_STATUS_FAILED]),
            "cancelled": len([record for record in records if record.get("status") == TASK_STATUS_CANCELLED]),
            "completed": len([record for record in records if record.get("status") == TASK_STATUS_COMPLETED]),
            "retryable": len([record for record in records if record.get("status") == TASK_STATUS_FAILED and record.get("retry_action")]),
        }

    @staticmethod
    def count_summary(counts: dict[str, int]) -> str:
        return (
            f"全部 {counts['total']} / 运行 {counts['running']} / 等待 {counts['waiting']} / "
            f"完成 {counts['completed']} / 失败 {counts['failed']} / 已取消 {counts['cancelled']}"
        )

    @staticmethod
    def filter_records(records: list[dict[str, Any]], mode: str) -> list[dict[str, Any]]:
        mode = str(mode or "all")
        status_map = {
            "running": TASK_STATUS_RUNNING,
            "failed": TASK_STATUS_FAILED,
            "cancelled": TASK_STATUS_CANCELLED,
            "completed": TASK_STATUS_COMPLETED,
            "waiting": TASK_STATUS_WAITING,
        }
        status = status_map.get(mode)
        if not status:
            return records
        return [record for record in records if record.get("status") == status]


    def batch_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        store = getattr(self.app.services, "batch_job_store", None)
        if store is None or not hasattr(store, "snapshot"):
            return []
        try:
            return list(store.snapshot(limit=limit) or [])
        except Exception:
            return []

    def batch_jobs_summary(self) -> dict[str, Any]:
        jobs = self.batch_jobs(100)
        counts: dict[str, int] = {}
        for job in jobs:
            status = str(job.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {"total": len(jobs), "counts": counts, "jobs": jobs}

    def batch_job_detail(self, job_id: str) -> dict[str, Any]:
        store = getattr(self.app.services, "batch_job_store", None)
        if store is None or not hasattr(store, "detail"):
            return {}
        try:
            return dict(store.detail(job_id) or {})
        except Exception:
            return {}

    async def pause_batch_job(self, job_id: str) -> dict[str, Any]:
        store = getattr(self.app.services, "batch_job_store", None)
        if store is None or not hasattr(store, "pause"):
            return {"success": False, "reason": "批量任务存储不可用"}
        store.pause(job_id)
        return {"success": True, "reason": "批量任务已暂停"}

    async def resume_batch_job(self, job_id: str) -> dict[str, Any]:
        store = getattr(self.app.services, "batch_job_store", None)
        if store is None or not hasattr(store, "resume"):
            return {"success": False, "reason": "批量任务存储不可用"}
        detail = self.batch_job_detail(job_id)
        payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
        account_id = str(payload.get("account_id") or "")
        item_ids = [str(item) for item in detail.get("remaining_ids", []) if item] or [str(item) for item in payload.get("item_ids", []) if item]
        store.resume(job_id)
        if account_id and item_ids:
            manager = getattr(self.app.services, "douyin_content_monitor", None)
            if manager is not None and hasattr(manager, "download_items_batch"):
                result = await manager.download_items_batch(account_id, item_ids, title_prefix="恢复批量下载")
                return {"success": bool(result.get("success")), "reason": str(result.get("reason") or "已恢复批量任务"), **result}
        return {"success": True, "reason": "批量任务已恢复为运行状态；缺少账号或作品信息时不会自动重新入队"}

    async def cancel_batch_job(self, job_id: str) -> dict[str, Any]:
        store = getattr(self.app.services, "batch_job_store", None)
        if store is None or not hasattr(store, "cancel"):
            return {"success": False, "reason": "批量任务存储不可用"}
        store.cancel(job_id, "用户在任务中心取消")
        return {"success": True, "reason": "批量任务已取消"}

    def queue_snapshot(self) -> dict[str, Any]:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return {}
        try:
            snapshot = queue.snapshot()
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            return {}

    def queue_is_paused(self) -> bool:
        queue = getattr(self.app.services, "media_task_queue", None)
        return bool(queue.is_paused()) if queue is not None and hasattr(queue, "is_paused") else False

    def queue_has_active_downloads(self) -> bool:
        snapshot = self.queue_snapshot()
        global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
        if int(global_state.get("inflight", 0) or 0) > 0:
            return True
        for kind, stats in snapshot.items() if isinstance(snapshot, dict) else []:
            if kind == "__global__" or not isinstance(stats, dict):
                continue
            if int(stats.get("running", 0) or 0) > 0 or int(stats.get("waiting", 0) or 0) > 0:
                return True
        return False

    def queue_summary(self) -> dict[str, Any]:
        snapshot = self.queue_snapshot()
        if not snapshot:
            return {"available": False}
        global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
        running = waiting = completed = failed = 0
        for kind, stats in snapshot.items() if isinstance(snapshot, dict) else []:
            if kind == "__global__" or not isinstance(stats, dict):
                continue
            running += int(stats.get("running", 0) or 0)
            waiting += int(stats.get("waiting", 0) or 0)
            completed += int(stats.get("completed", 0) or 0)
            failed += int(stats.get("failed", 0) or 0)
        running_labels = [str(label) for label in global_state.get("running_labels", []) if label]
        waiting_labels = [str(label) for label in global_state.get("waiting_labels", []) if label]
        details = [
            f"并发上限 {global_state.get('limit', 0) or 0}",
            f"运行 {running}",
            f"等待 {waiting}",
            f"完成 {completed}",
            f"失败 {failed}",
        ]
        if running_labels:
            details.append("当前：" + "、".join(running_labels[:2]))
        if waiting_labels:
            details.append("等待：" + "、".join(waiting_labels[:2]))
        return {
            "available": True,
            "paused": bool(global_state.get("paused")),
            "status_text": "已暂停" if bool(global_state.get("paused")) else "运行中",
            "details": " / ".join(details),
            "running_labels": running_labels,
            "waiting_labels": waiting_labels,
        }

    async def retry_record(self, record: dict[str, Any]) -> dict[str, Any]:
        action = str(record.get("retry_action") or "")
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        if action == "content_download_items":
            return await self.retry_content_download_items(payload)
        return {"success": False, "reason": "当前任务不支持自动重试"}

    async def retry_all_failed(self, delay_seconds: float = 0.1) -> dict[str, int]:
        retryable = [record for record in self.records(500) if record.get("status") == TASK_STATUS_FAILED and record.get("retry_action")]
        success_tasks = failed_tasks = 0
        for record in retryable:
            try:
                result = await self.retry_record(record)
                if result.get("success"):
                    success_tasks += 1
                else:
                    failed_tasks += 1
            except Exception:
                failed_tasks += 1
            if delay_seconds > 0:
                await asyncio.sleep(delay_seconds)
        return {"total": len(retryable), "success_tasks": success_tasks, "failed_tasks": failed_tasks}

    async def retry_content_download_items(self, payload: dict[str, Any]) -> dict[str, Any]:
        manager = getattr(self.app.services, "douyin_content_monitor", None)
        center = getattr(self.app.services, "task_center", None)
        account_id = str(payload.get("account_id") or "")
        item_ids = self.payload_retry_item_ids(payload)
        if manager is None or not account_id or not item_ids:
            return {"success": False, "reason": "重试信息不完整"}
        account = manager.find_account(account_id)
        if account is None:
            return {"success": False, "reason": "重试账号不存在"}
        name = account.display_name or account.douyin_nickname or account.account_id
        unique_ids = list(dict.fromkeys(item_ids))
        failed_item_ids: list[str] = []
        task_id = (
            center.start(
                f"重试失败下载：{name}",
                "内容监控下载",
                total=len(unique_ids),
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids},
            )
            if center is not None
            else None
        )
        success = failed = 0
        try:
            for index, item_id in enumerate(unique_ids, start=1):
                try:
                    result = await manager.download_item(account_id, item_id)
                except asyncio.CancelledError:
                    if center is not None and task_id and hasattr(center, "cancel"):
                        center.cancel(task_id, f"重试已取消：成功 {success}，失败 {failed}")
                    return {"success": False, "reason": "重试已取消", "success_count": success, "failed_count": failed}
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
                    failed_item_ids.append(item_id)
                if center is not None and task_id:
                    center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"重试进度：{index}/{len(unique_ids)}，成功 {success}，失败 {failed}",
                        retry_payload={
                            "account_id": account_id,
                            "item_ids": failed_item_ids or unique_ids,
                            "all_item_ids": unique_ids,
                            "failed_item_ids": failed_item_ids,
                        },
                    )
        except Exception as exc:
            if center is not None and task_id:
                center.finish(task_id, success=False, detail=f"重试失败：{exc}")
            return {"success": False, "reason": str(exc), "success_count": success, "failed_count": failed}
        if center is not None and task_id:
            center.finish(task_id, success=failed == 0, detail=f"重试完成：成功 {success}，失败 {failed}")
        return {"success": failed == 0, "success_count": success, "failed_count": failed}

    @staticmethod
    def payload_retry_item_ids(payload: dict[str, Any]) -> list[str]:
        failed_ids = [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]
        if failed_ids:
            return failed_ids
        return [str(item_id) for item_id in payload.get("item_ids", []) if item_id]

    @staticmethod
    def retry_failed_ids(record: dict[str, Any]) -> list[str]:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        return [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]

    @staticmethod
    def task_detail_lines(record: dict[str, Any]) -> list[str]:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        failure = classify_failure(str(record.get("detail") or "")) if record.get("status") == TASK_STATUS_FAILED else {}
        failed_ids = [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]
        lines = [
            f"标题：{record.get('title') or '-'}",
            f"类型：{record.get('category') or '-'}",
            f"状态：{record.get('status') or '-'}",
            f"进度：{record.get('completed') or 0}/{record.get('total') or 0}",
            f"成功：{record.get('success_count') or 0}",
            f"失败：{record.get('failed_count') or 0}",
            f"开始：{record.get('started_at') or '-'}",
            f"更新：{record.get('updated_at') or '-'}",
            f"结束：{record.get('finished_at') or '-'}",
            f"说明：{record.get('detail') or '-'}",
        ]
        if failure:
            lines.append(f"失败归类：{failure.get('category')}")
            lines.append(f"建议处理：{failure.get('next_step')}")
        if failed_ids:
            lines.append("失败作品ID：")
            lines.extend(f"  {item_id}" for item_id in failed_ids[:200])
        return lines
