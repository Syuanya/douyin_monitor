from __future__ import annotations

import inspect
from typing import Any

import httpx


def _clean_proxy_value(proxies: Any) -> Any:
    if not proxies:
        return None
    if isinstance(proxies, dict):
        cleaned = {key: value for key, value in proxies.items() if value}
        if not cleaned:
            return None
        return cleaned
    return proxies


def _single_proxy(proxies: Any) -> Any:
    cleaned = _clean_proxy_value(proxies)
    if isinstance(cleaned, dict):
        return cleaned.get("https://") or cleaned.get("http://") or next(iter(cleaned.values()), None)
    return cleaned


def _supports_parameter(client_cls: type, parameter: str) -> bool:
    try:
        return parameter in inspect.signature(client_cls.__init__).parameters
    except Exception:
        return False


def client_kwargs(proxies: Any = None, **kwargs: Any) -> dict[str, Any]:
    return _with_proxy_kwarg(httpx.Client, proxies, kwargs)


def async_client_kwargs(proxies: Any = None, **kwargs: Any) -> dict[str, Any]:
    return _with_proxy_kwarg(httpx.AsyncClient, proxies, kwargs)


def _with_proxy_kwarg(client_cls: type, proxies: Any, kwargs: dict[str, Any]) -> dict[str, Any]:
    proxy_value = _clean_proxy_value(proxies)
    if proxy_value is None:
        return kwargs
    if _supports_parameter(client_cls, "proxies"):
        kwargs["proxies"] = proxy_value
    elif _supports_parameter(client_cls, "proxy"):
        single_proxy = _single_proxy(proxy_value)
        if single_proxy:
            kwargs["proxy"] = single_proxy
    return kwargs
