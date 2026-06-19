from __future__ import annotations

import asyncio
import inspect
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

import yaml

from ..parser.risk_model import classify_parser_failure
from .cookie_utils import sanitize_cookie_header
from .image_urls import deduplicate_image_urls


ParserCallable = Callable[..., dict[str, Any] | Awaitable[dict[str, Any]]]


@dataclass(slots=True)
class ParsedVideoResult:
    source_url: str
    media_type: str
    platform: str
    item_id: str
    description: str = ""
    author_nickname: str = ""
    author_id: str = ""
    no_watermark_url: str = ""
    watermark_url: str = ""
    image_urls: list[str] = field(default_factory=list)
    watermark_image_urls: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_api_data(cls, source_url: str, data: dict[str, Any]) -> "ParsedVideoResult":
        author = data.get("author") if isinstance(data.get("author"), dict) else {}
        video_data = data.get("video_data") if isinstance(data.get("video_data"), dict) else {}
        image_data = data.get("image_data") if isinstance(data.get("image_data"), dict) else {}
        no_watermark_url = _prefer_direct_video_url(
            video_data.get("nwm_video_url_HQ"),
            video_data.get("nwm_video_url"),
        )
        watermark_url = _prefer_direct_video_url(
            video_data.get("wm_video_url_HQ"),
            video_data.get("wm_video_url"),
        )
        return cls(
            source_url=normalize_work_url(source_url),
            media_type=str(data.get("type") or "video"),
            platform=str(data.get("platform") or ""),
            item_id=str(data.get("aweme_id") or ""),
            description=str(data.get("desc") or ""),
            author_nickname=str(author.get("nickname") or ""),
            author_id=str(author.get("unique_id") or author.get("short_id") or author.get("uid") or ""),
            no_watermark_url=no_watermark_url,
            watermark_url=watermark_url,
            image_urls=deduplicate_image_urls(_string_list(image_data.get("no_watermark_image_list"))),
            watermark_image_urls=deduplicate_image_urls(_string_list(image_data.get("watermark_image_list"))),
            raw_data=data,
        )

    @property
    def primary_media_url(self) -> str:
        if self.media_type == "image" and self.image_urls:
            return self.image_urls[0]
        return self.no_watermark_url or self.watermark_url


@dataclass(slots=True)
class ParseFailure:
    source_url: str
    reason: str
    category: str = "parser_error"
    retryable: bool = True
    user_action_required: bool = False
    next_step: str = ""


@dataclass(slots=True)
class VideoParseBatchResult:
    input_text: str
    urls: list[str]
    successes: list[ParsedVideoResult] = field(default_factory=list)
    failures: list[ParseFailure] = field(default_factory=list)

    @property
    def success_count(self) -> int:
        return len(self.successes)

    @property
    def failed_count(self) -> int:
        return len(self.failures)

    @property
    def total_count(self) -> int:
        return len(self.urls)


