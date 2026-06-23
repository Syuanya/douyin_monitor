from __future__ import annotations

from .monitor_common import *


class ContentMonitorProfileParserMixin:
    @staticmethod
    def extract_sec_uid(homepage_url: str) -> str:
        parts = urlsplit(str(homepage_url or ""))
        match = re.search(r"/user/([^/?#]+)", parts.path)
        return match.group(1) if match else ""

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

    def _normalize_parser_items(self, items: list[Any]) -> list[DouyinContentItem]:
        normalized: list[DouyinContentItem] = []
        seen: set[str] = set()
        now = self._now()
        for raw in items or []:
            item: DouyinContentItem | None
            if isinstance(raw, DouyinContentItem):
                item = raw
            elif isinstance(raw, dict):
                item = DouyinContentItem.from_dict(raw)
                if not item.item_id:
                    item = self._item_from_json_object(raw, now)
            else:
                item = None
            if not item or not item.item_id or item.item_id in seen:
                continue
            seen.add(item.item_id)
            normalized.append(item)
        return normalized

    @staticmethod
    def _strip_eager_video_download_urls(items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        for item in items:
            if str(item.media_type or "video").lower() not in {"image", "images", "gallery", "note"}:
                item.download_url = ""
        return items

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
