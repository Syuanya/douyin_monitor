from __future__ import annotations

from .monitor_common import *
from ..status_rules import is_download_failed_item, is_pending_new_work_item
from ..insights import (
    account_health_insight,
    export_material_links_csv,
    group_statistics,
    health_summary,
    material_collection,
    time_window_digest,
)


class ContentMonitorBaseMixin:
    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def sort_items_newest_first(cls, items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        return sorted(items, key=cls._item_sort_key, reverse=True)

    @classmethod
    def _item_sort_key(cls, item: DouyinContentItem) -> tuple[int, float, float, int]:
        publish_ts = cls._parse_time_for_sort(item.publish_time)
        first_seen_ts = cls._parse_time_for_sort(item.first_seen_time)
        item_id_value = cls._parse_int(item.item_id, 0)
        return (
            1 if publish_ts > 0 else 0,
            publish_ts,
            first_seen_ts,
            item_id_value,
        )

    @staticmethod
    def _parse_time_for_sort(value: str) -> float:
        text = str(value or "").strip()
        if not text or text == "-":
            return 0.0
        if text.isdigit():
            try:
                return float(int(text[:10]))
            except Exception:
                return 0.0
        normalized = text.replace("T", " ").replace("/", "-")
        if normalized.endswith("Z"):
            normalized = normalized[:-1]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(normalized[: len(fmt)], fmt).timestamp()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except Exception:
            return 0.0

    def _account_interval_seconds(self, account: DouyinMonitorAccount) -> float:
        minutes = float(getattr(account, "monitor_interval_minutes", 0.0) or 0.0)
        if minutes <= 0:
            minutes = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        return max(60.0, minutes * 60.0)

    def _account_check_due(self, account: DouyinMonitorAccount, now_ts: float | None = None) -> bool:
        if not account.monitor_enabled:
            return False
        if now_ts is None:
            now_ts = time.time()
        last_ts = self._parse_time_for_sort(account.last_check_time)
        return last_ts <= 0 or now_ts - last_ts >= self._account_interval_seconds(account)

    def _record_monitor_history(self, account: DouyinMonitorAccount, success: bool, detail: str, new_count: int = 0) -> None:
        history = list(getattr(account, "monitor_history", []) or [])
        history.append(
            {
                "time": self._now(),
                "success": bool(success),
                "new": max(0, int(new_count or 0)),
                "detail": sanitize_text(str(detail or ""))[:300],
                "error_count": int(getattr(account, "error_count", 0) or 0),
            }
        )
        account.monitor_history = history[-100:]

    def _apply_account_retention(self, account: DouyinMonitorAccount) -> None:
        self._merge_service.apply_retention(account)

    @staticmethod
    def _is_pending_new_marker(item: DouyinContentItem) -> bool:
        # 下载失败不能从“新作品箱”直接消失。用户需要能看到失败项、重试或手动标记处理。
        return is_pending_new_work_item(item)

    def account_next_check_time(self, account: DouyinMonitorAccount) -> str:
        """Return a user-facing next-check time for account cards/API output."""
        if not getattr(account, "monitor_enabled", False):
            return "未启用"
        last_ts = self._parse_time_for_sort(getattr(account, "last_check_time", "") or "")
        if last_ts <= 0:
            return "等待首次检测"
        next_ts = last_ts + self._account_interval_seconds(account)
        if next_ts <= time.time():
            return "已到期，等待调度"
        return datetime.fromtimestamp(next_ts).strftime("%Y-%m-%d %H:%M:%S")

    def _refresh_account_new_count(self, account: DouyinMonitorAccount) -> int:
        count = sum(1 for item in getattr(account, "items", []) if self._is_pending_new_marker(item))
        account.last_new_count = count
        return count

    def _auto_pause_if_needed(self, account: DouyinMonitorAccount) -> bool:
        return self._merge_service.auto_pause_if_needed(account)

    def _write_detection_log(self, message: str) -> None:
        try:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            line = f"{self._now()} | {sanitize_text(message)}\n"
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.debug(f"Douyin monitor log write failed: {exc}")

    def _interval_seconds(self) -> int:
        try:
            minutes = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        except (TypeError, ValueError):
            minutes = 10
        return max(60, int(minutes * 60))

    def _between_users_delay(self) -> float:
        try:
            value = float(self.settings.user_config.get("douyin_content_check_interval_between_users_seconds", 3) or 3)
        except (TypeError, ValueError):
            value = 3
        return max(0.0, value)

    def _request_timeout(self) -> float:
        try:
            value = float(self.settings.user_config.get("douyin_content_request_timeout_seconds", 15) or 15)
        except (TypeError, ValueError):
            value = 15
        return max(5.0, value)

    def _external_api_base_url(self) -> str:
        return str(self.settings.user_config.get("douyin_external_api_base_url") or "").strip()

    def _parser_backend(self) -> str:
        configured = str(self.settings.user_config.get("douyin_parser_backend") or "").strip().lower()
        if configured in {"internal", "external"}:
            return configured
        return "external" if self._external_api_base_url() else "internal"

    def _parser_max_pages(self) -> int:
        value = self.settings.user_config.get("douyin_parser_max_pages")
        if value in (None, ""):
            value = self.settings.user_config.get("douyin_external_api_max_pages")
        return self._parse_int(value, 20)

    async def _resolve_parser_backend(self) -> str:
        backend = self._parser_backend()
        if backend == "external":
            base_url = self._external_api_base_url()
            if not base_url:
                raise ValueError("已选择外部解析器，但未配置 douyin_external_api_base_url")
            return f"external:{base_url.rstrip('/')}"
        return "internal"

    async def _resolve_external_api_base_url(self) -> str:
        """Backward-compatible wrapper for older call sites/settings names."""
        configured = self._external_api_base_url()
        if configured:
            return configured.rstrip("/")
        return "__internal_video_parser__"

    def _external_api_max_pages(self) -> int:
        return self._parser_max_pages()

    def _headers(self, *, include_cookie: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if include_cookie:
            cookie = self._select_douyin_cookie()
            if cookie:
                headers["Cookie"] = cookie
        return headers

    def _headers_for_cookie_request(self, *, include_cookie: bool = True) -> tuple[dict[str, str], str]:
        headers = self._headers(include_cookie=False)
        cookie = self._select_douyin_cookie() if include_cookie else ""
        if cookie:
            headers["Cookie"] = cookie
        return headers, cookie

    def cleanup_auto_download_tasks(self) -> dict[str, Any]:
        registry = getattr(self, "_auto_download_tasks", {})
        meta_registry = getattr(self, "_auto_download_task_meta", {})
        if not isinstance(registry, dict):
            return {"removed": 0, "running": 0, "tasks": []}
        before = len(registry)
        for key, task in list(registry.items()):
            if task is None or task.done():
                registry.pop(key, None)
                if isinstance(meta_registry, dict):
                    meta_registry.pop(key, None)
        tasks: list[dict[str, Any]] = []
        if isinstance(meta_registry, dict):
            for key, task in registry.items():
                meta = dict(meta_registry.get(key) or {})
                meta.setdefault("task_key", key)
                meta.setdefault("done", bool(task.done()) if task is not None else True)
                tasks.append(meta)
        return {"removed": before - len(registry), "running": len(registry), "tasks": tasks}

    async def cancel_auto_downloads(
        self,
        account_id: str = "",
        item_ids: list[str] | None = None,
        task_key: str = "",
    ) -> dict[str, Any]:
        registry = getattr(self, "_auto_download_tasks", {})
        meta_registry = getattr(self, "_auto_download_task_meta", {})
        if not isinstance(registry, dict):
            return {"cancelled": 0, "remaining": 0}
        wanted_items = set(str(item_id) for item_id in (item_ids or []) if str(item_id or ""))
        prefix = f"{account_id}:" if account_id else ""
        cancelled = 0
        tasks = []
        for key, task in list(registry.items()):
            key_text = str(key)
            if task_key and key_text != str(task_key):
                continue
            if prefix and not key_text.startswith(prefix):
                continue
            if wanted_items:
                meta = meta_registry.get(key_text, {}) if isinstance(meta_registry, dict) else {}
                task_items = set(str(item_id) for item_id in (meta.get("item_ids") or []) if str(item_id or ""))
                if not task_items.intersection(wanted_items):
                    continue
            if task is not None and not task.done():
                task.cancel()
                tasks.append(task)
                cancelled += 1
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                pass
        summary = self.cleanup_auto_download_tasks()
        return {"cancelled": cancelled, "remaining": len(registry), "tasks": summary.get("tasks", [])}


    def content_monitor_health_summary(self) -> dict[str, Any]:
        """Return account health scores and priority accounts for P3 efficiency dashboards."""
        try:
            default_interval = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        except (TypeError, ValueError):
            default_interval = 10.0
        return health_summary(list(getattr(self, "_accounts", []) or []), default_interval_minutes=default_interval)

    def account_health_detail(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        try:
            default_interval = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        except (TypeError, ValueError):
            default_interval = 10.0
        detail = account_health_insight(account, default_interval_minutes=default_interval)
        detail["success"] = True
        detail["download_summary"] = self.download_status_summary(account_id) if hasattr(self, "download_status_summary") else {}
        detail["next_check_time"] = self.account_next_check_time(account) if hasattr(self, "account_next_check_time") else ""
        return detail

    def content_monitor_group_statistics(self) -> dict[str, Any]:
        try:
            default_interval = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        except (TypeError, ValueError):
            default_interval = 10.0
        return group_statistics(list(getattr(self, "_accounts", []) or []), default_interval_minutes=default_interval)

    def content_monitor_material_collection(
        self,
        *,
        query: str = "",
        status: str = "pending",
        media_type: str = "all",
        group_name: str = "",
        limit: int = 200,
    ) -> dict[str, Any]:
        return material_collection(
            list(getattr(self, "_accounts", []) or []),
            query=query,
            status=status,
            media_type=media_type,
            group_name=group_name,
            limit=limit,
        )

    def content_monitor_time_window_digest(self, *, days: int = 1) -> dict[str, Any]:
        return time_window_digest(list(getattr(self, "_accounts", []) or []), days=days)

    def export_content_monitor_material_links(
        self,
        *,
        query: str = "",
        status: str = "pending",
        media_type: str = "all",
        group_name: str = "",
        limit: int = 1000,
    ) -> dict[str, Any]:
        collection = self.content_monitor_material_collection(
            query=query,
            status=status,
            media_type=media_type,
            group_name=group_name,
            limit=limit,
        )
        rows = list(collection.get("items") or [])
        if not rows:
            return {"success": False, "reason": "暂无可导出的素材链接", "total": 0}
        export_dir = Path(self.services.run_path) / "downloads" / "monitor_exports"
        path = export_dir / f"douyin_material_links_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        export_material_links_csv(path, rows)
        return {"success": True, "path": str(path), "total": len(rows), "filters": {"query": query, "status": status, "media_type": media_type, "group_name": group_name}}

    def content_monitor_runtime_summary(self) -> dict[str, Any]:
        accounts = list(getattr(self, "_accounts", []) or [])
        enabled = [account for account in accounts if bool(getattr(account, "monitor_enabled", False))]
        errored = [account for account in accounts if int(getattr(account, "error_count", 0) or 0) > 0 or str(getattr(account, "last_error", "") or "")]
        item_total = 0
        new_total = 0
        failed_download_total = 0
        for account in accounts:
            items = list(getattr(account, "items", []) or [])
            item_total += len(items)
            new_total += len([item for item in items if is_pending_new_work_item(item)])
            failed_download_total += len([item for item in items if is_download_failed_item(item)])
        auto_summary = self.cleanup_auto_download_tasks()
        media_queue = getattr(self.services, "media_task_queue", None)
        task_center = getattr(self.services, "task_center", None)
        batch_store = getattr(self.services, "batch_job_store", None)
        return {
            "accounts_total": len(accounts),
            "accounts_enabled": len(enabled),
            "accounts_with_errors": len(errored),
            "items_total": item_total,
            "pending_new_items": new_total,
            "download_failed_items": failed_download_total,
            "scheduler_running": self.is_periodic_task_running() if hasattr(self, "is_periodic_task_running") else False,
            "batch_check_running": bool(getattr(getattr(self, "_batch_check_lock", None), "locked", lambda: False)()),
            "auto_download_tasks": auto_summary,
            "persist": self.persist_status() if hasattr(self, "persist_status") else {},
            "media_queue": media_queue.snapshot() if media_queue is not None and hasattr(media_queue, "snapshot") else {},
            "task_center_active": task_center.active_count() if task_center is not None and hasattr(task_center, "active_count") else 0,
            "pending_batch_jobs": len(batch_store.pending_jobs()) if batch_store is not None and hasattr(batch_store, "pending_jobs") else 0,
            "health": self.content_monitor_health_summary() if hasattr(self, "content_monitor_health_summary") else {},
            "groups": self.content_monitor_group_statistics() if hasattr(self, "content_monitor_group_statistics") else {},
            "digest_24h": self.content_monitor_time_window_digest(days=1) if hasattr(self, "content_monitor_time_window_digest") else {},
        }