class VideoParserService:
    URL_RE = re.compile(r"https?://[^\s<>'\"，。；、]+", re.IGNORECASE)
    TRAILING_PUNCTUATION = ".,;:!?)]}）】》、，。；：！？"
    DEFAULT_PARSE_CONCURRENCY = 4

    def __init__(self, run_path: str = "", parser: ParserCallable | None = None, parse_concurrency: int = DEFAULT_PARSE_CONCURRENCY):
        self.run_path = run_path
        self._parser = parser
        try:
            self.parse_concurrency = max(1, int(parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        except (TypeError, ValueError):
            self.parse_concurrency = self.DEFAULT_PARSE_CONCURRENCY
        self._hybrid_crawler: Any | None = None
        self._douyin_web_crawler: Any | None = None
        self._parse_locks: dict[int, asyncio.Semaphore] = {}
        self._inflight_parses: dict[tuple[int, str], asyncio.Task] = {}
        self._parse_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.parse_cache_ttl_seconds = 180.0

    def update_cookie(self, platform: str, cookie: str) -> int:
        platform_key = str(platform or "").strip().lower()
        cookie_value = sanitize_cookie_header(cookie)
        if platform_key not in {"douyin", "tiktok"}:
            raise ValueError("platform must be 'douyin' or 'tiktok'")

        changed = 0
        for config_path, token_key, module_name in self._cookie_config_targets(platform_key):
            if self._write_cookie_config(config_path, token_key, cookie_value):
                changed += 1
                self._refresh_loaded_crawler_config(module_name, token_key, cookie_value)
        return changed

    def _cookie_config_targets(self, platform: str) -> list[tuple[Path, str, str]]:
        root = Path(self.run_path or os.getcwd())
        if platform == "douyin":
            return [
                (
                    root / "crawlers" / "douyin" / "web" / "config.yaml",
                    "douyin",
                    "crawlers.douyin.web.web_crawler",
                )
            ]
        return [
            (
                root / "crawlers" / "tiktok" / "web" / "config.yaml",
                "tiktok",
                "crawlers.tiktok.web.web_crawler",
            ),
            (
                root / "crawlers" / "tiktok" / "app" / "config.yaml",
                "tiktok",
                "crawlers.tiktok.app.app_crawler",
            ),
        ]

    @staticmethod
    def _write_cookie_config(config_path: Path, token_key: str, cookie: str) -> bool:
        if not config_path.exists():
            return False
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        token_config = data.setdefault("TokenManager", {}).setdefault(token_key, {})
        headers = token_config.setdefault("headers", {})
        headers["Cookie"] = cookie
        config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return True

    @staticmethod
    def _refresh_loaded_crawler_config(module_name: str, token_key: str, cookie: str) -> None:
        try:
            import sys

            module = sys.modules.get(module_name)
            if not module or not hasattr(module, "config"):
                return
            config = getattr(module, "config")
            config.setdefault("TokenManager", {}).setdefault(token_key, {}).setdefault("headers", {})["Cookie"] = cookie
        except Exception:
            return

    @classmethod
    def extract_urls(cls, text: str) -> list[str]:
        urls: list[str] = []
        seen: set[str] = set()
        for match in cls.URL_RE.findall(text or ""):
            url = match.rstrip(cls.TRAILING_PUNCTUATION)
            if url and url not in seen:
                seen.add(url)
                urls.append(url)
        return urls

    async def parse_text(self, text: str, concurrency: int | None = None) -> VideoParseBatchResult:
        urls = self.extract_urls(text)
        result = VideoParseBatchResult(input_text=text, urls=urls)
        limit = max(1, int(concurrency or self.parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        sem = asyncio.Semaphore(limit)

        async def parse_one(url: str) -> ParsedVideoResult | ParseFailure:
            try:
                async with sem:
                    data = await self.parse_url(url)
                return ParsedVideoResult.from_api_data(url, data)
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                assessment = classify_parser_failure(reason)
                return ParseFailure(
                    source_url=url,
                    reason=reason,
                    category=assessment.category,
                    retryable=assessment.retryable,
                    user_action_required=assessment.user_action_required,
                    next_step=assessment.detail,
                )

        parsed_items = await asyncio.gather(*(parse_one(url) for url in urls))
        for item in parsed_items:
            if isinstance(item, ParsedVideoResult):
                result.successes.append(item)
            else:
                result.failures.append(item)
        return result

    async def parse_url(self, url: str) -> dict[str, Any]:
        key_url = normalize_work_url(url) or str(url or "").strip()
        cached = self._parse_cache.get(key_url)
        if cached is not None and time.time() - cached[0] <= self.parse_cache_ttl_seconds:
            return dict(cached[1])
        loop = asyncio.get_running_loop()
        task_key = (id(loop), key_url)
        existing = self._inflight_parses.get(task_key)
        if existing is not None and not existing.done():
            return dict(await existing)

        task = loop.create_task(self._parse_url_once(url))
        self._inflight_parses[task_key] = task
        try:
            data = dict(await task)
            self._parse_cache[key_url] = (time.time(), dict(data))
            self._trim_parse_cache()
            return data
        finally:
            if self._inflight_parses.get(task_key) is task:
                self._inflight_parses.pop(task_key, None)

    def _trim_parse_cache(self) -> None:
        if len(self._parse_cache) <= 200:
            return
        for key, _value in sorted(self._parse_cache.items(), key=lambda item: item[1][0])[:50]:
            self._parse_cache.pop(key, None)

    async def _parse_url_once(self, url: str) -> dict[str, Any]:
        parser = self._parser or self._get_default_parser()
        async with self._parse_semaphore():
            value = parser(url=url, minimal=True)
            if inspect.isawaitable(value):
                value = await value
        if not isinstance(value, dict):
            raise ValueError("Parser returned an invalid response.")
        return value

    def _parse_semaphore(self) -> asyncio.Semaphore:
        limit = max(1, int(self.parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        loop_id = id(asyncio.get_running_loop())
        sem = self._parse_locks.get(loop_id)
        if sem is None or getattr(sem, "_douyin_parser_limit", None) != limit:
            sem = asyncio.Semaphore(limit)
            setattr(sem, "_douyin_parser_limit", limit)
            self._parse_locks[loop_id] = sem
        return sem

    def _get_default_parser(self) -> ParserCallable:
        if self._hybrid_crawler is None:
            from crawlers.hybrid.hybrid_crawler import HybridCrawler

            self._hybrid_crawler = HybridCrawler()
        return self._hybrid_crawler.hybrid_parsing_single_video

    async def fetch_all_douyin_user_posts(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        from app.core.content_monitor.douyin_api_client import DouyinExternalApiClient

        crawler = self._get_douyin_web_crawler()
        cursor = 0
        seen: set[str] = set()
        items: list[Any] = []
        for _ in range(max(1, max_pages)):
            page = await crawler.fetch_user_post_videos(sec_user_id=sec_user_id, max_cursor=cursor, count=count)
            if not isinstance(page, dict):
                break
            awemes = DouyinExternalApiClient._extract_aweme_list(page)
            for aweme in awemes:
                item = DouyinExternalApiClient.parse_aweme_item(aweme)
                if item and item.item_id not in seen:
                    seen.add(item.item_id)
                    items.append(item)
            next_cursor = _parse_int(page.get("max_cursor") or page.get("cursor") or page.get("next_cursor"), cursor)
            has_more = page.get("has_more")
            if has_more in (0, False) or not awemes or next_cursor == cursor:
                break
            cursor = next_cursor
        return items

    def _get_douyin_web_crawler(self) -> Any:
        if self._douyin_web_crawler is None:
            from crawlers.douyin.web.web_crawler import DouyinWebCrawler

            self._douyin_web_crawler = DouyinWebCrawler()
        return self._douyin_web_crawler


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item]


def normalize_work_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except Exception:
        return text
    if not parts.scheme or not parts.netloc:
        return text
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _prefer_direct_video_url(*values: Any) -> str:
    urls = [str(value) for value in values if isinstance(value, str) and value.startswith(("http://", "https://"))]
    if not urls:
        return ""
    direct_urls = [url for url in urls if not _is_douyin_redirect_play_url(url)]
    return direct_urls[0] if direct_urls else urls[0]


def _is_douyin_redirect_play_url(url: str) -> bool:
    try:
        parts = urlsplit(url)
    except Exception:
        return False
    return (parts.hostname or "").lower() == "aweme.snssdk.com" and parts.path.startswith("/aweme/v1/play")


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
