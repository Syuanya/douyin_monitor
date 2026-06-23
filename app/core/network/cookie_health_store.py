from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class CookieHealthState:
    cookie_hash: str
    platform: str
    success: float = 0.0
    failure: float = 0.0
    empty: float = 0.0
    last_success: float = 0.0
    last_failure: float = 0.0
    cooldown_until: float = 0.0
    disabled_until: float = 0.0
    last_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "cookie_hash": self.cookie_hash,
            "platform": self.platform,
            "success": self.success,
            "failure": self.failure,
            "empty": self.empty,
            "last_success": self.last_success,
            "last_failure": self.last_failure,
            "cooldown_until": self.cooldown_until,
            "disabled_until": self.disabled_until,
            "last_reason": self.last_reason,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CookieHealthState":
        def as_float(key: str) -> float:
            try:
                return float(data.get(key) or 0.0)
            except (TypeError, ValueError):
                return 0.0

        return cls(
            cookie_hash=str(data.get("cookie_hash") or ""),
            platform=str(data.get("platform") or "douyin"),
            success=as_float("success"),
            failure=as_float("failure"),
            empty=as_float("empty"),
            last_success=as_float("last_success"),
            last_failure=as_float("last_failure"),
            cooldown_until=as_float("cooldown_until"),
            disabled_until=as_float("disabled_until"),
            last_reason=str(data.get("last_reason") or ""),
        )


