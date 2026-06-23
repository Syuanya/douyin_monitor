from __future__ import annotations

import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from .common import default_douyin_download_path, format_bytes, storage_writable


class HomeDashboardService:
    """Builds dashboard state without importing or constructing Flet controls."""

    def __init__(self, app: Any):
        self.app = app

    def stats(self) -> dict[str, Any]:
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        accounts = list(getattr(monitor, "accounts", []) or [])
        works = sum(len(getattr(account, "items", []) or []) for account in accounts)
        new_works = sum(
            1
            for account in accounts
            for item in getattr(account, "items", []) or []
            if getattr(item, "status", "") == "new"
        )
        error_accounts = len(
            [account for account in accounts if getattr(account, "last_error", "") or "异常" in str(getattr(account, "status", ""))]
        )
        running_accounts = len([account for account in accounts if getattr(account, "monitor_enabled", False)])

        task_center = getattr(self.app.services, "task_center", None)
        tasks = task_center.snapshot(80) if task_center is not None and hasattr(task_center, "snapshot") else []
        running_tasks = len([task for task in tasks if str(task.get("status")) in {"运行中", "等待中"}])
        failed_tasks = len([task for task in tasks if str(task.get("status")) == "失败"])
        today = datetime.now().strftime("%Y-%m-%d")
        today_tasks = [task for task in tasks if self.task_time(task).startswith(today)]
        today_failed_tasks = len([task for task in today_tasks if str(task.get("status")) == "失败"])
        today_downloads = len(
            [
                task
                for task in today_tasks
                if str(task.get("status")) == "完成"
                and str(task.get("category") or "") in {"内容监控下载", "视频下载", "图片下载"}
            ]
        )
        failure_rate = f"{round(failed_tasks / len(tasks) * 100):d}%" if tasks else "0%"

        queue_snapshot = self.queue_snapshot()
        queue_running = sum(
            int(value.get("running", 0) or 0)
            for key, value in queue_snapshot.items()
            if key != "__global__" and isinstance(value, dict)
        )
        queue_waiting = sum(
            int(value.get("waiting", 0) or 0)
            for key, value in queue_snapshot.items()
            if key != "__global__" and isinstance(value, dict)
        )
        global_queue = queue_snapshot.get("__global__", {}) if isinstance(queue_snapshot, dict) else {}
        queue_running_labels = [str(label) for label in global_queue.get("running_labels", []) if label]
        queue_waiting_labels = [str(label) for label in global_queue.get("waiting_labels", []) if label]
        queue_active_text = "当前：" + "、".join(queue_running_labels[:2]) if queue_running_labels else "当前暂无下载"
        if not queue_running_labels and queue_waiting_labels:
            queue_active_text = "等待：" + "、".join(queue_waiting_labels[:2])

        settings = getattr(self.app.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        douyin_cookie = str(cookies.get("douyin_cookie") or "").strip()
        storage_path = str(user_config.get("douyin_content_download_path") or "").strip() or default_douyin_download_path(self.app)
        disk_free, disk_total = self.disk_usage_text(storage_path)
        parser = getattr(self.app.services, "video_parser", None)
        return {
            "accounts": len(accounts),
            "running_accounts": running_accounts,
            "error_accounts": error_accounts,
            "works": works,
            "new_works": new_works,
            "tasks": len(tasks),
            "running_tasks": running_tasks,
            "failed_tasks": failed_tasks,
            "today_failed_tasks": today_failed_tasks,
            "today_downloads": today_downloads,
            "failure_rate": failure_rate,
            "queue_running": queue_running,
            "queue_waiting": queue_waiting,
            "queue_running_labels": queue_running_labels,
            "queue_waiting_labels": queue_waiting_labels,
            "queue_active_text": queue_active_text,
            "queue_limit": int(global_queue.get("limit", 0) or 0),
            "queue_paused": bool(global_queue.get("paused", False)),
            "cookie_ready": bool(douyin_cookie and "=" in douyin_cookie and len(douyin_cookie) >= 20),
            "storage_ready": storage_writable(storage_path),
            "storage_path": storage_path,
            "disk_free": disk_free,
            "disk_total": disk_total,
            "parser_ready": parser is not None,
            "parse_concurrency": getattr(parser, "parse_concurrency", user_config.get("video_parse_concurrency", 4)),
        }

    def queue_snapshot(self) -> dict[str, Any]:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return {}
        try:
            snapshot = queue.snapshot()
            return snapshot if isinstance(snapshot, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def task_time(task: dict[str, Any]) -> str:
        return str(task.get("updated_at") or task.get("started_at") or task.get("finished_at") or "")

    @staticmethod
    def disk_usage_text(path: str) -> tuple[str, str]:
        try:
            target = Path(path)
            target.mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(str(target))
            return format_bytes(usage.free), format_bytes(usage.total)
        except Exception:
            return "未知", "未知"
