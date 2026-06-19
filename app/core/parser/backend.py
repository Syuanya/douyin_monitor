from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(slots=True)
class ParserHealth:
    ok: bool
    backend: str
    detail: str = ""
    capabilities: "ParserCapabilities | None" = None
    version: str = ""


@dataclass(slots=True, init=False)
class ParserCapabilities:
    parse_url: bool = False
    single_url: bool = False
    profile_contents: bool = False
    video: bool = False
    gallery: bool = False
    tiktok: bool = False
    fallback: bool = False

    def __init__(
        self,
        parse_url: bool | None = None,
        *,
        single_url: bool | None = None,
        profile_contents: bool = False,
        video: bool = False,
        gallery: bool = False,
        tiktok: bool = False,
        fallback: bool = False,
    ) -> None:
        supports_url = bool(parse_url) if parse_url is not None else bool(single_url)
        if single_url is not None:
            supports_url = bool(single_url)
        self.parse_url = supports_url
        self.single_url = supports_url
        self.profile_contents = bool(profile_contents)
        self.video = bool(video)
        self.gallery = bool(gallery)
        self.tiktok = bool(tiktok)
        self.fallback = bool(fallback)

    def __call__(self) -> "ParserCapabilities":
        """Allow both ``backend.capabilities`` and ``backend.capabilities()``.

        Older project code exposed capabilities as an attribute while the newer
        backend protocol uses a method. Making the value callable keeps both
        call sites valid without forcing a risky cross-project rename.
        """

        return self

    def merge(self, other: "ParserCapabilities") -> "ParserCapabilities":
        return ParserCapabilities(
            parse_url=self.parse_url or other.parse_url,
            profile_contents=self.profile_contents or other.profile_contents,
            video=self.video or other.video,
            gallery=self.gallery or other.gallery,
            tiktok=self.tiktok or other.tiktok,
            fallback=self.fallback or other.fallback,
        )


ParserCapability = ParserCapabilities


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


class FallbackParserBackend:
    """Generic parser fallback chain used by compatibility and tests."""

    name = "fallback"
    platform = "generic"
    version = "fallback-v1"

    def __init__(self, backends: list[Any]):
        self.backends = list(backends or [])
        self.capabilities = ParserCapability(fallback=True)

    async def health_check(self) -> ParserHealth:
        details: list[str] = []
        merged = ParserCapability(fallback=True)
        any_ok = False
        for backend in self.backends:
            caps = _backend_capabilities(backend)
            merged = merged.merge(caps)
            try:
                health = await backend.health_check()
                any_ok = any_ok or bool(getattr(health, "ok", False))
                detail = str(getattr(health, "detail", ""))
            except Exception as exc:
                detail = str(exc)
            details.append(f"{getattr(backend, 'name', backend.__class__.__name__)}:{detail}")
        self.capabilities = merged
        return ParserHealth(any_ok, self.name, "；".join(details), merged, self.version)

    async def parse_url(self, url: str) -> dict[str, Any]:
        return await self._call_first("parse_url", lambda caps: caps.parse_url or caps.single_url, url)

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        return await self._call_first("fetch_profile_contents", lambda caps: caps.profile_contents, sec_user_id, max_pages, count)

    async def _call_first(self, method_name: str, supports: Any, *args: Any) -> Any:
        errors: list[str] = []
        for backend in self.backends:
            caps = _backend_capabilities(backend)
            if not supports(caps):
                errors.append(f"{getattr(backend, 'name', backend.__class__.__name__)}: unsupported")
                continue
            try:
                health = await backend.health_check()
                if not getattr(health, "ok", False):
                    errors.append(f"{getattr(backend, 'name', backend.__class__.__name__)}: {getattr(health, 'detail', '')}")
                    continue
                return await getattr(backend, method_name)(*args)
            except Exception as exc:
                errors.append(f"{getattr(backend, 'name', backend.__class__.__name__)}: {exc}")
        raise RuntimeError("所有解析器后端均不可用：" + "；".join(errors))


def _backend_capabilities(backend: Any) -> ParserCapabilities:
    raw = getattr(backend, "capabilities", ParserCapability())
    if callable(raw):
        raw = raw()
    if isinstance(raw, ParserCapabilities):
        return raw
    return ParserCapability()
