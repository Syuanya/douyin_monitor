from __future__ import annotations

from .parser_common import *


class ParserCookiePoolMixin:
    def _risk_controls_bypassed(self) -> bool:
        limiter = getattr(self, "request_limiter", None)
        try:
            if limiter is not None and hasattr(limiter, "_bypass_enabled") and limiter._bypass_enabled():
                return True
        except Exception:
            pass
        settings = getattr(self, "settings_config", None)
        try:
            return bool(getattr(settings, "user_config", {}).get("development_bypass_risk_controls_enabled", False))
        except Exception:
            return False

    def _cookie_cooldown_enabled(self) -> bool:
        settings = getattr(self, "settings_config", None)
        try:
            return bool(getattr(settings, "user_config", {}).get("cookie_cooldown_enabled", True)) and not self._risk_controls_bypassed()
        except Exception:
            return not self._risk_controls_bypassed()

    def update_cookie(self, platform: str, cookie: str) -> int:
        pool = parse_cookie_pool(cookie)
        cookie_value = pool[0] if pool else sanitize_cookie_header(cookie)
        changed = self.configure_cookie_pool(platform, pool or ([cookie_value] if cookie_value else []))
        return changed

    def configure_cookie_pool(self, platform: str, cookies: list[str] | tuple[str, ...] | str) -> int:
        platform_key = str(platform or "").strip().lower()
        if platform_key not in {"douyin", "tiktok"}:
            raise ValueError("platform must be 'douyin' or 'tiktok'")

        pool = parse_cookie_pool(cookies)
        self._cookie_pools[platform_key] = pool
        store = getattr(self, "cookie_health_store", None)
        if store is not None:
            try:
                store.register_pool(platform_key, pool)
            except Exception:
                pass
        self._cookie_cursors[platform_key] = 0
        self._cookie_health.setdefault(platform_key, {})
        self._cookie_cooldowns.setdefault(platform_key, {})
        # Drop stale health for cookies no longer configured.
        self._cookie_health[platform_key] = {key: value for key, value in self._cookie_health[platform_key].items() if key in pool}
        self._cookie_cooldowns[platform_key] = {key: value for key, value in self._cookie_cooldowns[platform_key].items() if key in pool}
        primary_cookie = pool[0] if pool else ""

        for _config_path, token_key, module_name in self._cookie_config_targets(platform_key):
            self._refresh_loaded_crawler_config(module_name, token_key, primary_cookie)
        return len(pool)

    def next_cookie(self, platform: str) -> str:
        platform_key = str(platform or "").strip().lower()
        pool = self._cookie_pools.get(platform_key) or []
        if not pool:
            return ""
        now = time.monotonic()
        cooldown_enabled = self._cookie_cooldown_enabled()
        cooldowns = self._cookie_cooldowns.setdefault(platform_key, {})
        self._cookie_cooldowns[platform_key] = {cookie: until for cookie, until in cooldowns.items() if cooldown_enabled and until > now}
        store = getattr(self, "cookie_health_store", None) if cooldown_enabled else None
        available = []
        for cookie in pool:
            local_until = self._cookie_cooldowns[platform_key].get(cookie, 0.0)
            persisted_until = 0.0
            if store is not None:
                try:
                    persisted_until = float(store.cooldown_until(platform_key, cookie) or 0.0)
                except Exception:
                    persisted_until = 0.0
            if local_until <= now and persisted_until <= time.time():
                available.append(cookie)
        if not available:
            return ""
        cursor = self._cookie_cursors.get(platform_key, 0)
        ranked = sorted(
            enumerate(available),
            key=lambda pair: (-self._cookie_score(platform_key, pair[1]), (pair[0] - cursor) % max(1, len(available))),
        )
        cookie = ranked[0][1]
        self._cookie_cursors[platform_key] = (available.index(cookie) + 1) % max(1, len(available))
        self._cookie_health.setdefault(platform_key, {}).setdefault(cookie, {"success": 0.0, "failure": 0.0, "empty": 0.0, "last_success": 0.0, "last_failure": 0.0})
        return cookie

    def record_cookie_success(self, platform: str, cookie: str) -> None:
        self._record_cookie_health(platform, cookie, success=True)

    def record_cookie_failure(self, platform: str, cookie: str, reason: str = "") -> None:
        self._record_cookie_health(platform, cookie, success=False, reason=reason)

    def _record_cookie_health(self, platform: str, cookie: str, *, success: bool, reason: str = "") -> None:
        platform_key = str(platform or "").strip().lower()
        if not cookie or platform_key not in {"douyin", "tiktok"}:
            return
        state = self._cookie_health.setdefault(platform_key, {}).setdefault(
            cookie,
            {"success": 0.0, "failure": 0.0, "empty": 0.0, "last_success": 0.0, "last_failure": 0.0},
        )
        if success:
            state["success"] = min(100.0, float(state.get("success", 0.0) or 0.0) + 1.0)
            state["failure"] = max(0.0, float(state.get("failure", 0.0) or 0.0) - 0.25)
            state["empty"] = max(0.0, float(state.get("empty", 0.0) or 0.0) - 0.25)
            state["last_success"] = time.time()
            store = getattr(self, "cookie_health_store", None)
            if store is not None:
                try:
                    store.record_success(platform_key, cookie)
                except Exception:
                    pass
            return
        lowered = str(reason or "").lower()
        state["failure"] = min(100.0, float(state.get("failure", 0.0) or 0.0) + 1.0)
        if "empty" in lowered or "空响应" in lowered or "响应内容为空" in lowered:
            state["empty"] = min(100.0, float(state.get("empty", 0.0) or 0.0) + 1.0)
        state["last_failure"] = time.time()
        if not self._cookie_cooldown_enabled():
            return
        seconds = self._cookie_cooldown_seconds(reason)
        self._cookie_cooldowns.setdefault(platform_key, {})[cookie] = time.monotonic() + seconds
        store = getattr(self, "cookie_health_store", None)
        if store is not None:
            try:
                store.record_failure(platform_key, cookie, reason, seconds)
            except Exception:
                pass

    def _cookie_score(self, platform: str, cookie: str) -> float:
        state = self._cookie_health.setdefault(platform, {}).get(cookie, {})
        score = 1.0 + float(state.get("success", 0.0) or 0.0) * 1.5 - float(state.get("failure", 0.0) or 0.0) * 2.0 - float(state.get("empty", 0.0) or 0.0) * 3.0
        store = getattr(self, "cookie_health_store", None)
        if store is not None:
            try:
                score += float(store.score(platform, cookie) or 0.0) - 1.0
            except Exception:
                pass
        return score

    @staticmethod
    def _cookie_cooldown_seconds(reason: str = "") -> float:
        lowered = str(reason or "").lower()
        if "empty" in lowered or "空响应" in lowered or "响应内容为空" in lowered:
            return 900.0
        if "login" in lowered or "cookie" in lowered or "登录" in lowered:
            return 1800.0
        return 600.0

    def cookie_health_snapshot(self, platform: str = "douyin") -> dict[str, dict[str, float]]:
        platform_key = str(platform or "douyin").strip().lower()
        snapshot = {cookie: dict(state) for cookie, state in self._cookie_health.get(platform_key, {}).items()}
        store = getattr(self, "cookie_health_store", None)
        if store is not None:
            try:
                persisted = store.snapshot(platform_key)
                if persisted:
                    snapshot["__persisted__"] = persisted
            except Exception:
                pass
        return snapshot

    def _cookie_config_targets(self, platform: str) -> list[tuple[Path, str, str]]:
        root = Path(self.run_path or os.getcwd())
        if platform == "douyin":
            return [
                (
                    root / "crawlers" / "douyin" / "web" / "config.yaml",
                    "douyin",
                    "crawlers.douyin.web.web_crawler",
                )
            ]
        return [
            (
                root / "crawlers" / "tiktok" / "web" / "config.yaml",
                "tiktok",
                "crawlers.tiktok.web.web_crawler",
            ),
            (
                root / "crawlers" / "tiktok" / "app" / "config.yaml",
                "tiktok",
                "crawlers.tiktok.app.app_crawler",
            ),
        ]

    @staticmethod
    def _write_cookie_config(config_path: Path, token_key: str, cookie: str) -> bool:
        if not config_path.exists():
            return False
        data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        token_config = data.setdefault("TokenManager", {}).setdefault(token_key, {})
        headers = token_config.setdefault("headers", {})
        headers["Cookie"] = cookie
        config_path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
        return True

    @staticmethod
    def _refresh_loaded_crawler_config(module_name: str, token_key: str, cookie: str) -> None:
        try:
            import sys

            module = sys.modules.get(module_name)
            if not module or not hasattr(module, "config"):
                return
            config = getattr(module, "config")
            config.setdefault("TokenManager", {}).setdefault(token_key, {}).setdefault("headers", {})["Cookie"] = cookie
        except Exception:
            return
