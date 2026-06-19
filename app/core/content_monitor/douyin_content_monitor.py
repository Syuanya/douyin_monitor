from __future__ import annotations

import asyncio
import glob
import html
import json
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from ...core.diagnostics.diagnostic_tools import sanitize_text, sanitize_url
from ...core.media.cookie_utils import sanitize_cookie_header
from ...core.media.file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename
from ...core.media.image_urls import deduplicate_image_urls
from ...core.media.resumable_download import download_http_file
from ...core.parser import build_douyin_parser_backend
from ...core.media.video_parser_service import ParsedVideoResult
from ...core.runtime.media_task_queue import report_media_task_progress
from ...utils.logger import logger
from .services.account_repository import AccountRepository
from .services.content_merge_service import ContentMergeService
from .services.scheduler_service import PeriodicMonitorScheduler

DOUYIN_HOST_RE = re.compile(r"(^|\.)(douyin\.com|iesdouyin\.com|snssdk\.com)$", re.IGNORECASE)
ITEM_ID_PATTERNS = [
    re.compile(r'"(?:aweme_id|awemeId|item_id|itemId|itemID|id)"\s*:\s*"(\d{8,})"'),
    re.compile(r'"(?:aweme_id|awemeId|item_id|itemId|itemID|id)"\s*:\s*(\d{8,})'),
    re.compile(r'"(?:group_id|groupId|groupID)"\s*:\s*"(\d{8,})"'),
    re.compile(r'"(?:group_id|groupId|groupID)"\s*:\s*(\d{8,})'),
    re.compile(r"/video/(\d{8,})"),
    re.compile(r"/note/(\d{8,})"),
    re.compile(r"/share/video/(\d{8,})"),
]
ITEM_ID_KEYS = ("aweme_id", "awemeId", "item_id", "itemId", "itemID", "group_id", "groupId", "id")
TITLE_KEYS = ("desc", "caption", "title", "text", "share_title", "shareTitle")
CREATE_TIME_KEYS = ("create_time", "createTime", "publish_time", "publishTime")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0, read=60.0, write=30.0, pool=10.0)


