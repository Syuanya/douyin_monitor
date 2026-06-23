from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .image_urls import deduplicate_image_urls


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if isinstance(value, tuple):
        return [str(item) for item in value if item]
    if isinstance(value, str) and value:
        return [value]
    return []


def _prefer_direct_video_url(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            # Prefer direct play endpoints over redirect helpers when both are present.
            if "aweme.snssdk.com/aweme/v1/play" not in value:
                return value
    for value in values:
        if isinstance(value, str) and value.startswith(("http://", "https://")):
            return value
    return ""


def normalize_work_url(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit

    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
    except Exception:
        return text
    if not parts.scheme or not parts.netloc:
        return text
    return urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip("/") or "/", "", ""))


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
class ParseProgress:
    source_url: str = ""
    total: int = 0
    completed: int = 0
    success_count: int = 0
    failed_count: int = 0
    status: str = "running"
    message: str = ""



@dataclass(slots=True)
class ParseDownloadEvent:
    source_url: str
    item_id: str = ""
    status: str = "queued"
    success: bool = False
    reason: str = ""
    path: str = ""
    result: dict[str, Any] = field(default_factory=dict)


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

