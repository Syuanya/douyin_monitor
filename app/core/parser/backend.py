from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ParserHealth:
    ok: bool
    backend: str
    detail: str = ""


@dataclass(slots=True)
class ParserCapabilities:
    parse_url: bool = False
    profile_contents: bool = False
    video: bool = False
    gallery: bool = False
    tiktok: bool = False

    def merge(self, other: "ParserCapabilities") -> "ParserCapabilities":
        return ParserCapabilities(
            parse_url=self.parse_url or other.parse_url,
            profile_contents=self.profile_contents or other.profile_contents,
            video=self.video or other.video,
            gallery=self.gallery or other.gallery,
            tiktok=self.tiktok or other.tiktok,
        )


class ParserBackend(Protocol):
    name: str
    platform: str

    async def health_check(self) -> ParserHealth:
        ...

    def capabilities(self) -> ParserCapabilities:
        ...

    async def parse_url(self, url: str) -> dict[str, Any]:
        ...

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        ...
