from __future__ import annotations

from typing import Any

from .backend import ParserCapabilities, ParserHealth
from .registry import ParserBackendDescriptor, parser_backend_registry


class InternalDouyinParserBackend:
    name = "internal"
    platform = "douyin"
    version = "internal-v1"

    def __init__(self, video_parser: Any):
        self.video_parser = video_parser

    async def health_check(self) -> ParserHealth:
        if self.video_parser is None:
            return ParserHealth(False, self.name, "内置解析器未初始化")
        return ParserHealth(True, self.name, "内置解析器可用")

    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(parse_url=True, profile_contents=True, video=True, gallery=True, tiktok=True)

    async def parse_url(self, url: str) -> dict[str, Any]:
        health = await self.health_check()
        if not health.ok:
            raise RuntimeError(health.detail)
        return await self.video_parser.parse_url(url)

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        health = await self.health_check()
        if not health.ok:
            raise RuntimeError(health.detail)
        return await self.video_parser.fetch_all_douyin_user_posts(sec_user_id, max_pages=max_pages, count=count)


class ExternalDouyinParserBackend:
    name = "external"
    platform = "douyin"
    version = "external-api-v1"

    def __init__(self, base_url: str):
        self.base_url = str(base_url or "").strip().rstrip("/")

    async def health_check(self) -> ParserHealth:
        if not self.base_url:
            return ParserHealth(False, self.name, "外部解析器地址未配置")
        return ParserHealth(True, self.name, f"外部解析器已配置：{self.base_url}")

    def capabilities(self) -> ParserCapabilities:
        return ParserCapabilities(parse_url=False, profile_contents=True, video=True, gallery=True, tiktok=False)

    async def parse_url(self, url: str) -> dict[str, Any]:
        raise NotImplementedError("外部解析器暂未实现统一 parse_url 接口，请使用内置解析器解析单作品链接。")

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        health = await self.health_check()
        if not health.ok:
            raise RuntimeError(health.detail)
        from ..content_monitor.douyin_api_client import DouyinExternalApiClient

        client = DouyinExternalApiClient(self.base_url)
        return await client.fetch_all_user_posts(sec_user_id, max_pages=max_pages, count=count)


class FallbackDouyinParserBackend:
    """Try multiple Douyin parser backends behind one stable interface."""

    name = "fallback"
    platform = "douyin"
    version = "fallback-v1"

    def __init__(self, primary: Any, fallbacks: list[Any] | None = None):
        self.primary = primary
        self.fallbacks = list(fallbacks or [])

    def _backends(self) -> list[Any]:
        return [self.primary, *self.fallbacks]

    async def health_check(self) -> ParserHealth:
        details: list[str] = []
        any_ok = False
        for backend in self._backends():
            health = await backend.health_check()
            any_ok = any_ok or health.ok
            state = "ok" if health.ok else "bad"
            details.append(f"{backend.name}:{state}({health.detail})")
        return ParserHealth(any_ok, self.name, "；".join(details))

    def capabilities(self) -> ParserCapabilities:
        merged = ParserCapabilities()
        for backend in self._backends():
            merged = merged.merge(backend.capabilities())
        return merged

    async def parse_url(self, url: str) -> dict[str, Any]:
        return await self._call_first("parse_url", lambda backend: backend.capabilities().parse_url, url)

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20) -> list[Any]:
        return await self._call_first(
            "fetch_profile_contents",
            lambda backend: backend.capabilities().profile_contents,
            sec_user_id,
            max_pages,
            count,
        )

    async def _call_first(self, method_name: str, supports: Any, *args: Any) -> Any:
        errors: list[str] = []
        for backend in self._backends():
            if not supports(backend):
                errors.append(f"{backend.name}: unsupported")
                continue
            health = await backend.health_check()
            if not health.ok:
                errors.append(f"{backend.name}: {health.detail}")
                continue
            try:
                method = getattr(backend, method_name)
                return await method(*args)
            except Exception as exc:
                errors.append(f"{backend.name}: {exc}")
        raise RuntimeError("所有解析器后端均不可用：" + "；".join(errors))


def build_douyin_parser_backend(kind: str, *, video_parser: Any = None, external_base_url: str = ""):
    backend = str(kind or "internal").strip().lower()
    if backend == "external":
        external = ExternalDouyinParserBackend(external_base_url)
        if video_parser is not None:
            return FallbackDouyinParserBackend(external, [InternalDouyinParserBackend(video_parser)])
        return external
    return InternalDouyinParserBackend(video_parser)


def _register_default_backends() -> None:
    parser_backend_registry.register(
        ParserBackendDescriptor(
            key="douyin_internal",
            label="内置抖音解析器",
            platform="douyin",
            factory=lambda **kw: InternalDouyinParserBackend(kw.get("video_parser")),
            capabilities=InternalDouyinParserBackend(None).capabilities(),
            description="使用项目内置 crawler 和 VideoParserService 解析作品与主页。",
        )
    )
    parser_backend_registry.register(
        ParserBackendDescriptor(
            key="douyin_external",
            label="外部抖音解析 API",
            platform="douyin",
            factory=lambda **kw: ExternalDouyinParserBackend(str(kw.get("external_base_url") or "")),
            capabilities=ExternalDouyinParserBackend("https://example.invalid").capabilities(),
            description="通过外部 API 获取主页作品列表；单作品解析可由 fallback 接管。",
        )
    )
    parser_backend_registry.register(
        ParserBackendDescriptor(
            key="douyin_fallback",
            label="抖音 fallback 链",
            platform="douyin",
            factory=lambda **kw: build_douyin_parser_backend(
                "external",
                video_parser=kw.get("video_parser"),
                external_base_url=str(kw.get("external_base_url") or ""),
            ),
            capabilities=ParserCapabilities(parse_url=True, profile_contents=True, video=True, gallery=True, tiktok=True),
            description="优先外部主页解析，必要时回退内置解析器。",
        )
    )


_register_default_backends()
