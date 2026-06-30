from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime
from typing import Any

from ..errors import classify_failure
from .operation_models import (
    OperationStatus,
    RECOVERABLE_DOWNLOAD_STATUS_KEYS,
    inspect_file_state,
    is_download_recoverable,
    normalize_download_status,
)


RECOVERABLE_STATUSES = sorted(RECOVERABLE_DOWNLOAD_STATUS_KEYS)


class DownloadRecoveryService:
    """Persistent download record and recovery facade.

    The service keeps download history records tied to TaskCenter records where
    possible and projects bulk recovery back into TaskCenter as a visible task.
    Bulk recovery is bounded-concurrent and reports failure categories back to
    the task center so users can see what to fix instead of only seeing counts.
    """

    def __init__(self, sqlite_store: Any, task_center: Any | None = None):
        self.sqlite_store = sqlite_store
        self.task_center = task_center
        self._last_progress_write: dict[str, float] = {}

    def initialize_recovery_state(self) -> int:
        marker = getattr(self.sqlite_store, "mark_interrupted_downloads_recoverable", None)
        if not callable(marker):
            return 0
        return int(marker())

    def start(
        self,
        *,
        url: str,
        save_path: str,
        kind: str = "",
        label: str = "",
        task_id: str = "",
        payload: dict[str, Any] | None = None,
    ) -> str:
        if not task_id:
            task_id = self._current_media_task_id()
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
                "status": OperationStatus.RUNNING.value,
                "bytes_downloaded": bytes_downloaded,
                "total_bytes": int(data.get("total_bytes") or 0),
                "error": "",
                "finished_at": "",
            }
        )
        return self.sqlite_store.upsert_download_record(data)

    def mark_completed(self, download_id: str) -> None:
        record = self.sqlite_store.get_download_record(download_id) if hasattr(self.sqlite_store, "get_download_record") else None
        save_path = str((record or {}).get("save_path") or "")
        final_size = self._file_size(save_path)
        self.sqlite_store.update_download_record(
            download_id,
            status=OperationStatus.COMPLETED.value,
            error="",
            bytes_downloaded=final_size,
            total_bytes=final_size,
            finished_at=self._now(),
        )

    def mark_failed(self, download_id: str, error: str) -> None:
        self.sqlite_store.update_download_record(download_id, status=OperationStatus.FAILED.value, error=str(error or ""), finished_at=self._now())

    def mark_cancelled(self, download_id: str) -> None:
        self.sqlite_store.update_download_record(download_id, status=OperationStatus.CANCELLED.value, error="cancelled", finished_at=self._now())

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
        result = await self.recover_one_result(
            record,
            headers=headers,
            timeout=timeout,
            proxy=proxy,
            resume_enabled=resume_enabled,
        )
        return bool(result.get("success"))

    async def recover_one_result(
        self,
        record: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        timeout: Any = 180.0,
        proxy: str | None = None,
        resume_enabled: bool = True,
    ) -> dict[str, Any]:
        from ..media.resumable_download import download_http_file

        download_id = str(record.get("download_id") or "")
        url = str(record.get("url") or "")
        save_path = str(record.get("save_path") or "")
        if not download_id:
            return self._failure_result("下载记录缺少 ID", "")
        if not url:
            return self._failure_result("下载记录缺少 URL，无法恢复", download_id)
        if not save_path:
            return self._failure_result("下载记录缺少保存路径，无法恢复", download_id)
        if not self._is_recoverable(record):
            return self._failure_result("该记录当前不可恢复：本地文件已存在或缺少可恢复信息", download_id)
        self.sqlite_store.update_download_record(download_id, status=OperationStatus.RUNNING.value, error="", finished_at="")
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
            return {"success": True, "reason": "恢复下载完成", "download_id": download_id, "category": "恢复完成", "next_step": ""}
        except asyncio.CancelledError:
            self.mark_cancelled(download_id)
            raise
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            self.mark_failed(download_id, reason)
            return self._failure_result(reason, download_id)

    async def recover_all(
        self,
        *,
        limit: int = 100,
        headers: dict[str, str] | None = None,
        timeout: Any = 180.0,
        proxy: str | None = None,
        resume_enabled: bool = True,
        concurrency: int = 2,
    ) -> dict[str, Any]:
        records = self.recoverable(limit=limit)
        total = len(records)
        safe_concurrency = max(1, min(5, int(concurrency or 1)))
        center = getattr(self, "task_center", None)
        task_id = ""
        download_ids = [str(r.get("download_id") or "") for r in records if r.get("download_id")]
        if center is not None and hasattr(center, "start"):
            try:
                task_id = center.start(
                    "恢复下载记录",
                    "下载恢复",
                    detail=f"准备恢复 {total} 条下载记录，并发 {safe_concurrency}",
                    total=total,
                    retry_action="download_recover_all",
                    retry_payload={"download_ids": download_ids, "concurrency": safe_concurrency},
                ) or ""
            except Exception:
                task_id = ""
        if total <= 0:
            if center is not None and task_id and hasattr(center, "finish"):
                center.finish(task_id, success=True, detail="没有可恢复的下载记录")
            return {
                "total": 0,
                "success_count": 0,
                "failed_count": 0,
                "success": True,
                "task_id": task_id,
                "failures": [],
                "failure_categories": {},
                "concurrency": safe_concurrency,
            }

        state = {"completed": 0, "success": 0, "failed": 0, "last_label": ""}
        failures: list[dict[str, str]] = []
        failure_categories: dict[str, int] = {}
        lock = asyncio.Lock()
        started_at = time.monotonic()

        async def worker(index: int, record: dict[str, Any]) -> None:
            label = str(record.get("label") or os.path.basename(str(record.get("save_path") or "")) or record.get("download_id") or "下载记录")
            async with lock:
                state["last_label"] = label
                self._task_progress(
                    center,
                    task_id,
                    completed=int(state["completed"]),
                    success_count=int(state["success"]),
                    failed_count=int(state["failed"]),
                    detail=f"正在恢复：{label}（{index}/{total}，并发 {safe_concurrency}）",
                )
            result = await self.recover_one_result(
                record,
                headers=headers,
                timeout=timeout,
                proxy=proxy,
                resume_enabled=resume_enabled,
            )
            async with lock:
                state["completed"] = int(state["completed"]) + 1
                if result.get("success"):
                    state["success"] = int(state["success"]) + 1
                else:
                    state["failed"] = int(state["failed"]) + 1
                    category = str(result.get("category") or self._advice(str(result.get("reason") or "")).get("category") or "执行失败")
                    failure_categories[category] = failure_categories.get(category, 0) + 1
                    failures.append(
                        {
                            "download_id": str(record.get("download_id") or result.get("download_id") or ""),
                            "reason": str(result.get("reason") or "恢复失败"),
                            "category": category,
                            "next_step": str(result.get("next_step") or ""),
                        }
                    )
                elapsed = max(0.001, time.monotonic() - started_at)
                speed = int(state["completed"]) / elapsed
                remaining = max(0, total - int(state["completed"]))
                eta = remaining / speed if speed > 0 else 0.0
                category_text = ""
                if failure_categories:
                    category_text = "；失败归类：" + "，".join(f"{name} {count}" for name, count in sorted(failure_categories.items()))
                self._task_progress(
                    center,
                    task_id,
                    completed=int(state["completed"]),
                    success_count=int(state["success"]),
                    failed_count=int(state["failed"]),
                    detail=f"恢复进度：{state['completed']}/{total}，成功 {state['success']}，失败 {state['failed']}，预计剩余 {eta:.0f}s{category_text}",
                    retry_payload={"download_ids": download_ids, "failed_download_ids": [item.get("download_id", "") for item in failures], "failure_categories": failure_categories, "concurrency": safe_concurrency},
                )

        try:
            semaphore = asyncio.Semaphore(safe_concurrency)

            async def guarded(index: int, record: dict[str, Any]) -> None:
                async with semaphore:
                    await worker(index, record)

            await asyncio.gather(*(guarded(index, record) for index, record in enumerate(records, start=1)))
        except asyncio.CancelledError:
            if center is not None and task_id and hasattr(center, "cancel"):
                center.cancel(task_id, f"恢复已取消：成功 {state['success']}，失败 {state['failed']}")
            raise
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            advice = self._advice(reason)
            failure_categories[advice["category"]] = failure_categories.get(advice["category"], 0) + 1
            failures.append({"download_id": "", "reason": reason, "category": advice["category"], "next_step": advice["next_step"]})
            state["failed"] = int(state["failed"]) + 1
            if center is not None and task_id and hasattr(center, "finish"):
                center.finish(task_id, success=False, detail=f"恢复任务异常：{reason}")
            return {
                "total": total,
                "success_count": int(state["success"]),
                "failed_count": int(state["failed"]),
                "success": False,
                "task_id": task_id,
                "failures": failures,
                "failure_categories": failure_categories,
                "concurrency": safe_concurrency,
            }
        if center is not None and task_id and hasattr(center, "finish"):
            category_text = ""
            if failure_categories:
                category_text = "；失败归类：" + "，".join(f"{name} {count}" for name, count in sorted(failure_categories.items()))
            detail = f"恢复完成：总计 {total}，成功 {state['success']}，失败 {state['failed']}，并发 {safe_concurrency}{category_text}"
            center.finish(task_id, success=int(state["failed"]) == 0, detail=detail)
        return {
            "total": total,
            "success_count": int(state["success"]),
            "failed_count": int(state["failed"]),
            "success": int(state["failed"]) == 0,
            "task_id": task_id,
            "failures": failures,
            "failure_categories": failure_categories,
            "concurrency": safe_concurrency,
        }

    @staticmethod
    def _is_recoverable(record: dict[str, Any]) -> bool:
        return is_download_recoverable(record)

    @staticmethod
    def _file_size(path: str) -> int:
        try:
            return inspect_file_state({"save_path": path}).size_bytes
        except OSError:
            return 0

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat(timespec="seconds")

    @staticmethod
    def _task_progress(center: Any, task_id: str, **updates: Any) -> None:
        if center is None or not task_id or not hasattr(center, "progress"):
            return
        try:
            center.progress(task_id, **updates)
        except Exception:
            pass

    @staticmethod
    def _current_media_task_id() -> str:
        try:
            from .media_task_queue import current_media_task_id

            return current_media_task_id()
        except Exception:
            return ""

    @staticmethod
    def _advice(reason: str) -> dict[str, str]:
        advice = classify_failure(reason)
        return {"category": advice.category, "next_step": advice.next_step}

    @classmethod
    def _failure_result(cls, reason: str, download_id: str) -> dict[str, Any]:
        advice = cls._advice(reason)
        return {"success": False, "reason": str(reason or "恢复失败"), "download_id": download_id, **advice}
