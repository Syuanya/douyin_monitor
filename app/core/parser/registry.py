from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .backend import ParserBackend, ParserCapabilities, ParserHealth


BackendFactory = Callable[..., ParserBackend]


@dataclass(slots=True)
class ParserBackendDescriptor:
    key: str
    label: str
    platform: str
    factory: BackendFactory
    capabilities: ParserCapabilities
    description: str = ""


class ParserBackendRegistry:
    """Small registry for parser backend discovery and health governance."""

    def __init__(self) -> None:
        self._items: dict[str, ParserBackendDescriptor] = {}

    def register(self, descriptor: ParserBackendDescriptor) -> None:
        key = str(descriptor.key or "").strip().lower()
        if not key:
            raise ValueError("parser backend key is required")
        self._items[key] = descriptor

    def keys(self) -> list[str]:
        return sorted(self._items)

    def descriptors(self, platform: str = "") -> list[ParserBackendDescriptor]:
        platform = str(platform or "").strip().lower()
        values = list(self._items.values())
        if platform:
            values = [item for item in values if item.platform.lower() == platform]
        return sorted(values, key=lambda item: item.key)

    def create(self, key: str, **kwargs: Any) -> ParserBackend:
        normalized = str(key or "").strip().lower()
        descriptor = self._items.get(normalized)
        if descriptor is None:
            raise KeyError(f"parser backend not registered: {key}")
        return descriptor.factory(**kwargs)

    async def health_check_all(self, platform: str = "", **kwargs: Any) -> list[ParserHealth]:
        results: list[ParserHealth] = []
        for descriptor in self.descriptors(platform=platform):
            try:
                backend = descriptor.factory(**kwargs)
                results.append(await backend.health_check())
            except Exception as exc:
                results.append(ParserHealth(False, descriptor.key, str(exc)))
        return results


parser_backend_registry = ParserBackendRegistry()
