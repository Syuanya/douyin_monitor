from __future__ import annotations

import html
import re
from typing import Any
from urllib.parse import urljoin, urlsplit

import httpx

from .douyin_content_monitor import DouyinContentItem
from ..media.image_urls import deduplicate_image_urls


class DouyinExternalApiClient:
    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = str(base_url or "").strip().rstrip("/")
        self.timeout = timeout

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", path.lstrip("/"))

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(self._url(path), params=params or {})
            response.raise_for_status()
            payload = response.json()
        if isinstance(payload, dict) and "data" in payload:
            return payload.get("data")
        return payload

    async def fetch_user_post_page(self, sec_user_id: str, max_cursor: int = 0, count: int = 20) -> dict[str, Any]:
        data = await self._get(
            "/api/douyin/web/fetch_user_post_videos",
            {"sec_user_id": sec_user_id, "max_cursor": max_cursor, "count": count},
        )
        return data if isinstance(data, dict) else {}

    async def fetch_one_video(self, aweme_id: str) -> dict[str, Any]:
        data = await self._get("/api/douyin/web/fetch_one_video", {"aweme_id": aweme_id})
        return data if isinstance(data, dict) else {}

    async def fetch_all_user_posts(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[DouyinContentItem]:
        cursor = 0
        seen: set[str] = set()
        items: list[DouyinContentItem] = []
        for _ in range(max(1, max_pages)):
            page = await self.fetch_user_post_page(sec_user_id, cursor, count)
            awemes = self._extract_aweme_list(page)
            for aweme in awemes:
                item = self.parse_aweme_item(aweme)
                if item and item.item_id not in seen:
                    seen.add(item.item_id)
                    items.append(item)
            next_cursor = self._parse_int(page.get("max_cursor") or page.get("cursor") or page.get("next_cursor"), cursor)
            has_more = page.get("has_more")
            if has_more in (0, False) or not awemes or next_cursor == cursor:
                break
            cursor = next_cursor
        return items

    @classmethod
    def parse_aweme_item(cls, data: dict[str, Any]) -> DouyinContentItem | None:
        aweme = cls._unwrap_aweme(data)
        item_id = cls._first_str(aweme, ("aweme_id", "awemeId", "item_id", "itemId", "id"))
        if not item_id or not re.fullmatch(r"\d{8,}", item_id):
            return None
        title = cls._first_str(aweme, ("desc", "caption", "title", "text")) or f"抖音作品 {item_id}"
        media_type, image_urls = cls._extract_image_urls(aweme)
        share_url = cls._find_first_url(
            aweme,
            preferred_keys=("share_url", "shareUrl", "uri"),
            contains=("douyin.com",),
        ) or f"https://www.douyin.com/{'note' if media_type == 'image' else 'video'}/{item_id}"
        download_url = image_urls[0] if image_urls else cls._extract_download_url(aweme)
        cover_url = (image_urls[0] if image_urls else "") or cls._extract_cover_url(aweme)
        publish_time = ""
        create_time = aweme.get("create_time") or aweme.get("createTime") or aweme.get("publish_time")
        if create_time:
            try:
                from datetime import datetime

                publish_time = datetime.fromtimestamp(int(str(create_time)[:10])).strftime("%Y-%m-%d %H:%M:%S")
            except Exception:
                publish_time = str(create_time)
        return DouyinContentItem(
            item_id=item_id,
            title=html.unescape(str(title)).strip()[:120],
            share_url=share_url,
            download_url=download_url,
            cover_url=cover_url,
            media_type=media_type,
            image_urls=image_urls,
            publish_time=publish_time,
            status="active",
        )

    @classmethod
    def _extract_aweme_list(cls, data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            for key in ("aweme_list", "awemeList", "awemes", "items", "list"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
            for value in data.values():
                found = cls._extract_aweme_list(value)
                if found:
                    return found
        return []

    @staticmethod
    def _unwrap_aweme(data: dict[str, Any]) -> dict[str, Any]:
        for key in ("aweme_detail", "awemeDetail", "aweme"):
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return data

    @staticmethod
    def _parse_int(value: Any, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @classmethod
    def _first_str(cls, data: dict[str, Any], keys: tuple[str, ...]) -> str:
        for key in keys:
            value = data.get(key)
            if value is not None:
                return str(value)
        return ""

    @classmethod
    def _extract_download_url(cls, aweme: dict[str, Any]) -> str:
        candidates: list[str] = []
        for key in ("nwm_video_url", "no_watermark_url", "download_url", "video_url", "play_url"):
            value = aweme.get(key)
            if isinstance(value, str) and value.startswith(("http://", "https://")):
                candidates.append(html.unescape(value))
        video = aweme.get("video")
        if isinstance(video, dict):
            for key in ("play_addr", "download_addr", "play_addr_h264", "bit_rate"):
                value = video.get(key)
                candidates.extend(cls._find_urls(value, contains=("http",)))
        candidates.extend(cls._find_urls(aweme, preferred_keys=("url_list",), contains=("http",)))
        return cls._prefer_direct_video_url(candidates)

    @classmethod
    def _extract_image_urls(cls, aweme: dict[str, Any]) -> tuple[str, list[str]]:
        containers: list[Any] = []
        for key in ("image_post_info", "images", "image_list", "image_infos", "images_info"):
            value = aweme.get(key)
            if value:
                containers.append(value)
        image_post_info = aweme.get("image_post_info")
        if isinstance(image_post_info, dict):
            for key in ("images", "image_list", "image_infos"):
                value = image_post_info.get(key)
                if value:
                    containers.append(value)

        urls: list[str] = []
        for container in containers:
            for url in cls._collect_image_urls(container):
                if url not in urls:
                    urls.append(url)

        aweme_type = str(aweme.get("aweme_type") or aweme.get("awemeType") or aweme.get("type") or "").lower()
        media_type = "image" if urls or aweme_type in {"2", "68", "image", "images", "gallery", "note"} else "video"
        return media_type, deduplicate_image_urls(urls)

    @classmethod
    def _collect_image_urls(cls, data: Any) -> list[str]:
        if isinstance(data, str):
            value = html.unescape(data)
            if value.startswith(("http://", "https://")):
                return [value]
            return []
        if isinstance(data, list):
            urls: list[str] = []
            for item in data:
                for url in cls._collect_image_urls(item):
                    if url not in urls:
                        urls.append(url)
            return urls
        if isinstance(data, dict):
            urls: list[str] = []
            preferred_keys = (
                "images",
                "image_list",
                "image_infos",
                "watermark_free_download_url_list",
                "url_list",
                "urlList",
                "origin_image",
                "originImage",
                "display_image",
                "displayImage",
                "download_url",
                "downloadUrl",
                "large_image",
                "largeImage",
                "image",
            )
            for key in preferred_keys:
                value = data.get(key)
                found = cls._collect_image_urls(value)
                if found:
                    return found
            for value in data.values():
                for url in cls._collect_image_urls(value):
                    if url not in urls:
                        urls.append(url)
            return urls
        return []

    @classmethod
    def _extract_cover_url(cls, aweme: dict[str, Any]) -> str:
        video = aweme.get("video")
        if isinstance(video, dict):
            for key in ("cover", "origin_cover", "dynamic_cover"):
                found = cls._find_first_url(video.get(key), contains=("http",))
                if found:
                    return found
        return ""

    @classmethod
    def _find_first_url(
        cls,
        data: Any,
        preferred_keys: tuple[str, ...] = (),
        contains: tuple[str, ...] = ("http",),
    ) -> str:
        if isinstance(data, str):
            value = html.unescape(data)
            if value.startswith(("http://", "https://")) and all(token in value for token in contains if token != "http"):
                return value
            return ""
        if isinstance(data, list):
            for item in data:
                found = cls._find_first_url(item, preferred_keys, contains)
                if found:
                    return found
        if isinstance(data, dict):
            for key in preferred_keys:
                found = cls._find_first_url(data.get(key), preferred_keys, contains)
                if found:
                    return found
            for value in data.values():
                found = cls._find_first_url(value, preferred_keys, contains)
                if found:
                    return found
        return ""

    @classmethod
    def _find_urls(
        cls,
        data: Any,
        preferred_keys: tuple[str, ...] = (),
        contains: tuple[str, ...] = ("http",),
    ) -> list[str]:
        if isinstance(data, str):
            value = html.unescape(data)
            if value.startswith(("http://", "https://")) and all(token in value for token in contains if token != "http"):
                return [value]
            return []
        if isinstance(data, list):
            urls: list[str] = []
            for item in data:
                for url in cls._find_urls(item, preferred_keys, contains):
                    if url not in urls:
                        urls.append(url)
            return urls
        if isinstance(data, dict):
            urls: list[str] = []
            for key in preferred_keys:
                for url in cls._find_urls(data.get(key), preferred_keys, contains):
                    if url not in urls:
                        urls.append(url)
            if urls:
                return urls
            for value in data.values():
                for url in cls._find_urls(value, preferred_keys, contains):
                    if url not in urls:
                        urls.append(url)
            return urls
        return []

    @classmethod
    def _prefer_direct_video_url(cls, urls: list[str]) -> str:
        clean_urls = [url for url in urls if url]
        if not clean_urls:
            return ""
        direct_urls = [url for url in clean_urls if not cls._is_douyin_redirect_play_url(url)]
        return direct_urls[0] if direct_urls else clean_urls[0]

    @staticmethod
    def _is_douyin_redirect_play_url(url: str) -> bool:
        try:
            parts = urlsplit(url)
        except Exception:
            return False
        return (parts.hostname or "").lower() == "aweme.snssdk.com" and parts.path.startswith("/aweme/v1/play")
