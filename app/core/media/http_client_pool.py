from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx


@dataclass(frozen=True)
class _ClientKey:
    loop_id: int
    proxy: str


class DownloadHttpClientPool:
    """Reusable async HTTP client pool for media downloads.

    The pool is intentionally keyed only by event loop and proxy. Headers and
    timeouts are supplied per request so the same connection pool can be reused
    across videos, images, previews and content-monitor downloads.
    """

    def __init__(self) -> None:
        self._clients: dict[_ClientKey, httpx.AsyncClient] = {}
        self._lock = asyncio.Lock()

    async def get_client(self, *, proxy: str | None = None) -> httpx.AsyncClient:
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = 0
        key = _ClientKey(loop_id=loop_id, proxy=str(proxy or ""))
        async with self._lock:
            client = self._clients.get(key)
            if client is not None and not client.is_closed:
                return client
            kwargs: dict[str, Any] = {"follow_redirects": True}
            if proxy:
                kwargs["proxy"] = proxy
            client = httpx.AsyncClient(**kwargs)
            self._clients[key] = client
            return client

    async def aclose(self) -> None:
        async with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                await client.aclose()
            except Exception:
                pass
