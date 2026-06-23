from __future__ import annotations

import os
from typing import Any

from ..runtime.task_center import classify_failure
from .common import default_douyin_download_path, storage_writable


class IssueCenterService:
    """Collects actionable issues for the issue-center page."""

    def __init__(self, app: Any):
        self.app = app

    def collect_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        settings = getattr(self.app.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        douyin_cookie = str(cookies.get("douyin_cookie") or "").strip()
        if not (douyin_cookie and "=" in douyin_cookie and len(douyin_cookie) >= 20):
            issues.append(
                {
                    "level": "高",
                    "title": "抖音 Cookie 未配置或格式异常",
                    "detail": "解析、同步作品和监控主页可能失败。",
                    "next_step": "打开设置页填写完整 Cookie，并点击 Cookie 测试。",
                    "page": self.app.settings_page.page_name,
                }
            )

        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        storage_path = str(user_config.get("douyin_content_download_path") or "").strip() or default_douyin_download_path(self.app)
        if not storage_writable(storage_path):
            issues.append(
                {
                    "level": "高",
                    "title": "下载目录不可写",
                    "detail": storage_path,
                    "next_step": "检查目录权限，或在设置页更换保存路径。",
                    "page": self.app.settings_page.page_name,
                }
            )

        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is not None and hasattr(queue, "snapshot"):
            try:
                snapshot = queue.snapshot()
            except Exception:
                snapshot = {}
            global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
            if global_state.get("paused"):
                issues.append(
                    {
                        "level": "中",
                        "title": "下载队列已暂停",
                        "detail": "后台下载任务不会继续执行。",
                        "next_step": "打开任务中心点击继续下载。",
                        "page": self.app.task_center_page.page_name,
                    }
                )

        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        for account in list(getattr(monitor, "accounts", []) or []):
            reason = str(getattr(account, "last_error", "") or "")
            status = str(getattr(account, "status", "") or "")
            if reason or "异常" in status:
                issues.append(
                    {
                        "level": "中",
                        "title": f"账号异常：{account.display_name or account.douyin_nickname or account.account_id}",
                        "detail": reason or status,
                        "next_step": "打开内容监控页检查账号，必要时更新 Cookie 后重新检测。",
                        "page": self.app.douyin_content.page_name,
                    }
                )

        task_center = getattr(self.app.services, "task_center", None)
        records = task_center.snapshot(200) if task_center is not None and hasattr(task_center, "snapshot") else []
        for record in records:
            if str(record.get("status") or "") != "失败":
                continue
            failure = classify_failure(str(record.get("detail") or ""))
            issues.append(
                {
                    "level": "中",
                    "title": f"任务失败：{record.get('title') or '未命名任务'}",
                    "detail": f"{failure.get('category') or '执行失败'}：{record.get('detail') or '-'}",
                    "next_step": failure.get("next_step") or "打开任务中心查看详情并重试。",
                    "page": self.app.task_center_page.page_name,
                }
            )
        return issues[:100]
