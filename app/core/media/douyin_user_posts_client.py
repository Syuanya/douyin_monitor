from __future__ import annotations

from .parser_common import *


class DouyinUserPostsMixin:
    async def fetch_all_douyin_user_posts(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        from app.core.content_monitor.douyin_api_client import DouyinExternalApiClient

        crawler = self._get_douyin_web_crawler()
        cursor = 0
        seen: set[str] = set()
        items: list[Any] = []
        for _ in range(max(1, max_pages)):
            cookie = self.next_cookie("douyin")
            try:
                page = await crawler.fetch_user_post_videos(
                    sec_user_id=sec_user_id,
                    max_cursor=cursor,
                    count=count,
                    cookie=cookie or None,
                )
                if cookie and hasattr(self, "record_cookie_success"):
                    self.record_cookie_success("douyin", cookie)
            except Exception as exc:
                if cookie and hasattr(self, "record_cookie_failure"):
                    self.record_cookie_failure("douyin", cookie, str(exc))
                raise
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


def _parse_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