class CookieHealthStore:
    """Persist non-sensitive Cookie health metrics.

    Cookies are never written to disk.  State is keyed by a salted-ish SHA256
    digest of the cookie header so health survives restart without exposing the
    cookie value in diagnostics or backups.
    """

    def __init__(self, run_path: str, relative_path: str = "config/cookie_health.json", enabled: bool = True):
        self.run_path = str(run_path or ".")
        self.path = os.path.join(self.run_path, relative_path)
        self.enabled = bool(enabled)
        self._lock = threading.RLock()
        self._states: dict[str, dict[str, CookieHealthState]] = {"douyin": {}, "tiktok": {}}
        self._last_save_at = 0.0
        self._save_interval_seconds = 2.0
        self.load()

    @staticmethod
    def cookie_hash(cookie: str) -> str:
        text = str(cookie or "").strip()
        if not text:
            return ""
        return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()[:24]

    def load(self) -> None:
        if not self.enabled or not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
            states = data.get("states", data) if isinstance(data, dict) else {}
            loaded: dict[str, dict[str, CookieHealthState]] = {"douyin": {}, "tiktok": {}}
            for platform, records in states.items() if isinstance(states, dict) else []:
                platform_key = str(platform or "").lower()
                if platform_key not in loaded or not isinstance(records, dict):
                    continue
                for cookie_hash, raw in records.items():
                    if not isinstance(raw, dict):
                        continue
                    raw = dict(raw)
                    raw.setdefault("cookie_hash", cookie_hash)
                    raw.setdefault("platform", platform_key)
                    state = CookieHealthState.from_dict(raw)
                    if state.cookie_hash:
                        loaded[platform_key][state.cookie_hash] = state
            with self._lock:
                self._states = loaded
        except Exception:
            return

    def save(self, *, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_save_at < self._save_interval_seconds:
            return
        with self._lock:
            data = {
                "version": 1,
                "saved_at": time.time(),
                "states": {
                    platform: {key: state.to_dict() for key, state in records.items()}
                    for platform, records in self._states.items()
                },
            }
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
            self._last_save_at = now
        except Exception:
            pass

    def register_pool(self, platform: str, cookies: list[str] | tuple[str, ...]) -> None:
        platform_key = self._platform(platform)
        if not platform_key:
            return
        hashes = {self.cookie_hash(cookie) for cookie in cookies if str(cookie or "").strip()}
        hashes.discard("")
        with self._lock:
            states = self._states.setdefault(platform_key, {})
            for key in hashes:
                states.setdefault(key, CookieHealthState(cookie_hash=key, platform=platform_key))
            # Keep old states for diagnostics and cooldown history, but cap growth.
            if len(states) > 200:
                stale = sorted(states.values(), key=lambda item: max(item.last_success, item.last_failure))[: len(states) - 200]
                for item in stale:
                    states.pop(item.cookie_hash, None)
        self.save()

    def record_success(self, platform: str, cookie: str) -> None:
        state = self._state(platform, cookie)
        if state is None:
            return
        with self._lock:
            state.success = min(100.0, state.success + 1.0)
            state.failure = max(0.0, state.failure - 0.25)
            state.empty = max(0.0, state.empty - 0.25)
            state.last_success = time.time()
            state.cooldown_until = 0.0
            state.last_reason = ""
        self.save(force=True)

    def record_failure(self, platform: str, cookie: str, reason: str = "", cooldown_seconds: float = 600.0) -> None:
        state = self._state(platform, cookie)
        if state is None:
            return
        lowered = str(reason or "").lower()
        now = time.time()
        cooldown = max(60.0, min(24 * 3600.0, float(cooldown_seconds or 600.0)))
        with self._lock:
            state.failure = min(100.0, state.failure + 1.0)
            if "empty" in lowered or "空响应" in lowered or "响应内容为空" in lowered:
                state.empty = min(100.0, state.empty + 1.0)
            state.last_failure = now
            state.cooldown_until = max(state.cooldown_until, now + cooldown)
            state.last_reason = str(reason or "")[:240]
            if state.failure >= 8.0 or state.empty >= 5.0:
                state.disabled_until = max(state.disabled_until, now + min(6 * 3600.0, cooldown * 2))
        self.save(force=True)

    def cooldown_until(self, platform: str, cookie: str) -> float:
        state = self._state(platform, cookie, create=False)
        if state is None:
            return 0.0
        return max(float(state.cooldown_until or 0.0), float(state.disabled_until or 0.0))

    def score(self, platform: str, cookie: str) -> float:
        state = self._state(platform, cookie, create=False)
        if state is None:
            return 1.0
        return 1.0 + state.success * 1.5 - state.failure * 2.0 - state.empty * 3.0

    def snapshot(self, platform: str = "douyin") -> dict[str, dict[str, float | str]]:
        platform_key = self._platform(platform) or "douyin"
        with self._lock:
            return {key: state.to_dict() for key, state in self._states.get(platform_key, {}).items()}


    def clear(self, platform: str = "") -> int:
        """Clear persisted health records without touching real Cookie values."""
        platform_key = self._platform(platform)
        with self._lock:
            if platform_key:
                count = len(self._states.get(platform_key, {}))
                self._states[platform_key] = {}
            else:
                count = sum(len(records) for records in self._states.values())
                self._states = {"douyin": {}, "tiktok": {}}
        self.save(force=True)
        return count

    def clear_expired_cooldowns(self) -> None:
        now = time.time()
        changed = False
        with self._lock:
            for records in self._states.values():
                for state in records.values():
                    if state.cooldown_until and state.cooldown_until <= now:
                        state.cooldown_until = 0.0
                        changed = True
                    if state.disabled_until and state.disabled_until <= now:
                        state.disabled_until = 0.0
                        # Do not instantly restore full trust after a long disable.
                        state.failure = min(state.failure, 3.0)
                        state.empty = min(state.empty, 2.0)
                        changed = True
        if changed:
            self.save()

    def _state(self, platform: str, cookie: str, *, create: bool = True) -> CookieHealthState | None:
        platform_key = self._platform(platform)
        key = self.cookie_hash(cookie)
        if not platform_key or not key:
            return None
        with self._lock:
            states = self._states.setdefault(platform_key, {})
            if key not in states and create:
                states[key] = CookieHealthState(cookie_hash=key, platform=platform_key)
            return states.get(key)

    @staticmethod
    def _platform(platform: str) -> str:
        value = str(platform or "").strip().lower()
        return value if value in {"douyin", "tiktok"} else ""