@dataclass
class DouyinContentItem:
    item_id: str
    title: str = ""
    share_url: str = ""
    download_url: str = ""
    cover_url: str = ""
    media_type: str = "video"
    image_urls: list[str] = field(default_factory=list)
    publish_time: str = ""
    first_seen_time: str = ""
    last_seen_time: str = ""
    status: str = "active"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DouyinContentItem":
        return cls(
            item_id=str(data.get("item_id") or data.get("aweme_id") or ""),
            title=str(data.get("title") or ""),
            share_url=str(data.get("share_url") or ""),
            download_url=str(data.get("download_url") or ""),
            cover_url=str(data.get("cover_url") or ""),
            media_type=str(data.get("media_type") or data.get("type") or "video"),
            image_urls=deduplicate_image_urls([str(url) for url in data.get("image_urls", []) if url]),
            publish_time=str(data.get("publish_time") or ""),
            first_seen_time=str(data.get("first_seen_time") or ""),
            last_seen_time=str(data.get("last_seen_time") or ""),
            status=str(data.get("status") or "active"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "title": self.title,
            "share_url": self.share_url,
            "download_url": self.download_url,
            "cover_url": self.cover_url,
            "media_type": self.media_type,
            "image_urls": self.image_urls,
            "publish_time": self.publish_time,
            "first_seen_time": self.first_seen_time,
            "last_seen_time": self.last_seen_time,
            "status": self.status,
        }


@dataclass
class DouyinMonitorAccount:
    account_id: str
    homepage_url: str
    display_name: str = ""
    group_name: str = ""
    auto_download_policy: str = "none"
    monitor_interval_minutes: float = 0.0
    auto_sync_enabled: bool = True
    auto_pause_failures: int = 0
    keep_recent_count: int = 0
    notify_mode: str = "desktop"
    douyin_nickname: str = ""
    avatar_url: str = ""
    monitor_enabled: bool = False
    notify_enabled: bool = True
    status: str = "未监控"
    last_check_time: str = ""
    last_success_time: str = ""
    last_error: str = ""
    error_count: int = 0
    total_new_count: int = 0
    last_new_count: int = 0
    aweme_count: int = -1
    last_aweme_count: int = -1
    last_item_id: str = ""
    monitor_history: list[dict[str, Any]] = field(default_factory=list)
    known_item_ids: list[str] = field(default_factory=list)
    items: list[DouyinContentItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DouyinMonitorAccount":
        items = [DouyinContentItem.from_dict(item) for item in data.get("items", []) if isinstance(item, dict)]

        def as_int(value: Any, default: int = 0) -> int:
            try:
                if value is None or value == "":
                    return default
                return int(value)
            except (TypeError, ValueError):
                return default

        def as_float(value: Any, default: float = 0.0) -> float:
            try:
                if value is None or value == "":
                    return default
                return float(value)
            except (TypeError, ValueError):
                return default

        return cls(
            account_id=str(data.get("account_id") or data.get("id") or uuid.uuid4().hex),
            homepage_url=str(data.get("homepage_url") or data.get("url") or ""),
            display_name=str(data.get("display_name") or ""),
            group_name=str(data.get("group_name") or ""),
            auto_download_policy=str(data.get("auto_download_policy") or "none"),
            monitor_interval_minutes=max(0.0, as_float(data.get("monitor_interval_minutes"), 0.0)),
            auto_sync_enabled=bool(data.get("auto_sync_enabled", True)),
            auto_pause_failures=max(0, as_int(data.get("auto_pause_failures"), 0)),
            keep_recent_count=max(0, as_int(data.get("keep_recent_count"), 0)),
            notify_mode=str(data.get("notify_mode") or "desktop"),
            douyin_nickname=str(data.get("douyin_nickname") or data.get("nickname") or ""),
            avatar_url=str(data.get("avatar_url") or data.get("avatar") or ""),
            monitor_enabled=bool(data.get("monitor_enabled", False)),
            notify_enabled=bool(data.get("notify_enabled", True)),
            status=str(data.get("status") or "未监控"),
            last_check_time=str(data.get("last_check_time") or ""),
            last_success_time=str(data.get("last_success_time") or ""),
            last_error=str(data.get("last_error") or ""),
            error_count=as_int(data.get("error_count"), 0),
            total_new_count=as_int(data.get("total_new_count"), 0),
            last_new_count=as_int(data.get("last_new_count"), 0),
            aweme_count=as_int(data.get("aweme_count"), -1),
            last_aweme_count=as_int(data.get("last_aweme_count", data.get("aweme_count")), -1),
            last_item_id=str(data.get("last_item_id") or ""),
            monitor_history=[item for item in data.get("monitor_history", []) if isinstance(item, dict)][-100:],
            known_item_ids=[str(x) for x in data.get("known_item_ids", []) if x],
            items=items,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "homepage_url": self.homepage_url,
            "display_name": self.display_name,
            "group_name": self.group_name,
            "auto_download_policy": self.auto_download_policy,
            "monitor_interval_minutes": self.monitor_interval_minutes,
            "auto_sync_enabled": self.auto_sync_enabled,
            "auto_pause_failures": self.auto_pause_failures,
            "keep_recent_count": self.keep_recent_count,
            "notify_mode": self.notify_mode,
            "douyin_nickname": self.douyin_nickname,
            "avatar_url": self.avatar_url,
            "monitor_enabled": self.monitor_enabled,
            "notify_enabled": self.notify_enabled,
            "status": self.status,
            "last_check_time": self.last_check_time,
            "last_success_time": self.last_success_time,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "total_new_count": self.total_new_count,
            "last_new_count": self.last_new_count,
            "aweme_count": self.aweme_count,
            "last_aweme_count": self.last_aweme_count,
            "last_item_id": self.last_item_id,
            "monitor_history": self.monitor_history[-100:],
            "known_item_ids": self.known_item_ids,
            "items": [item.to_dict() for item in self.items],
        }


class DouyinContentMonitorManager:
    """Low-frequency monitor for public Douyin profile page changes.

    This module only reads public profile pages provided by the user.  It does
    not attempt to bypass login, private profiles, CAPTCHAs, platform rate
    limits or risk-control responses.  The detector is intentionally conservative:
    the first successful scan creates a baseline; later scans notify only newly
    observed work IDs.
    """

    def __init__(self, services):
        self.services = services
        self.settings = services.settings_config
        self.run_path = services.run_path
        self.config_path = os.path.join(self.run_path, "config", "douyin_content_monitor.json")
        self.log_path = os.path.join(self.run_path, "logs", "douyin_monitor.log")
        self._account_repository = AccountRepository(
            self.config_path,
            sqlite_store=getattr(services, "sqlite_store", None),
            mirror_json=bool(self.settings.user_config.get("sqlite_json_mirror_enabled", True)),
        )
        self._accounts: list[DouyinMonitorAccount] = []
        self._lock = asyncio.Lock()
        self._batch_check_lock = asyncio.Lock()
        self._account_scan_locks: dict[str, asyncio.Lock] = {}
        self._persist_task: asyncio.Task | None = None
        self._periodic_task: asyncio.Task | None = None
        self._persist_lock = asyncio.Lock()
        self._last_persist_at = 0.0
        self._persist_debounce_seconds = 1.5
        self._op_logger = logger.bind(douyin_monitor_event=True)
        self._merge_service = ContentMergeService(
            now_fn=self._now,
            sort_items_newest_first=self.sort_items_newest_first,
            is_gallery_item=self._is_gallery_item,
        )
        self._scheduler = PeriodicMonitorScheduler(
            run_once=self._periodic_check_once,
            interval_seconds=self._interval_seconds,
            logger=logger,
        )
        self._load_accounts()

    @property
    def accounts(self) -> list[DouyinMonitorAccount]:
        return self._accounts

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

    def _load_accounts(self) -> None:
        loaded_accounts = self._account_repository.load_accounts(DouyinMonitorAccount.from_dict)
        self._accounts = self._dedupe_accounts(loaded_accounts)
        if len(self._accounts) != len(loaded_accounts):
            self._save_accounts_sync()
        logger.info(f"Douyin content monitor: loaded {len(self._accounts)} accounts")

    @staticmethod
    def _dedupe_accounts(accounts: list[DouyinMonitorAccount]) -> list[DouyinMonitorAccount]:
        deduped: list[DouyinMonitorAccount] = []
        by_url: dict[str, DouyinMonitorAccount] = {}
        for account in accounts:
            key = account.homepage_url.strip().rstrip("/")
            if not key:
                key = account.account_id
            existing = by_url.get(key)
            if existing is None:
                by_url[key] = account
                deduped.append(account)
                continue

            if not existing.display_name and account.display_name:
                existing.display_name = account.display_name
            if not existing.douyin_nickname and account.douyin_nickname:
                existing.douyin_nickname = account.douyin_nickname
            if not existing.avatar_url and account.avatar_url:
                existing.avatar_url = account.avatar_url
            existing.monitor_enabled = existing.monitor_enabled or account.monitor_enabled
            existing.notify_enabled = existing.notify_enabled or account.notify_enabled
            existing.total_new_count = max(existing.total_new_count, account.total_new_count)
            existing.last_new_count = max(existing.last_new_count, account.last_new_count)
            existing.aweme_count = max(existing.aweme_count, account.aweme_count)
            existing.last_aweme_count = max(existing.last_aweme_count, account.last_aweme_count)
            for item_id in account.known_item_ids:
                if item_id not in existing.known_item_ids:
                    existing.known_item_ids.append(item_id)
            existing_items = {item.item_id for item in existing.items}
            for item in account.items:
                if item.item_id not in existing_items:
                    existing.items.append(item)
                    existing_items.add(item.item_id)
        return deduped

    def _save_accounts_sync(self, accounts: list[dict[str, Any]] | None = None) -> None:
        if accounts is None:
            accounts = [account.to_dict() for account in self._accounts]
        self._account_repository.save_accounts(accounts)

    async def persist(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_persist_at >= self._persist_debounce_seconds:
            if self._persist_task and not self._persist_task.done():
                self._persist_task.cancel()
            await self._persist_now()
            return
        self._schedule_persist()

    def _schedule_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            return
        try:
            self._persist_task = asyncio.create_task(self._delayed_persist())
        except RuntimeError:
            self._save_accounts_sync()

    async def _delayed_persist(self) -> None:
        await asyncio.sleep(self._persist_debounce_seconds)
        await self._persist_now()

    async def _persist_now(self) -> None:
        accounts = [account.to_dict() for account in self._accounts]
        async with self._persist_lock:
            await asyncio.to_thread(self._save_accounts_sync, accounts)
            self._last_persist_at = time.monotonic()

    async def flush_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            self._persist_task.cancel()
        await self._persist_now()

    @staticmethod
    def normalize_homepage_url(raw_url: str) -> str:
        text = str(raw_url or "").strip()
        if not text:
            raise ValueError("请输入抖音主页链接")
        if not re.match(r"^https?://", text, re.IGNORECASE):
            text = "https://" + text
        parts = urlsplit(text)
        host = (parts.netloc or "").lower()
        if not host:
            raise ValueError("主页链接无效")
        if not DOUYIN_HOST_RE.search(host):
            raise ValueError("只支持公开抖音主页链接")
        # Keep path, remove query/fragment to reduce expired tracking params.
        return urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/") or "/", "", ""))

    def find_account(self, account_id: str) -> DouyinMonitorAccount | None:
        for account in self._accounts:
            if account.account_id == account_id:
                return account
        return None

    def _account_scan_lock(self, account_id: str) -> asyncio.Lock:
        key = str(account_id or "")
        lock = self._account_scan_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._account_scan_locks[key] = lock
        return lock

    @staticmethod
    def extract_sec_uid(homepage_url: str) -> str:
        parts = urlsplit(str(homepage_url or ""))
        match = re.search(r"/user/([^/?#]+)", parts.path)
        return match.group(1) if match else ""

    async def add_account(self, homepage_url: str, display_name: str = "") -> DouyinMonitorAccount:
        url = self.normalize_homepage_url(homepage_url)
        sec_uid = self.extract_sec_uid(url)
        provided_display_name = str(display_name or "").strip()
        async with self._lock:
            for account in self._accounts:
                account_sec_uid = self.extract_sec_uid(account.homepage_url)
                if account.homepage_url == url or (sec_uid and account_sec_uid == sec_uid):
                    if provided_display_name:
                        account.display_name = provided_display_name
                    elif not account.display_name or account.display_name == "抖音用户":
                        account.display_name = account.douyin_nickname or account.display_name or "抖音用户"
                    if account.homepage_url != url and sec_uid:
                        account.homepage_url = url
                    await self.persist(force=True)
                    return account
            account = DouyinMonitorAccount(
                account_id=uuid.uuid4().hex,
                homepage_url=url,
                display_name=provided_display_name or "抖音用户",
                notify_enabled=bool(self.settings.user_config.get("douyin_content_notify_enabled", True)),
                status="未监控",
            )
            self._accounts.append(account)
            await self.persist(force=True)
        self._write_detection_log(f"Added Douyin monitor account: {url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "added", "account_id": account.account_id})
        return account

    async def hydrate_account_display_name(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "display_name": ""}
        if str(account.display_name or "").strip() and account.display_name != "抖音用户":
            return {"success": True, "reason": "已使用手动备注", "display_name": account.display_name}

        try:
            profile_info = await self.fetch_user_profile_info(account)
        except Exception as exc:
            profile_info = {}
            logger.debug(f"Hydrate Douyin display name by user info failed: {exc}")

        nickname = str(profile_info.get("douyin_nickname") or "").strip()
        avatar_url = str(profile_info.get("avatar_url") or "").strip()
        if not nickname:
            try:
                page_text, final_url = await self.fetch_public_profile(account)
                if final_url:
                    account.homepage_url = self.normalize_homepage_url(final_url)
                nickname = self._extract_douyin_nickname(page_text)
            except Exception as exc:
                logger.debug(f"Hydrate Douyin display name by public profile failed: {exc}")

        if nickname:
            account.douyin_nickname = nickname[:80]
            account.display_name = account.douyin_nickname
        if avatar_url:
            account.avatar_url = avatar_url
        if nickname or avatar_url:
            await self.persist(force=True)
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "account_profile", "account_id": account_id})
            return {"success": True, "reason": "已自动填充抖音昵称", "display_name": account.display_name}
        return {"success": False, "reason": "暂未获取到抖音昵称", "display_name": account.display_name}

    @staticmethod
    def _auto_fill_display_name(account: DouyinMonitorAccount) -> None:
        if account.douyin_nickname and (not account.display_name or account.display_name == "抖音用户"):
            account.display_name = account.douyin_nickname

    async def delete_account(self, account_id: str) -> bool:
        async with self._lock:
            account = self.find_account(account_id)
            if not account:
                return False
            self._accounts.remove(account)
            self._account_scan_locks.pop(account_id, None)
            await self.persist(force=True)
        self._write_detection_log(f"Deleted Douyin monitor account: {account.homepage_url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "deleted", "account_id": account_id})
        return True

    async def restore_accounts(self, account_data: list[dict[str, Any]]) -> int:
        restored = 0
        async with self._lock:
            existing_ids = {account.account_id for account in self._accounts}
            existing_urls = {account.homepage_url for account in self._accounts}
            for data in account_data:
                account = DouyinMonitorAccount.from_dict(data)
                if account.account_id in existing_ids or account.homepage_url in existing_urls:
                    continue
                self._accounts.append(account)
                existing_ids.add(account.account_id)
                existing_urls.add(account.homepage_url)
                restored += 1
            if restored:
                await self.persist(force=True)
        if restored:
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "restored", "count": restored})
        return restored

    async def start_monitor(self, account_id: str) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        account.monitor_enabled = True
        account.status = "等待检测"
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "status", "account_id": account_id})
        return True

    async def stop_monitor(self, account_id: str) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        account.monitor_enabled = False
        account.status = "已停止监控"
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "status", "account_id": account_id})
        return True

    async def update_account_settings(
        self,
        account_id: str,
        *,
        display_name: str | None = None,
        group_name: str | None = None,
        auto_download_policy: str | None = None,
        monitor_interval_minutes: float | None = None,
        auto_sync_enabled: bool | None = None,
        auto_pause_failures: int | None = None,
        keep_recent_count: int | None = None,
        notify_mode: str | None = None,
        notify_enabled: bool | None = None,
    ) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        if display_name is not None:
            account.display_name = str(display_name or "").strip() or account.display_name
        if group_name is not None:
            account.group_name = str(group_name or "").strip()
        if auto_download_policy is not None:
            policy = str(auto_download_policy or "none").strip()
            account.auto_download_policy = policy if policy in {"none", "video", "gallery", "all"} else "none"
        if monitor_interval_minutes is not None:
            try:
                account.monitor_interval_minutes = max(0.0, float(monitor_interval_minutes or 0))
            except (TypeError, ValueError):
                account.monitor_interval_minutes = 0.0
        if auto_sync_enabled is not None:
            account.auto_sync_enabled = bool(auto_sync_enabled)
        if auto_pause_failures is not None:
            try:
                account.auto_pause_failures = max(0, int(auto_pause_failures or 0))
            except (TypeError, ValueError):
                account.auto_pause_failures = 0
        if keep_recent_count is not None:
            try:
                account.keep_recent_count = max(0, int(keep_recent_count or 0))
            except (TypeError, ValueError):
                account.keep_recent_count = 0
        if notify_mode is not None:
            mode = str(notify_mode or "desktop")
            account.notify_mode = mode if mode in {"desktop", "task", "silent"} else "desktop"
        if notify_enabled is not None:
            account.notify_enabled = bool(notify_enabled)
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "account_settings", "account_id": account_id})
        return True

    async def start_all(self) -> dict[str, Any]:
        results = []
        for account in list(self._accounts):
            ok = await self.start_monitor(account.account_id)
            results.append({"account_id": account.account_id, "status": "success" if ok else "failed"})
            await asyncio.sleep(self._between_users_delay())
        return {"total": len(results), "results": results}

    async def stop_all(self) -> dict[str, Any]:
        results = []
        for account in list(self._accounts):
            ok = await self.stop_monitor(account.account_id)
            results.append({"account_id": account.account_id, "status": "success" if ok else "failed"})
            await asyncio.sleep(min(0.5, self._between_users_delay()))
        return {"total": len(results), "results": results}

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

    def _content_download_dir(self, account: DouyinMonitorAccount) -> str:
        base = str(self.settings.user_config.get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.run_path, "downloads", "douyin_content")
        safe_name = self._account_download_folder_name(account)
        return os.path.join(base, safe_name)

    def _filename_template(self) -> str:
        return str(self.settings.user_config.get("douyin_content_filename_template") or DEFAULT_FILENAME_TEMPLATE)

    def _media_filename(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        return format_media_filename(
            self._filename_template(),
            {
                "platform": "douyin",
                "author": account.douyin_nickname or account.display_name or account.account_id,
                "item_id": item.item_id,
                "title": item.title or item.item_id,
            },
            fallback=item.item_id or "douyin",
        )

    def _video_save_path(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        return os.path.join(self._content_download_dir(account), f"{self._media_filename(account, item)}.mp4")

    def _existing_downloaded_video_path(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        save_path = self._video_save_path(account, item)
        if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
            return save_path

        roots = self._video_search_roots(account)
        media_name = self._media_filename(account, item)
        patterns = [
            f"{glob.escape(media_name)}.mp4",
            f"{glob.escape(item.item_id)}*.mp4",
            f"*{glob.escape(item.item_id)}*.mp4",
        ]
        matches: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for pattern in patterns:
                try:
                    candidates = root.rglob(pattern)
                    for path in candidates:
                        key = str(path.resolve())
                        if key in seen:
                            continue
                        seen.add(key)
                        if path.is_file() and path.suffix.lower() == ".mp4" and path.stat().st_size > 0:
                            matches.append(path)
                except OSError as exc:
                    logger.debug(f"Search downloaded video failed in {root}: {exc}")
        if not matches:
            return ""
        return str(max(matches, key=lambda path: path.stat().st_mtime))

    def _video_search_roots(self, account: DouyinMonitorAccount) -> list[Path]:
        roots: list[Path] = [Path(self._content_download_dir(account))]
        base = str(self.settings.user_config.get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.run_path, "downloads", "douyin_content")
        base_path = Path(base)
        roots.extend([base_path / "parsed", base_path])
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key and key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def local_item_path_info(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在"}
        if self._is_gallery_item(item):
            folder = os.path.join(self._content_download_dir(account), self._media_filename(account, item))
            if os.path.isdir(folder):
                files = [str(path) for path in sorted(Path(folder).glob("*")) if path.is_file()]
                if files:
                    return {"success": True, "kind": "folder", "path": folder, "files": files}
            return {"success": False, "reason": "未找到已下载图集文件夹"}
        path = self._existing_downloaded_video_path(account, item)
        if path:
            return {"success": True, "kind": "file", "path": path, "folder": os.path.dirname(path)}
        return {"success": False, "reason": "未找到已下载视频文件"}

    def _account_download_folder_name(self, account: DouyinMonitorAccount) -> str:
        generic_names = {"", "抖音用户", "douyin user", "douyin"}
        display_name = str(account.display_name or "").strip()
        nickname = str(account.douyin_nickname or "").strip()
        name = nickname or ("" if display_name.lower() in generic_names else display_name) or account.account_id
        safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .") or account.account_id
        sec_uid = self.extract_sec_uid(account.homepage_url)
        suffix = (sec_uid[-8:] if sec_uid else account.account_id[:8]).strip()
        if suffix and suffix not in safe_name:
            safe_name = f"{safe_name}_{suffix}"
        return safe_name[:120]

    def _headers(self) -> dict[str, str]:
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
        try:
            cookie = self.settings.get_cookies_value("douyin_cookie", "")
        except Exception:
            cookie = ""
        cookie = sanitize_cookie_header(cookie)
        if cookie:
            headers["Cookie"] = cookie
        return headers

    @staticmethod
    def _extract_display_name(page_text: str) -> str:
        title_match = re.search(r"<title[^>]*>(.*?)</title>", page_text, re.IGNORECASE | re.DOTALL)
        if title_match:
            title = html.unescape(re.sub(r"\s+", " ", title_match.group(1))).strip()
            for suffix in (" - 抖音", "_抖音", "| 抖音", "的抖音"):
                title = title.replace(suffix, "")
            if title and "抖音" not in title[:4]:
                return title[:80]
        for pattern in (
            r'"nickname"\s*:\s*"([^"]{1,80})"',
            r'"user"\s*:\s*\{[^{}]{0,500}"nickname"\s*:\s*"([^"]{1,80})"',
        ):
            m = re.search(pattern, page_text)
            if m:
                return html.unescape(m.group(1)).strip()[:80]
        return ""

    @classmethod
    def _extract_douyin_nickname(cls, page_text: str) -> str:
        nickname = cls._extract_display_name(page_text)
        if nickname:
            return cls._decode_text(nickname)[:80]

        scripts = re.findall(r"<script[^>]*>(.*?)</script>", page_text, re.IGNORECASE | re.DOTALL)
        for script in scripts:
            text = html.unescape(script).strip()
            if not text:
                continue
            if "%7B" in text[:200] or "%5B" in text[:200]:
                text = unquote(text)
            if not text.startswith(("{", "[")):
                continue
            try:
                found = cls._find_nickname_in_json(json.loads(text))
            except Exception:
                found = ""
            if found:
                return found
        return ""

    @classmethod
    def _find_nickname_in_json(cls, data: Any) -> str:
        if isinstance(data, dict):
            for key in ("nickname", "nickName", "nick_name", "unique_id", "short_id"):
                value = data.get(key)
                if isinstance(value, str):
                    candidate = re.sub(r"\s+", " ", cls._decode_text(value)).strip()
                    if candidate:
                        return candidate[:80]
            for value in data.values():
                candidate = cls._find_nickname_in_json(value)
                if candidate:
                    return candidate
        elif isinstance(data, list):
            for value in data:
                candidate = cls._find_nickname_in_json(value)
                if candidate:
                    return candidate
        return ""

    @staticmethod
    def _decode_text(value: str) -> str:
        if value is None:
            return ""
        value = str(value)
        if re.search(r"\\u[0-9a-fA-F]{4}|\\x[0-9a-fA-F]{2}|\\/", value):
            try:
                value = bytes(value, "utf-8").decode("unicode_escape")
            except Exception:
                pass
        value = value.replace(r"\/", "/")
        return html.unescape(value).strip()

    @staticmethod
    def _format_timestamp(value: Any) -> str:
        try:
            raw = str(value).strip()
            if not raw:
                return ""
            ts = int(raw[:10])
            if ts <= 0:
                return ""
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(value or "")

    def _item_from_json_object(self, data: dict[str, Any], now: str) -> DouyinContentItem | None:
        item_id = ""
        for key in ITEM_ID_KEYS:
            value = data.get(key)
            if value is not None and re.fullmatch(r"\d{8,}", str(value)):
                item_id = str(value)
                break
        if not item_id:
            return None

        title = ""
        for key in TITLE_KEYS:
            value = data.get(key)
            if isinstance(value, str):
                candidate = re.sub(r"\s+", " ", self._decode_text(value)).strip()
                if candidate and not candidate.startswith(("http://", "https://")):
                    title = candidate[:120]
                    break

        publish_time = ""
        for key in CREATE_TIME_KEYS:
            if key in data:
                publish_time = self._format_timestamp(data.get(key))
                break

        share_url = ""
        for key in ("share_url", "shareUrl", "url"):
            value = data.get(key)
            if isinstance(value, str) and "douyin.com" in value:
                share_url = self._decode_text(value)
                break

        return DouyinContentItem(
            item_id=item_id,
            title=title or f"抖音作品 {item_id}",
            share_url=share_url or f"https://www.douyin.com/video/{item_id}",
            publish_time=publish_time,
            first_seen_time=now,
            last_seen_time=now,
            status="active",
        )

    def _collect_json_items(self, data: Any, now: str, items: list[DouyinContentItem], seen: set[str]) -> None:
        if isinstance(data, dict):
            item = self._item_from_json_object(data, now)
            if item and item.item_id not in seen:
                seen.add(item.item_id)
                items.append(item)
            for value in data.values():
                self._collect_json_items(value, now, items, seen)
        elif isinstance(data, list):
            for value in data:
                self._collect_json_items(value, now, items, seen)

    def _extract_embedded_json_items(self, page_text: str, now: str, items: list[DouyinContentItem], seen: set[str]) -> None:
        scripts = re.findall(r"<script[^>]*>(.*?)</script>", page_text, re.IGNORECASE | re.DOTALL)
        candidates = []
        for script in scripts:
            text = html.unescape(script).strip()
            if not text:
                continue
            if "%7B" in text[:200] or "%5B" in text[:200]:
                text = unquote(text)
            if text.startswith(("{", "[")):
                candidates.append(text)
                continue
            for match in re.finditer(r"(\{[^<]{100,}\})", text, re.DOTALL):
                candidates.append(match.group(1))

        for candidate in candidates[:30]:
            try:
                self._collect_json_items(json.loads(candidate), now, items, seen)
            except Exception:
                continue

    def _extract_item_meta(self, page_text: str, item_id: str) -> tuple[str, str]:
        idx = page_text.find(item_id)
        if idx < 0:
            window = page_text
        else:
            window = page_text[max(0, idx - 2500): idx + 2500]
        title = ""
        publish_time = ""
        for key in TITLE_KEYS:
            m = re.search(rf'"{key}"\s*:\s*"(.*?)"', window, re.DOTALL)
            if m:
                candidate = self._decode_text(m.group(1))
                candidate = re.sub(r"\s+", " ", candidate).strip()
                if candidate and not candidate.startswith("http"):
                    title = candidate[:120]
                    break
        for key in CREATE_TIME_KEYS:
            m = re.search(rf'"{key}"\s*:\s*"?(\d{{10,13}})"?', window)
            if m:
                publish_time = self._format_timestamp(m.group(1))
                break
        return title, publish_time

    def parse_public_profile_items(self, page_text: str) -> list[DouyinContentItem]:
        seen: set[str] = set()
        now = self._now()
        items: list[DouyinContentItem] = []
        self._extract_embedded_json_items(page_text, now, items, seen)

        ids: list[str] = []
        for pattern in ITEM_ID_PATTERNS:
            for item_id in pattern.findall(page_text):
                item_id = str(item_id)
                if item_id not in seen:
                    seen.add(item_id)
                    ids.append(item_id)
        for item_id in ids[:50]:
            title, publish_time = self._extract_item_meta(page_text, item_id)
            items.append(
                DouyinContentItem(
                    item_id=item_id,
                    title=title or f"抖音作品 {item_id}",
                    share_url=f"https://www.douyin.com/video/{item_id}",
                    publish_time=publish_time,
                    first_seen_time=now,
                    last_seen_time=now,
                    status="active",
                )
            )
        return items

    async def fetch_parser_user_posts(self, account: DouyinMonitorAccount) -> list[DouyinContentItem]:
        sec_uid = self.extract_sec_uid(account.homepage_url)
        if not sec_uid:
            return []
        await self._resolve_parser_backend()
        backend = build_douyin_parser_backend(
            self._parser_backend(),
            video_parser=getattr(self.services, "video_parser", None),
            external_base_url=self._external_api_base_url(),
        )
        return self._strip_eager_video_download_urls(await backend.fetch_profile_contents(sec_uid, max_pages=self._parser_max_pages(), count=20))

    async def fetch_external_user_posts(self, account: DouyinMonitorAccount) -> list[DouyinContentItem]:
        """Compatibility alias. The current default backend is the bundled parser."""
        return await self.fetch_parser_user_posts(account)

    @staticmethod
    def _strip_eager_video_download_urls(items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        for item in items:
            if str(item.media_type or "video").lower() not in {"image", "images", "gallery", "note"}:
                item.download_url = ""
        return items

    async def sync_account_works(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "total": 0, "new": 0}
        lock = self._account_scan_lock(account_id)
        if lock.locked():
            return {"success": False, "reason": "该账号已有检测或同步任务正在运行", "total": len(account.items), "new": 0}
        async with lock:
            try:
                items = await self.fetch_parser_user_posts(account)
            except Exception as exc:
                return {"success": False, "reason": f"解析器获取作品失败：{exc}", "total": 0, "new": 0}
            if not items:
                return {
                    "success": False,
                    "reason": (
                        "解析器未返回作品列表。请检查抖音 Cookie、X-Bogus/A_Bogus 签名能力，"
                        "以及该博主主页是否有公开作品。"
                    ),
                    "total": 0,
                    "new": 0,
                }
            new_items = self._merge_detected_items(account, items)
            now = self._now()
            account.last_check_time = now
            account.last_success_time = now
            account.last_error = ""
            account.error_count = 0
            account.aweme_count = max(account.aweme_count, len(items))
            account.last_aweme_count = account.aweme_count
            account.last_new_count = len(new_items)
            account.total_new_count += len(new_items)
            account.status = "已同步作品列表"
            self._apply_account_retention(account)
            self._record_monitor_history(account, True, account.status, len(new_items))
            await self.persist()
            self._write_detection_log(
                f"Synced Douyin works via parser: name={account.display_name or account.douyin_nickname}, "
                f"items={len(items)}, new={len(new_items)}, url={account.homepage_url}"
            )
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
            self._schedule_auto_download(account, new_items)
            return {"success": True, "reason": account.status, "total": len(items), "new": len(new_items)}

    def _merge_detected_items(self, account: DouyinMonitorAccount, detected_items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        for item in detected_items:
            item.image_urls = deduplicate_image_urls(item.image_urls)
        return self._merge_service.merge_detected_items(account, detected_items)

    async def fetch_public_profile(self, account: DouyinMonitorAccount) -> tuple[str, str]:
        proxy = None
        if self.settings.user_config.get("enable_proxy"):
            proxy = self.settings.user_config.get("proxy_address") or None
        async with httpx.AsyncClient(
            headers=self._headers(),
            follow_redirects=True,
            timeout=self._request_timeout(),
            proxy=proxy,
        ) as client:
            response = await client.get(account.homepage_url)
            response.raise_for_status()
            return response.text, str(response.url)

    async def fetch_user_profile_info(self, account: DouyinMonitorAccount) -> dict[str, str]:
        sec_uid = self.extract_sec_uid(account.homepage_url)
        if not sec_uid:
            return {}

        proxy = None
        if self.settings.user_config.get("enable_proxy"):
            proxy = self.settings.user_config.get("proxy_address") or None
        url = f"https://www.douyin.com/web/api/v2/user/info/?sec_uid={sec_uid}"
        async with httpx.AsyncClient(
            headers=self._headers(),
            follow_redirects=True,
            timeout=self._request_timeout(),
            proxy=proxy,
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

        if int(data.get("status_code") or 0) != 0:
            return {}
        user_info = data.get("user_info") or data.get("user") or {}
        if not isinstance(user_info, dict):
            return {}

        nickname = self._decode_text(user_info.get("nickname") or "")
        avatar_url = self._extract_avatar_url(user_info)
        aweme_count = self._parse_int(user_info.get("aweme_count"), -1)
        return {
            "douyin_nickname": nickname[:80],
            "avatar_url": avatar_url,
            "aweme_count": aweme_count,
        }

    @staticmethod
    def _parse_int(value: Any, default: int = 0) -> int:
        try:
            if value is None or value == "":
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _extract_avatar_url(user_info: dict[str, Any]) -> str:
        for key in ("avatar_thumb", "avatar_medium", "avatar_larger", "avatar_168x168", "avatar_300x300"):
            avatar = user_info.get(key)
            if isinstance(avatar, dict):
                url_list = avatar.get("url_list")
                if isinstance(url_list, list):
                    for url in url_list:
                        if isinstance(url, str) and url.startswith(("http://", "https://")):
                            return html.unescape(url)
                uri = avatar.get("uri")
                if isinstance(uri, str) and uri.startswith(("http://", "https://")):
                    return html.unescape(uri)
        for key in ("avatar_url", "avatar"):
            value = user_info.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                return html.unescape(value)
        return ""

    async def check_account(self, account_id: str, notify: bool = True) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        lock = self._account_scan_lock(account_id)
        if lock.locked():
            return {"success": False, "reason": "该账号已有检测或同步任务正在运行", "new_items": []}
        async with lock:
            account.status = "检测中"
            account.last_check_time = self._now()
            account.last_error = ""
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checking", "account_id": account_id})
            try:
                page_text, final_url = await self.fetch_public_profile(account)
                if final_url:
                    try:
                        account.homepage_url = self.normalize_homepage_url(final_url)
                    except Exception:
                        pass
                douyin_nickname = self._extract_douyin_nickname(page_text)
                if douyin_nickname:
                    account.douyin_nickname = douyin_nickname
                    self._auto_fill_display_name(account)
                try:
                    profile_info = await self.fetch_user_profile_info(account)
                except Exception as exc:
                    profile_info = {}
                    logger.debug(f"Douyin user profile info fallback failed: {exc}")
                if profile_info.get("douyin_nickname"):
                    account.douyin_nickname = profile_info["douyin_nickname"]
                    self._auto_fill_display_name(account)
                if profile_info.get("avatar_url"):
                    account.avatar_url = profile_info["avatar_url"]
                profile_aweme_count = self._parse_int(profile_info.get("aweme_count"), -1)
                detected_items = []
                if getattr(account, "auto_sync_enabled", True):
                    try:
                        detected_items = await self.fetch_parser_user_posts(account)
                    except Exception as exc:
                        logger.debug(f"Douyin parser user posts fallback failed: {exc}")
                if not detected_items:
                    detected_items = self.parse_public_profile_items(page_text)
                if not detected_items:
                    if profile_aweme_count >= 0:
                        return await self._handle_profile_count_check(account, profile_aweme_count, notify=notify)
                    return await self._handle_no_public_items_check(account)

                now = self._now()
                first_success = not account.known_item_ids and not account.items
                new_items = self._merge_detected_items(account, detected_items)
                account.aweme_count = profile_aweme_count if profile_aweme_count >= 0 else max(account.aweme_count, len(account.known_item_ids))
                account.last_aweme_count = account.aweme_count
                account.last_success_time = now
                account.error_count = 0
                account.last_new_count = len(new_items)
                account.total_new_count += len(new_items)
                account.status = "已发现新作品" if new_items else ("已建立初始基线" if first_success else "无更新")
                self._apply_account_retention(account)
                self._record_monitor_history(account, True, account.status, len(new_items))
                await self.persist()
                self._write_detection_log(
                    f"Checked Douyin account: name={account.display_name}, items={len(detected_items)}, new={len(new_items)}, url={account.homepage_url}"
                )
                if notify and account.notify_enabled and new_items:
                    await self._notify_new_items(account, new_items)
                self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
                self._schedule_auto_download(account, new_items)
                return {"success": True, "reason": account.status, "new_items": [item.to_dict() for item in new_items]}
            except httpx.HTTPStatusError as exc:
                reason = f"HTTP {exc.response.status_code}：公开主页请求失败"
            except httpx.TimeoutException:
                reason = "网络超时：公开主页请求超时"
            except httpx.RequestError as exc:
                reason = f"网络错误：{exc}"
            except Exception as exc:
                reason = f"检测异常：{exc}"
            account.status = "检测异常"
            account.last_error = sanitize_text(reason)
            account.error_count += 1
            self._auto_pause_if_needed(account)
            self._record_monitor_history(account, False, account.last_error, 0)
            await self.persist()
            self._write_detection_log(f"Check failed: account={account.display_name}, error={reason}, url={account.homepage_url}")
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
            return {"success": False, "reason": account.last_error, "new_items": []}

    async def _notify_new_items(self, account: DouyinMonitorAccount, new_items: list[DouyinContentItem]) -> None:
        if str(getattr(account, "notify_mode", "desktop") or "desktop") != "desktop":
            return
        top_item = new_items[0]
        title = f"抖音用户更新：{account.display_name or account.douyin_nickname or '抖音用户'}"
        message = f"发现 {len(new_items)} 个新作品：{top_item.title or top_item.item_id}"
        self.services.broadcast_snack(message, duration=5000, show_close_icon=True)
        self._write_detection_log(f"New Douyin content notification: {title} / {message}")
        # Desktop notification only when a UI session is hidden/minimized.
        for bridge in self.services.snapshot_bridges():
            try:
                app = bridge
                from ...messages.desktop_notify import send_notification, should_push_notification

                if should_push_notification(app):
                    send_notification(title, message, timeout=10)
            except Exception as exc:
                logger.debug(f"Douyin desktop notification skipped: {exc}")

    def _schedule_auto_download(self, account: DouyinMonitorAccount, new_items: list[DouyinContentItem]) -> None:
        policy = str(getattr(account, "auto_download_policy", "none") or "none")
        if policy == "none" or not new_items:
            return
        item_ids = [item.item_id for item in new_items if self._auto_download_matches(policy, item)]
        if not item_ids:
            return

        async def run_auto_download() -> None:
            success = 0
            failed = 0
            task_center = getattr(self.services, "task_center", None)
            task_id = (
                task_center.start(
                    f"自动下载：{account.display_name or account.douyin_nickname or account.account_id}",
                    "自动下载",
                    total=len(item_ids),
                    retry_action="content_download_items",
                    retry_payload={"account_id": account.account_id, "item_ids": item_ids},
                )
                if task_center
                else None
            )
            for index, item_id in enumerate(item_ids, start=1):
                result = await self.download_item(account.account_id, item_id, priority="background")
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
                if task_center and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"自动下载进度：{index}/{len(item_ids)}，成功 {success}，失败 {failed}",
                    )
            if task_center and task_id:
                task_center.finish(task_id, success=failed == 0, detail=f"自动下载完成：成功 {success}，失败 {failed}")
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "auto_download", "account_id": account.account_id})

        try:
            asyncio.create_task(run_auto_download())
        except RuntimeError:
            logger.debug("Auto download skipped: no running event loop")

    def _auto_download_matches(self, policy: str, item: DouyinContentItem) -> bool:
        if policy == "all":
            return item.status != "count_only"
        if policy == "gallery":
            return self._is_gallery_item(item)
        if policy == "video":
            return item.status != "count_only" and not self._is_gallery_item(item)
        return False

    async def download_item(self, account_id: str, item_id: str, priority: str = "foreground") -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if self._is_gallery_item(item):
            return await self._download_gallery_with_parsed_downloader(account, item, priority=priority)

        existing_path = self._existing_downloaded_video_path(account, item)
        if existing_path:
            item.status = "downloaded"
            await self.persist()
            return {"success": True, "reason": "文件已存在", "path": existing_path}

        should_refresh_video_url = bool(item.download_url) and self._is_expiring_douyin_video_url(item.download_url)
        if (not item.download_url and not item.image_urls) or should_refresh_video_url:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()
            elif should_refresh_video_url:
                item.download_url = ""
                item.status = "download_failed"
                await self.persist()
                return {"success": False, "reason": "解析器未返回可下载视频，作品可能已下架、不可见或被接口过滤"}
        if not item.download_url:
            return {"success": False, "reason": "未获取到下载地址，请检查解析器配置"}

        save_path = self._video_save_path(account, item)
        task_label = item.title or item.item_id

        async def run_download():
            await self._download_file(item.download_url, save_path)
            return save_path

        try:
            path = await self.services.media_task_queue.run(
                "douyin_download",
                task_label,
                run_download,
                priority=priority,
                dedupe_key=save_path,
            )
        except Exception as exc:
            refreshed = await self._resolve_item_download_item(item)
            if refreshed and refreshed.download_url:
                self._apply_resolved_download_item(item, refreshed)
                await self.persist()

                async def retry_download():
                    await self._download_file(item.download_url, save_path)
                    return save_path

                try:
                    path = await self.services.media_task_queue.run(
                        "douyin_download",
                        task_label,
                        retry_download,
                        priority=priority,
                        dedupe_key=save_path,
                    )
                except Exception as retry_exc:
                    item.status = "download_failed"
                    await self.persist()
                    return {"success": False, "reason": f"下载失败：{retry_exc}"}
            else:
                item.status = "download_failed"
                await self.persist()
                return {"success": False, "reason": f"下载失败：{exc}"}
        item.status = "downloaded"
        await self.persist()
        return {"success": True, "reason": "下载完成", "path": path}

    async def resolve_item_preview(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if self._is_gallery_item(item):
            return {"success": False, "reason": "图文作品不支持视频浏览，请打开作品或下载图片"}

        existing_path = self._existing_downloaded_video_path(account, item)
        if existing_path:
            item.status = "downloaded"
            await self.persist()
            return {
                "success": True,
                "reason": "使用已下载文件预览",
                "url": existing_path,
                "share_url": item.share_url,
                "title": item.title or item.item_id,
                "is_file_path": True,
            }

        should_refresh_video_url = bool(item.download_url) and self._is_expiring_douyin_video_url(item.download_url)
        if not item.download_url or should_refresh_video_url:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()
            elif should_refresh_video_url:
                item.download_url = ""
                await self.persist()

        if self._is_gallery_item(item):
            return {"success": False, "reason": "图文作品不支持视频浏览，请打开作品或下载图片"}
        if not item.download_url:
            return {"success": False, "reason": "未获取到视频浏览地址，请检查解析器配置"}
        try:
            cache = await self.services.parsed_media_downloader.cache_video_preview(
                item.download_url,
                f"{account.account_id}_{item.item_id}",
                title=item.title or item.item_id or "视频预览",
                priority="foreground",
            )
            if cache.get("success") and cache.get("path"):
                return {
                    "success": True,
                    "reason": "使用本地预览缓存",
                    "url": str(cache["path"]),
                    "share_url": item.share_url,
                    "title": item.title or item.item_id,
                    "is_file_path": True,
                    "copy_source_url": item.download_url,
                }
        except Exception as exc:
            logger.debug(f"Cache content video preview failed: {exc}")
        return {
            "success": True,
            "reason": "已获取视频浏览地址",
            "url": item.download_url,
            "share_url": item.share_url,
            "title": item.title or item.item_id,
            "is_file_path": False,
        }

    async def resolve_item_image_preview(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if not self._is_gallery_item(item):
            return {"success": False, "reason": "当前作品不是图文作品"}

        item.image_urls = deduplicate_image_urls(item.image_urls)
        if not item.image_urls:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()

        if not item.image_urls:
            return {"success": False, "reason": "未获取到图片地址，请打开作品或重新同步"}
        return {
            "success": True,
            "reason": "已获取图片预览地址",
            "urls": deduplicate_image_urls(item.image_urls),
            "share_url": item.share_url,
            "title": item.title or item.item_id,
            "item_id": item.item_id,
        }

    @staticmethod
    def _apply_resolved_download_item(item: DouyinContentItem, resolved: DouyinContentItem) -> None:
        item.download_url = resolved.download_url or item.download_url
        item.cover_url = resolved.cover_url or item.cover_url
        item.media_type = resolved.media_type or item.media_type
        item.image_urls = deduplicate_image_urls(resolved.image_urls or item.image_urls)

    @staticmethod
    def _is_gallery_item(item: DouyinContentItem) -> bool:
        return bool(item.image_urls) or str(item.media_type or "").lower() in {"image", "images", "gallery", "note"}

    @staticmethod
    def _is_expiring_douyin_video_url(url: str) -> bool:
        hostname = (urlsplit(str(url or "")).hostname or "").lower()
        return hostname.endswith("douyinvod.com")

    async def _download_gallery_with_parsed_downloader(self, account: DouyinMonitorAccount, item: DouyinContentItem, priority: str = "foreground") -> dict[str, Any]:
        item.image_urls = deduplicate_image_urls(item.image_urls)
        if not item.image_urls:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()

        if not item.image_urls:
            item.status = "download_failed"
            await self.persist()
            return {"success": False, "reason": "未获取到图集图片地址，请检查解析器配置"}

        item.image_urls = deduplicate_image_urls(item.image_urls)
        parsed_item = self._to_parsed_media_result(account, item, priority=priority)
        try:
            result = await self.services.parsed_media_downloader.download(parsed_item)
        except Exception as exc:
            refreshed = await self._resolve_item_download_item(item)
            if refreshed and refreshed.image_urls:
                self._apply_resolved_download_item(item, refreshed)
                await self.persist()
                parsed_item = self._to_parsed_media_result(account, item, priority=priority)
                try:
                    result = await self.services.parsed_media_downloader.download(parsed_item)
                except Exception as retry_exc:
                    item.status = "download_failed"
                    await self.persist()
                    return {"success": False, "reason": f"图集下载失败：{retry_exc}"}
            else:
                item.status = "download_failed"
                await self.persist()
                return {"success": False, "reason": f"图集下载失败：{exc}"}

        item.status = "downloaded" if result.get("success") else "download_failed"
        await self.persist()
        return result

    def _to_parsed_media_result(self, account: DouyinMonitorAccount, item: DouyinContentItem, priority: str = "foreground") -> ParsedVideoResult:
        return ParsedVideoResult(
            source_url=item.share_url,
            media_type="image",
            platform="douyin",
            item_id=item.item_id,
            description=item.title or item.item_id,
            author_nickname=account.display_name or account.douyin_nickname,
            no_watermark_url="",
            watermark_url="",
            image_urls=deduplicate_image_urls(item.image_urls),
            watermark_image_urls=[],
            raw_data={
                "download_base_dir": self._content_download_dir(account),
                "download_filename": self._media_filename(account, item),
                "download_priority": priority,
            },
        )

    async def download_all_items(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "total": 0, "success_count": 0, "failed_count": 0}
        if not account.items:
            sync_result = await self.sync_account_works(account_id)
            if not sync_result.get("success"):
                return {"success": False, "reason": sync_result.get("reason"), "total": 0, "success_count": 0, "failed_count": 0}
        results = []
        for item in list(account.items):
            if item.status == "count_only":
                continue
            results.append(await self.download_item(account_id, item.item_id))
            await asyncio.sleep(0.5)
        success_count = len([r for r in results if r.get("success")])
        failed_count = len(results) - success_count
        return {
            "success": failed_count == 0,
            "reason": f"下载完成：成功 {success_count}，失败 {failed_count}",
            "total": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
        }

    async def _resolve_item_download_item(self, item: DouyinContentItem) -> DouyinContentItem | None:
        try:
            source_url = item.share_url or f"https://www.douyin.com/video/{item.item_id}"
            backend = build_douyin_parser_backend(
                self._parser_backend(),
                video_parser=getattr(self.services, "video_parser", None),
                external_base_url=self._external_api_base_url(),
            )
            data = await backend.parse_url(source_url)
            parsed = self.services.video_parser_result_from_api_data(source_url, data)
            return self._content_item_from_parsed_result(item, parsed)
        except Exception as exc:
            logger.debug(f"Resolve Douyin download url failed with internal parser: item={item.item_id}, error={exc}")
            return None

    @staticmethod
    def _content_item_from_parsed_result(item: DouyinContentItem, parsed: Any) -> DouyinContentItem:
        return DouyinContentItem(
            item_id=parsed.item_id or item.item_id,
            title=parsed.description or item.title,
            share_url=parsed.source_url or item.share_url,
            download_url=parsed.no_watermark_url or parsed.watermark_url or item.download_url,
            cover_url=item.cover_url,
            media_type=parsed.media_type or item.media_type,
            image_urls=deduplicate_image_urls(parsed.image_urls or item.image_urls),
            publish_time=item.publish_time,
            first_seen_time=item.first_seen_time,
            last_seen_time=item.last_seen_time,
            status=item.status,
        )

    async def _download_file(self, url: str, save_path: str) -> None:
        headers = {
            "User-Agent": self._headers().get("User-Agent", ""),
            "Referer": "https://www.douyin.com/",
        }
        proxy = self.settings.user_config.get("proxy_address") or None if self.settings.user_config.get("enable_proxy") else None
        recovery = getattr(self.services, "download_recovery_service", None)
        download_id = recovery.start(url=url, save_path=save_path, kind="content_monitor", label=os.path.basename(save_path)) if recovery else ""
        try:
            await download_http_file(
                url,
                save_path,
                headers=headers,
                proxy=proxy,
                timeout=DOWNLOAD_TIMEOUT,
                chunk_size=DOWNLOAD_CHUNK_SIZE,
                progress_interval=self._download_progress_interval(),
                progress_formatter=self._download_progress_text,
                progress_reporter=report_media_task_progress,
                progress_callback=(lambda downloaded, total: recovery.mark_progress(download_id, downloaded, total)) if recovery and download_id else None,
                resume_enabled=self._download_resume_enabled(),
            )
            if recovery and download_id:
                recovery.mark_completed(download_id)
        except asyncio.CancelledError:
            if recovery and download_id:
                recovery.mark_cancelled(download_id)
            raise
        except Exception as exc:
            if recovery and download_id:
                recovery.mark_failed(download_id, str(exc))
            raise

    @classmethod
    def _download_progress_text(cls, downloaded: int, total: int, started: float) -> str:
        elapsed = max(0.1, time.monotonic() - started)
        speed = downloaded / elapsed
        if total > 0:
            percent = min(100.0, downloaded * 100.0 / total)
            return f"下载中：{percent:.1f}%  {cls._format_bytes(downloaded)}/{cls._format_bytes(total)}  {cls._format_bytes(speed)}/s"
        return f"下载中：{cls._format_bytes(downloaded)}  {cls._format_bytes(speed)}/s"

    def _download_progress_interval(self) -> float:
        try:
            value = self.settings.user_config.get("media_download_progress_interval_seconds", 1.5)
            return max(0.5, min(10.0, float(value or 1.5)))
        except (TypeError, ValueError):
            return 1.5

    def _download_resume_enabled(self) -> bool:
        value = self.settings.user_config.get("download_resume_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _format_bytes(value: float) -> str:
        size = float(max(0.0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
            size /= 1024
        return f"{size:.1f}GB"


    async def _handle_profile_count_check(self, account: DouyinMonitorAccount, aweme_count: int, notify: bool = True) -> dict[str, Any]:
        now = self._now()
        previous_count = account.aweme_count if account.aweme_count >= 0 else account.last_aweme_count
        first_success = previous_count < 0 and not account.items and not account.known_item_ids
        delta = max(0, aweme_count - previous_count) if previous_count >= 0 else 0

        account.last_aweme_count = previous_count if previous_count >= 0 else aweme_count
        account.aweme_count = aweme_count
        account.last_success_time = now
        account.error_count = 0
        account.last_error = ""
        account.last_new_count = delta
        account.total_new_count += delta
        account.status = "已发现新作品" if delta else ("已建立初始基线" if first_success else "无更新")

        new_items: list[DouyinContentItem] = []
        if delta:
            item = DouyinContentItem(
                item_id=f"count-{aweme_count}-{int(time.time())}",
                title=f"作品数量增加 {delta} 个（当前 {aweme_count} 个）",
                share_url=account.homepage_url,
                publish_time="",
                first_seen_time=now,
                last_seen_time=now,
                status="count_only",
            )
            account.items.insert(0, item)
            account.items = account.items[:200]
            new_items.append(item)

        self._apply_account_retention(account)
        self._record_monitor_history(account, True, account.status, delta)
        await self.persist()
        self._write_detection_log(
            f"Checked Douyin account by profile count: name={account.display_name or account.douyin_nickname}, "
            f"aweme_count={aweme_count}, previous={previous_count}, new={delta}, url={account.homepage_url}"
        )
        if notify and account.notify_enabled and new_items:
            await self._notify_new_items(account, new_items)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        return {"success": True, "reason": account.status, "new_items": [item.to_dict() for item in new_items]}

    async def _handle_no_public_items_check(self, account: DouyinMonitorAccount) -> dict[str, Any]:
        account.status = "未识别到公开作品"
        account.last_error = "本次检测未从公开主页识别到作品 ID。可能是账号无公开作品、页面结构变化、登录限制或风控。"
        account.last_new_count = 0
        self._record_monitor_history(account, False, account.last_error, 0)
        await self.persist()
        self._write_detection_log(f"No public items detected: account={account.display_name}, url={account.homepage_url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        return {"success": False, "reason": account.last_error, "new_items": []}

    async def check_all_enabled(self) -> dict[str, Any]:
        if self._batch_check_lock.locked():
            return {"total": 0, "results": [], "reason": "已有批量检测任务正在运行"}
        async with self._batch_check_lock:
            return await self._check_all_enabled_locked()

    async def _check_all_enabled_locked(self) -> dict[str, Any]:
        accounts = [account for account in list(self._accounts) if account.monitor_enabled]
        results = []
        for account in accounts:
            result = await self.check_account(account.account_id, notify=True)
            results.append({"account_id": account.account_id, **result})
            await asyncio.sleep(self._between_users_delay())
        return {"total": len(results), "results": results}

    async def check_due_enabled(self) -> dict[str, Any]:
        if self._batch_check_lock.locked():
            return {"total": 0, "results": [], "reason": "已有批量检测任务正在运行"}
        async with self._batch_check_lock:
            now_ts = time.time()
            accounts = [account for account in list(self._accounts) if self._account_check_due(account, now_ts)]
            results = []
            for account in accounts:
                result = await self.check_account(account.account_id, notify=True)
                results.append({"account_id": account.account_id, **result})
                await asyncio.sleep(self._between_users_delay())
            return {"total": len(results), "results": results}

    @classmethod
    def is_periodic_task_running(cls) -> bool:
        return False

    @classmethod
    def set_periodic_task_running(cls, value: bool = True) -> None:
        return None

    async def setup_periodic_check(self) -> None:
        self._periodic_task = await self._scheduler.start()

    async def _periodic_check_once(self) -> None:
        if self._batch_check_lock.locked():
            logger.info("Douyin content monitor periodic check skipped: batch check already running")
            return
        await self.check_due_enabled()

    async def stop_periodic_check(self) -> None:
        task = self._periodic_task
        self._periodic_task = None
        await self._scheduler.stop()

    def snapshot(self) -> dict[str, Any]:
        return {
            "account_count": len(self._accounts),
            "enabled_count": len([a for a in self._accounts if a.monitor_enabled]),
            "last_check_time": max([a.last_check_time for a in self._accounts if a.last_check_time] or [""]),
            "log_path": sanitize_text(self.log_path),
        }
