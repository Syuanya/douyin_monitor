from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class RateLimitSnapshot:
    global_delay: float
    scopes: dict[str, float]
    wait_count: int
    failure_count: int


class _AsyncIntervalLimiter:
    def __init__(self, interval_seconds: float):
        self.interval_seconds = max(0.0, float(interval_seconds or 0.0))
        self._next_at = 0.0
        self._lock = asyncio.Lock()

    async def wait(self, extra_delay: float = 0.0) -> None:
        interval = max(self.interval_seconds, float(extra_delay or 0.0))
        if interval <= 0:
            return
        async with self._lock:
            now = time.monotonic()
            if self._next_at > now:
                await asyncio.sleep(self._next_at - now)
                now = time.monotonic()
            self._next_at = max(self._next_at, now) + interval


class DouyinRequestLimiter:
    """Global throttling shared by monitoring and parsing.

    This is intentionally conservative.  It limits bursts per scope and can add
    temporary global backoff after risk-control-like failures.
    """

    def __init__(self, settings_config: Any | None = None):
        self.settings = settings_config
        self._limiters: dict[str, _AsyncIntervalLimiter] = {}
        self._lock = asyncio.Lock()
        self._global_backoff_until = 0.0
        self._global_backoff_seconds = 0.0
        self._wait_count = 0
        self._failure_count = 0

    def _config_float(self, key: str, default: float) -> float:
        try:
            value = getattr(self.settings, "user_config", {}).get(key, default) if self.settings is not None else default
            return float(value)
        except (TypeError, ValueError):
            return float(default)

    def _config_bool(self, key: str, default: bool) -> bool:
        try:
            value = getattr(self.settings, "user_config", {}).get(key, default) if self.settings is not None else default
        except Exception:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _interval_for_scope(self, scope: str) -> float:
        if not self._config_bool("global_request_limiter_enabled", True):
            return 0.0
        scope = str(scope or "general")
        if scope.startswith("cookie:"):
            rpm = self._config_float("douyin_cookie_requests_per_minute", 12.0)
        elif scope.startswith("account:"):
            rpm = self._config_float("douyin_account_requests_per_minute", 6.0)
        elif scope.startswith("api:"):
            rpm = self._config_float("douyin_api_requests_per_minute", 30.0)
        else:
            rpm = self._config_float("douyin_global_requests_per_minute", 60.0)
        rpm = max(1.0, min(600.0, rpm))
        return 60.0 / rpm

    async def wait(self, *scopes: str) -> None:
        if not self._config_bool("global_request_limiter_enabled", True):
            return
        normalized = [str(scope or "").strip() for scope in scopes if str(scope or "").strip()]
        normalized.append("global")
        now = time.monotonic()
        extra_delay = max(0.0, self._global_backoff_until - now)
        for scope in normalized:
            limiter = await self._limiter(scope)
            await limiter.wait(extra_delay if scope == "global" else 0.0)
            self._wait_count += 1

    async def _limiter(self, scope: str) -> _AsyncIntervalLimiter:
        interval = self._interval_for_scope(scope)
        async with self._lock:
            limiter = self._limiters.get(scope)
            if limiter is None or abs(limiter.interval_seconds - interval) > 1e-6:
                limiter = _AsyncIntervalLimiter(interval)
                self._limiters[scope] = limiter
            return limiter

    def record_success(self) -> None:
        if self._global_backoff_seconds > 0:
            self._global_backoff_seconds = max(0.0, self._global_backoff_seconds * 0.7)

    def record_failure(self, reason: str = "") -> None:
        lowered = str(reason or "").lower()
        risk = any(token in lowered for token in ("empty", "空响应", "风控", "captcha", "verify", "429", "418"))
        if not risk:
            return
        self._failure_count += 1
        base = self._config_float("douyin_risk_backoff_seconds", 30.0)
        maximum = self._config_float("douyin_max_risk_backoff_seconds", 600.0)
        self._global_backoff_seconds = min(maximum, max(base, self._global_backoff_seconds * 1.8 or base))
        self._global_backoff_until = max(self._global_backoff_until, time.monotonic() + self._global_backoff_seconds)

    def snapshot(self) -> RateLimitSnapshot:
        return RateLimitSnapshot(
            global_delay=max(0.0, self._global_backoff_until - time.monotonic()),
            scopes={key: limiter.interval_seconds for key, limiter in self._limiters.items()},
            wait_count=self._wait_count,
            failure_count=self._failure_count,
        )
