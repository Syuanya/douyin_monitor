from __future__ import annotations

from .monitor_common import *


class ContentMonitorCookieMixin:
    def _risk_controls_bypassed(self) -> bool:
        try:
            return bool(getattr(self.settings, "user_config", {}).get("development_bypass_risk_controls_enabled", False))
        except Exception:
            return False

    def _cookie_cooldown_enabled(self) -> bool:
        try:
            user_config = getattr(self.settings, "user_config", {}) or {}
            return bool(user_config.get("cookie_cooldown_enabled", True)) and not self._risk_controls_bypassed()
        except Exception:
            return True

    def _douyin_cookie_pool(self) -> list[str]:
        try:
            cookies_config = getattr(self.settings, "cookies_config", {}) or {}
            configured_pool = cookies_config.get("douyin_cookie_pool") or []
            primary_cookie = cookies_config.get("douyin_cookie") or self.settings.get_cookies_value("douyin_cookie", "")
        except Exception:
            configured_pool = []
            primary_cookie = ""
        pool = parse_cookie_pool(configured_pool)
        for cookie in parse_cookie_pool(primary_cookie):
            if cookie not in pool:
                pool.append(cookie)
        store = getattr(self.services, "cookie_health_store", None)
        if store is not None:
            try:
                store.register_pool("douyin", pool)
            except Exception:
                pass
        return pool

    def _select_douyin_cookie(self) -> str:
        pool = self._douyin_cookie_pool()
        if not pool:
            return ""
        now = time.monotonic()
        cooldown_enabled = self._cookie_cooldown_enabled()
        self._douyin_cookie_cooldowns = {
            cookie: until for cookie, until in self._douyin_cookie_cooldowns.items() if cooldown_enabled and until > now
        }
        store = getattr(self.services, "cookie_health_store", None) if cooldown_enabled else None
        available = []
        for cookie in pool:
            local_until = self._douyin_cookie_cooldowns.get(cookie, 0.0)
            persisted_until = 0.0
            if store is not None:
                try:
                    persisted_until = float(store.cooldown_until("douyin", cookie) or 0.0)
                except Exception:
                    persisted_until = 0.0
            if local_until <= now and persisted_until <= time.time():
                available.append(cookie)
        if not available:
            return ""
        health = getattr(self, "_douyin_cookie_health", {})
        # Weighted health scheduling. Lower failures and recent successes win;
        # the cursor is used only as a stable tie-breaker.
        cursor = int(getattr(self, "_douyin_cookie_cursor", 0) or 0)
        ranked = sorted(
            enumerate(available),
            key=lambda pair: (-self._cookie_health_score(pair[1]), (pair[0] - cursor) % max(1, len(available))),
        )
        cookie = ranked[0][1]
        self._douyin_cookie_cursor = (available.index(cookie) + 1) % max(1, len(available))
        health.setdefault(cookie, {"success": 0.0, "failure": 0.0, "empty": 0.0, "last_success": 0.0, "last_failure": 0.0})
        self._douyin_cookie_health = health
        return cookie

    def _cookie_health_score(self, cookie: str) -> float:
        state = getattr(self, "_douyin_cookie_health", {}).get(cookie, {})
        success = float(state.get("success", 0.0) or 0.0)
        failure = float(state.get("failure", 0.0) or 0.0)
        empty = float(state.get("empty", 0.0) or 0.0)
        score = 1.0 + success * 1.5 - failure * 2.0 - empty * 3.0
        store = getattr(self.services, "cookie_health_store", None)
        if store is not None:
            try:
                score += float(store.score("douyin", cookie) or 0.0) - 1.0
            except Exception:
                pass
        return score

    def _cooldown_douyin_cookie(self, cookie: str, reason: str = "") -> None:
        if not cookie:
            return
        if not self._cookie_cooldown_enabled():
            logger.debug(f"Douyin Cookie cooldown skipped by development/risk-control settings: {sanitize_text(reason)[:120]}")
            return
        try:
            seconds = float(self.settings.user_config.get("douyin_cookie_cooldown_seconds", 600) or 600)
        except (TypeError, ValueError):
            seconds = 600.0
        seconds = max(60.0, min(3600.0, seconds))
        self._douyin_cookie_cooldowns[cookie] = time.monotonic() + seconds
        store = getattr(self.services, "cookie_health_store", None)
        if store is not None:
            try:
                store.record_failure("douyin", cookie, reason, seconds)
            except Exception:
                pass
        logger.debug(f"Douyin Cookie temporarily cooled down for {int(seconds)}s: {sanitize_text(reason)[:120]}")

    def _record_cookie_response_health(self, cookie: str, response: httpx.Response | None = None, error: Exception | None = None) -> None:
        if not cookie:
            return
        health = getattr(self, "_douyin_cookie_health", {})
        state = health.setdefault(cookie, {"success": 0.0, "failure": 0.0, "empty": 0.0, "last_success": 0.0, "last_failure": 0.0})
        reason = ""
        if response is not None:
            status_code = int(getattr(response, "status_code", 0) or 0)
            text = ""
            try:
                text = response.text[:4000]
            except Exception:
                text = ""
            if status_code in {401, 403, 418, 429} or status_code >= 500:
                reason = f"HTTP {status_code}"
            elif status_code == 200 and not str(text or "").strip():
                reason = "HTTP 200 empty response"
                state["empty"] = min(100.0, float(state.get("empty", 0.0) or 0.0) + 1.0)
            else:
                lowered = text.lower()
                risk_markers = ("captcha", "verify", "security", "risk", "login", "风控", "验证", "登录")
                if any(marker in lowered for marker in risk_markers):
                    reason = "risk-control marker in response"
        if error is not None and not reason:
            reason = str(error)
        if reason:
            state["failure"] = min(100.0, float(state.get("failure", 0.0) or 0.0) + 1.0)
            state["last_failure"] = time.time()
            self._cooldown_douyin_cookie(cookie, reason)
        else:
            state["success"] = min(100.0, float(state.get("success", 0.0) or 0.0) + 1.0)
            state["failure"] = max(0.0, float(state.get("failure", 0.0) or 0.0) - 0.25)
            state["empty"] = max(0.0, float(state.get("empty", 0.0) or 0.0) - 0.25)
            state["last_success"] = time.time()
            store = getattr(self.services, "cookie_health_store", None)
            if store is not None:
                try:
                    store.record_success("douyin", cookie)
                except Exception:
                    pass
        self._douyin_cookie_health = health
