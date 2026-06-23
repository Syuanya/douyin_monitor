from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

from ..media.image_urls import deduplicate_image_urls

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

