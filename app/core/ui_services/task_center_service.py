from __future__ import annotations

import asyncio
import json
from typing import Any

from ..runtime.operation_models import OperationStatus, task_status_key
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
        status_keys = [task_status_key(record.get("status_key") or record.get("status")) for record in records]
        return {
            "total": len(records),
            "running": len([status for status in status_keys if status == OperationStatus.RUNNING.value]),
            "waiting": len([status for status in status_keys if status in {OperationStatus.WAITING.value, OperationStatus.PENDING.value}]),
            "failed": len([status for status in status_keys if status == OperationStatus.FAILED.value]),
            "cancelled": len([status for status in status_keys if status == OperationStatus.CANCELLED.value]),
            "completed": len([status for status in status_keys if status == OperationStatus.COMPLETED.value]),
            "retryable": len([record for record in records if task_status_key(record.get("status_key") or record.get("status")) == OperationStatus.FAILED.value and record.get("retry_action")]),
            "cancelable": len([record for record in records if record.get("is_active") and record.get("cancel_action")]),
        }

    @staticmethod
    def count_summary(counts: dict[str, int]) -> str:
        return (
            f"全部 {counts['total']} / 运行 {counts['running']} / 等待 {counts['waiting']} / "
            f"完成 {counts['completed']} / 失败 {counts['failed']} / 已取消 {counts['cancelled']}"
        )

    @staticmethod
    def record_search_text(record: dict[str, Any]) -> str:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        parts = [
            record.get("task_id"),
            record.get("title"),
            record.get("category"),
            record.get("status"),
            record.get("detail"),
            record.get("retry_action"),
            json.dumps(payload, ensure_ascii=False),
        ]
        return " ".join(str(part or "") for part in parts).lower()

    @staticmethod
    def filter_records(records: list[dict[str, Any]], mode: str, query: str = "") -> list[dict[str, Any]]:
        mode = str(mode or "all")
        status_map = {
            "running": {OperationStatus.RUNNING.value},
            "failed": {OperationStatus.FAILED.value},
            "cancelled": {OperationStatus.CANCELLED.value},
            "completed": {OperationStatus.COMPLETED.value},
            "waiting": {OperationStatus.WAITING.value, OperationStatus.PENDING.value},
        }
        statuses = status_map.get(mode)
        result = [record for record in records if not statuses or task_status_key(record.get("status_key") or record.get("status")) in statuses]
        terms = [term.lower() for term in str(query or "").strip().split() if term.strip()]
        if not terms:
            return result
        return [record for record in result if all(term in TaskCenterFacadeService.record_search_text(record) for term in terms)]

    def filtered_records(self, *, limit: int = 1000, mode: str = "all", query: str = "") -> list[dict[str, Any]]:
        return self.filter_records(self.records(limit), mode, query)


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
        active_count = len([job for job in jobs if str(job.get("status") or "") in {"running", "paused", "failed"}])
        return {"total": len(jobs), "active_count": active_count, "counts": counts, "jobs": jobs}

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


    def related_download_records(self, record: dict[str, Any], limit: int = 50) -> list[dict[str, Any]]:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None or not hasattr(store, "load_download_records"):
            return []
        related: list[dict[str, Any]] = []
        seen: set[str] = set()
        task_id = str(record.get("task_id") or "")
        try:
            if task_id:
                for item in store.load_download_records(task_id=task_id, limit=limit):
                    did = str(item.get("download_id") or "")
                    if did and did in seen:
                        continue
                    seen.add(did)
                    related.append(item)
        except Exception:
            pass
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        for download_id in [str(item) for item in payload.get("download_ids", []) if item]:
            if download_id in seen:
                continue
            try:
                rows = store.load_download_records(download_id=download_id, limit=1)
            except Exception:
                rows = []
            if rows:
                seen.add(download_id)
                related.append(rows[0])
            if len(related) >= limit:
                break
        return related[: max(1, int(limit or 50))]


    async def cancel_record(self, record: dict[str, Any]) -> dict[str, Any]:
        action = str(record.get("cancel_action") or "")
        payload = record.get("cancel_payload") if isinstance(record.get("cancel_payload"), dict) else {}
        result: dict[str, Any]
        if action == "content_auto_download":
            manager = getattr(self.app.services, "douyin_content_monitor", None)
            if manager is None or not hasattr(manager, "cancel_auto_downloads"):
                return {"success": False, "reason": "内容监控自动下载服务不可用"}
            result = await manager.cancel_auto_downloads(
                str(payload.get("account_id") or ""),
                item_ids=[str(item) for item in payload.get("item_ids", []) if item],
                task_key=str(payload.get("task_key") or ""),
            )
            if int(result.get("cancelled") or 0) <= 0:
                return {"success": False, "reason": "未找到正在运行的自动下载任务", **result}
            result = {"success": True, "reason": f"已取消自动下载 {result.get('cancelled')} 个", **result}
        elif action == "batch_job":
            job_id = str(payload.get("job_id") or "")
            if not job_id:
                return {"success": False, "reason": "缺少批量任务 ID"}
            result = await self.cancel_batch_job(job_id)
        else:
            return {"success": False, "reason": "当前任务不支持从任务中心取消"}
        self._broadcast_content_monitor_update("task_cancelled", payload)
        return result

    async def retry_record(self, record: dict[str, Any]) -> dict[str, Any]:
        action = str(record.get("retry_action") or "")
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        if action == "content_download_items":
            result = await self.retry_content_download_items(payload)
            self._broadcast_content_monitor_update("task_retry", payload)
            return result
        if action == "download_recover_all":
            return await self.retry_download_recovery(payload)
        if action == "download_recover_one":
            return await self.retry_download_recovery(payload)
        return {"success": False, "reason": "当前任务不支持自动重试"}


    def _broadcast_content_monitor_update(self, event: str, payload: dict[str, Any] | None = None) -> None:
        services = getattr(self.app, "services", None)
        broadcaster = getattr(services, "broadcast_pubsub", None)
        if not callable(broadcaster):
            return
        data = {"event": event, "force": True}
        if isinstance(payload, dict):
            for key in ("account_id", "item_ids", "failed_item_ids", "task_key", "job_id"):
                if key in payload:
                    data[key] = payload.get(key)
        try:
            broadcaster("douyin_monitor_update", data)
        except Exception:
            pass

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


    async def retry_download_recovery(self, payload: dict[str, Any]) -> dict[str, Any]:
        history = getattr(self.app, "download_history_service", None)
        recovery = getattr(self.app.services, "download_recovery_service", None)
        store = getattr(self.app.services, "sqlite_store", None)
        if recovery is None or store is None:
            return {"success": False, "reason": "下载恢复服务不可用"}
        download_ids = [str(item) for item in payload.get("download_ids", []) if item]
        if not download_ids:
            return {"success": False, "reason": "缺少可恢复下载记录"}
        records: list[dict[str, Any]] = []
        for download_id in download_ids:
            try:
                row = store.get_download_record(download_id) if hasattr(store, "get_download_record") else None
            except Exception:
                row = None
            if isinstance(row, dict):
                records.append(row)
        if not records:
            return {"success": False, "reason": "下载记录不存在"}
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/"}
        settings = getattr(self.app.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        cookie = str((cookies or {}).get("douyin_cookie") or "").strip()
        if cookie:
            headers["Cookie"] = cookie
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        proxy = str(config.get("proxy_address") or "").strip() or None if config.get("enable_proxy") else None
        resume_enabled = bool(config.get("download_resume_enabled", True))
        concurrency = max(1, min(5, int(payload.get("concurrency") or 2)))
        success = failed = 0
        failures: list[dict[str, str]] = []
        failure_categories: dict[str, int] = {}
        lock = asyncio.Lock()
        semaphore = asyncio.Semaphore(concurrency)

        async def recover_record(record: dict[str, Any]) -> None:
            nonlocal success, failed
            async with semaphore:
                if hasattr(recovery, "recover_one_result"):
                    result = await recovery.recover_one_result(record, headers=headers, proxy=proxy, resume_enabled=resume_enabled)
                else:
                    ok = await recovery.recover_one(record, headers=headers, proxy=proxy, resume_enabled=resume_enabled)
                    result = {"success": bool(ok), "reason": "恢复完成" if ok else "恢复失败"}
            async with lock:
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
                    category = str(result.get("category") or classify_failure(str(result.get("reason") or "")).get("category") or "执行失败")
                    failure_categories[category] = failure_categories.get(category, 0) + 1
                    failures.append({"download_id": str(record.get("download_id") or ""), "reason": str(result.get("reason") or "恢复失败"), "category": category})

        await asyncio.gather(*(recover_record(record) for record in records))
        return {"success": failed == 0, "success_count": success, "failed_count": failed, "failures": failures, "failure_categories": failure_categories, "concurrency": concurrency}

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
        requested_ids = list(dict.fromkeys(item_ids))
        retryable_only = bool(payload.get("retryable_only", True))
        item_by_id = {str(getattr(item, "item_id", "") or ""): item for item in getattr(account, "items", []) or []}
        skipped_ids: list[str] = []
        unique_ids: list[str] = []
        for item_id in requested_ids:
            item = item_by_id.get(item_id)
            if retryable_only and item is not None and str(getattr(item, "status", "") or "") == "download_failed" and not bool(getattr(item, "failure_retryable", True)):
                skipped_ids.append(item_id)
                continue
            unique_ids.append(item_id)
        if not unique_ids:
            return {"success": True, "reason": "没有可重试的失败作品", "success_count": 0, "failed_count": 0, "skipped_count": len(skipped_ids)}
        failed_item_ids: list[str] = []
        task_id = (
            center.start(
                f"重试失败下载：{name}",
                "内容监控下载",
                total=len(unique_ids),
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids, "retryable_only": retryable_only},
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
        reason = f"重试完成：成功 {success}，失败 {failed}"
        if skipped_ids:
            reason += f"；跳过不可重试 {len(skipped_ids)} 个"
        return {"success": failed == 0, "reason": reason, "success_count": success, "failed_count": failed, "skipped_count": len(skipped_ids)}

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
    def failure_category_summary_from_reasons(reasons: dict[str, Any]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for reason in (reasons or {}).values():
            category = classify_failure(str(reason or "")).get("category") or "执行失败"
            summary[category] = summary.get(category, 0) + 1
        return summary

    @staticmethod
    def failure_category_text(summary: dict[str, int]) -> str:
        if not summary:
            return ""
        return "，".join(f"{name} {count}" for name, count in sorted(summary.items()))

    def related_download_summary(self, record: dict[str, Any]) -> dict[str, Any]:
        records = self.related_download_records(record, limit=500)
        status_counts: dict[str, int] = {}
        missing = recoverable = 0
        failures: dict[str, int] = {}
        try:
            from .download_history_service import DownloadHistoryService

            history = DownloadHistoryService(self.app)
            for item in records:
                status = str(item.get("status") or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
                if history.is_missing_completed_file(item):
                    missing += 1
                if history.is_recoverable(item):
                    recoverable += 1
                meta = history.failure_meta(item)
                if meta:
                    category = str(meta.get("category") or "执行失败")
                    failures[category] = failures.get(category, 0) + 1
        except Exception:
            for item in records:
                status = str(item.get("status") or "unknown")
                status_counts[status] = status_counts.get(status, 0) + 1
        return {"total": len(records), "status_counts": status_counts, "missing_file": missing, "recoverable": recoverable, "failure_categories": failures}

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
