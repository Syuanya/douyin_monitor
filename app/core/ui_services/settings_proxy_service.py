from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx


@dataclass(slots=True)
class ProxyValidationResult:
    ok: bool
    enabled: bool
    raw: str
    normalized: str = ""
    scheme: str = ""
    host: str = ""
    port: int | None = None
    message: str = ""
    warning: str = ""

    def summary(self) -> str:
        if not self.enabled:
            return "代理未启用。"
        if self.ok:
            note = f"代理格式有效：{self.scheme}://{self.host}"
            if self.port:
                note += f":{self.port}"
            if self.warning:
                note += f"；{self.warning}"
            return note
        return self.message or "代理地址格式无效。"


@dataclass(slots=True)
class ProxyTestResult:
    ok: bool
    validation: ProxyValidationResult
    status_code: int | None = None
    elapsed_ms: int | None = None
    message: str = ""

    def summary(self) -> str:
        if not self.validation.ok:
            return self.validation.summary()
        if self.ok:
            suffix = f"，HTTP {self.status_code}" if self.status_code is not None else ""
            elapsed = f"，耗时 {self.elapsed_ms}ms" if self.elapsed_ms is not None else ""
            return f"代理连通性正常{suffix}{elapsed}。"
        return self.message or "代理连通性测试失败。"


class SettingsProxyService:
    """Proxy validation and connectivity checks for settings UI."""

    SUPPORTED_SCHEMES = {"http", "https", "socks5", "socks5h"}

    def __init__(self, app: Any):
        self.app = app

    @classmethod
    def validate(cls, proxy_address: str, *, enabled: bool = True) -> ProxyValidationResult:
        raw = str(proxy_address or "").strip()
        if not enabled:
            return ProxyValidationResult(ok=True, enabled=False, raw=raw, normalized="", message="代理未启用。")
        if not raw:
            return ProxyValidationResult(ok=False, enabled=True, raw=raw, message="代理已开启，但代理地址为空。")
        normalized = raw
        warning = ""
        if "://" not in normalized:
            normalized = "http://" + normalized
            warning = "未填写协议，已按 http 代理处理。"
        parsed = urlparse(normalized)
        scheme = (parsed.scheme or "").lower()
        host = parsed.hostname or ""
        port = parsed.port
        if scheme not in cls.SUPPORTED_SCHEMES:
            return ProxyValidationResult(ok=False, enabled=True, raw=raw, normalized=normalized, scheme=scheme, message=f"代理协议 {scheme or '<空>'} 不支持，请使用 http/https/socks5。")
        if not host:
            return ProxyValidationResult(ok=False, enabled=True, raw=raw, normalized=normalized, scheme=scheme, message="代理地址缺少主机。")
        if port is None:
            return ProxyValidationResult(ok=False, enabled=True, raw=raw, normalized=normalized, scheme=scheme, host=host, message="代理地址缺少端口。")
        if port < 1 or port > 65535:
            return ProxyValidationResult(ok=False, enabled=True, raw=raw, normalized=normalized, scheme=scheme, host=host, port=port, message="代理端口必须在 1-65535 之间。")
        return ProxyValidationResult(ok=True, enabled=True, raw=raw, normalized=normalized, scheme=scheme, host=host, port=port, warning=warning)

    async def test(self, proxy_address: str, *, enabled: bool = True, test_url: str = "https://www.douyin.com/") -> ProxyTestResult:
        validation = self.validate(proxy_address, enabled=enabled)
        if not validation.ok:
            return ProxyTestResult(ok=False, validation=validation, message=validation.summary())
        if not validation.enabled:
            return ProxyTestResult(ok=True, validation=validation, message="代理未启用，已跳过连通性测试。")
        return await asyncio.to_thread(self._test_sync, validation, test_url)

    @staticmethod
    def _test_sync(validation: ProxyValidationResult, test_url: str) -> ProxyTestResult:
        import time

        start = time.monotonic()
        try:
            with httpx.Client(proxy=validation.normalized, timeout=8.0, follow_redirects=True) as client:
                response = client.get(test_url)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            ok = response.status_code < 500
            message = "" if ok else f"代理连接返回 HTTP {response.status_code}。"
            return ProxyTestResult(ok=ok, validation=validation, status_code=response.status_code, elapsed_ms=elapsed_ms, message=message)
        except Exception as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ProxyTestResult(ok=False, validation=validation, elapsed_ms=elapsed_ms, message=f"代理连通性测试失败：{exc}")
