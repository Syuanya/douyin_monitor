from __future__ import annotations

from urllib.parse import urlsplit, urlunsplit

from .parser_common import *


class UrlExtractorMixin:
    URL_RE = re.compile(r"https?://[^\s<>'\"，。；、]+", re.IGNORECASE)
    BARE_PLATFORM_URL_RE = re.compile(
        r"(?<![A-Za-z0-9_.:/-])"
        r"((?:www\.)?(?:douyin\.com|iesdouyin\.com|tiktok\.com)/[^\s<>'\"，。；、]+|"
        r"(?:v\.douyin\.com|vm\.tiktok\.com|vt\.tiktok\.com)/[^\s<>'\"，。；、]+)",
        re.IGNORECASE,
    )
    TRAILING_PUNCTUATION = ".,;:!?)]}）】》、，。；：！？"
    DIRECT_WORK_RE = re.compile(r"/(?:video|note|discover|share/video)/(\d{8,})", re.IGNORECASE)

    @classmethod
    def extract_urls(cls, text: str) -> list[str]:
        """Extract and aggressively dedupe share/work URLs.

        Deduping uses, in order, a direct aweme/note id when present, the
        normalized URL without tracking query/fragment, and finally the raw URL.
        Short-links are still preserved because resolving them requires network.
        Bare platform links such as ``v.douyin.com/xxx`` are accepted and
        normalized to https URLs because users often paste them without a scheme.
        """

        candidates = cls._url_candidates(text)
        urls: list[str] = []
        seen: set[str] = set()
        for _start, raw_url in candidates:
            url = raw_url.rstrip(cls.TRAILING_PUNCTUATION)
            if not url:
                continue
            key = cls._dedupe_key(url)
            if key in seen:
                continue
            seen.add(key)
            urls.append(url)
        return urls

    @classmethod
    def extract_url_report(cls, text: str) -> dict[str, object]:
        """Return URL extraction details for UI feedback.

        The parser only needs the de-duplicated URL list, but the desktop UI
        needs to tell the user how many links were identified and how many were
        removed as duplicates. Keeping this logic here prevents the UI from
        re-implementing parser-specific URL matching rules.
        """

        candidates = cls._url_candidates(text)
        raw_urls = [cls.clean_url(url) for _start, url in candidates]
        raw_urls = [url for url in raw_urls if url]
        urls: list[str] = []
        seen: set[str] = set()
        duplicates = 0
        for url in raw_urls:
            key = cls._dedupe_key(url)
            if key in seen:
                duplicates += 1
                continue
            seen.add(key)
            urls.append(url)
        return {
            "urls": urls,
            "raw_count": len(raw_urls),
            "duplicate_count": duplicates,
            "invalid_count": 0,
        }

    @classmethod
    def _url_candidates(cls, text: str) -> list[tuple[int, str]]:
        raw_text = str(text or "")
        candidates: list[tuple[int, str]] = []
        spans: list[tuple[int, int]] = []
        for match in cls.URL_RE.finditer(raw_text):
            candidates.append((match.start(), match.group(0)))
            spans.append(match.span())
        for match in cls.BARE_PLATFORM_URL_RE.finditer(raw_text):
            start = match.start(1)
            if any(span_start <= start < span_end for span_start, span_end in spans):
                continue
            candidates.append((start, "https://" + match.group(1)))
        candidates.sort(key=lambda item: item[0])
        return candidates

    @classmethod
    def clean_url(cls, url: str) -> str:
        """Return a user-facing URL without tracking query/fragment noise."""

        text = str(url or "").strip().rstrip(cls.TRAILING_PUNCTUATION)
        if not text:
            return ""
        try:
            parts = urlsplit(text)
        except Exception:
            return text
        if not parts.scheme or not parts.netloc:
            return text
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", "", ""))

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
