from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .parser_common import *


class UrlExtractorMixin:
    URL_RE = re.compile(r"https?://[^\s<>'\"，。；、]+", re.IGNORECASE)
    TRAILING_PUNCTUATION = ".,;:!?)]}）】》、，。；：！？"
    DIRECT_WORK_RE = re.compile(r"/(?:video|note|discover|share/video)/(\d{8,})", re.IGNORECASE)

    @classmethod
    def extract_urls(cls, text: str) -> list[str]:
        """Extract and aggressively dedupe share/work URLs.

        Deduping uses, in order, a direct aweme/note id when present, the
        normalized URL without tracking query/fragment, and finally the raw URL.
        Short-links are still preserved because resolving them requires network.
        """

        urls: list[str] = []
        seen: set[str] = set()
        for match in cls.URL_RE.findall(text or ""):
            url = match.rstrip(cls.TRAILING_PUNCTUATION)
            if not url:
                continue
            key = cls._dedupe_key(url)
            if key in seen:
                continue
            seen.add(key)
            urls.append(url)
        return urls

    @classmethod
    def _dedupe_key(cls, url: str) -> str:
        text = str(url or "").strip()
        try:
            parts = urlsplit(text)
        except Exception:
            return text
        host = (parts.netloc or "").lower()
        path = parts.path.rstrip("/") or "/"
        match = cls.DIRECT_WORK_RE.search(path)
        if match:
            platform = "douyin" if "douyin" in host else "tiktok" if "tiktok" in host else host
            return f"{platform}:item:{match.group(1)}"
        # Drop query/fragment tracking for ordinary long links; keep short-link
        # paths because their path token is the useful id.
        return urlunsplit((parts.scheme.lower() or "https", host, path, "", ""))
