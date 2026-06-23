from __future__ import annotations

import asyncio
from typing import Any

from .douyin_user_posts_client import DouyinUserPostsMixin
from .parser_common import ParserCallable
from .parser_cookie_pool import ParserCookiePoolMixin
from .parser_models import ParseDownloadEvent, ParseFailure, ParseProgress, ParsedVideoResult, VideoParseBatchResult, normalize_work_url
from .parser_runtime import ParserRuntimeMixin
from .url_extractor import UrlExtractorMixin


class VideoParserService(
    ParserRuntimeMixin,
    ParserCookiePoolMixin,
    DouyinUserPostsMixin,
    UrlExtractorMixin,
):
    """Facade for video parsing.

    Parsing orchestration, URL extraction, cookie-pool handling and Douyin user
    post pagination are split into focused modules while this class preserves
    the existing public API used by the UI.
    """

    DEFAULT_PARSE_CONCURRENCY = 4

    def __init__(self, run_path: str = "", parser: ParserCallable | None = None, parse_concurrency: int = DEFAULT_PARSE_CONCURRENCY):
        self.run_path = run_path
        self._parser = parser
        try:
            self.parse_concurrency = max(1, int(parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        except (TypeError, ValueError):
            self.parse_concurrency = self.DEFAULT_PARSE_CONCURRENCY
        self.parse_batch_size = 20
        self._hybrid_crawler: Any | None = None
        self._douyin_web_crawler: Any | None = None
        self._parse_locks: dict[int, asyncio.Semaphore] = {}
        self._inflight_parses: dict[tuple[int, str], asyncio.Task] = {}
        self._parse_cache: dict[str, tuple[float, dict[str, Any]]] = {}
        self.parse_cache_ttl_seconds = 180.0
        self.cookie_health_store: Any | None = None
        self.request_limiter: Any | None = None
        self._cookie_pools: dict[str, list[str]] = {"douyin": [], "tiktok": []}
        self._cookie_cursors: dict[str, int] = {"douyin": 0, "tiktok": 0}
        self._cookie_health: dict[str, dict[str, dict[str, float]]] = {"douyin": {}, "tiktok": {}}
        self._cookie_cooldowns: dict[str, dict[str, float]] = {"douyin": {}, "tiktok": {}}


__all__ = [
    "ParseDownloadEvent",
    "ParseFailure",
    "ParseProgress",
    "ParsedVideoResult",
    "VideoParseBatchResult",
    "VideoParserService",
    "normalize_work_url",
]
