from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from ..media.cookie_utils import cookie_looks_usable, parse_cookie_pool, sanitize_cookie_header


@dataclass(slots=True)
class CookieInventoryItem:
    platform: str
    index: int
    cookie_hash: str
    masked: str
    key_count: int
    length: int
    usable: bool
    status: str = "unknown"
    cooldown_seconds: float = 0.0
    failure: float = 0.0
    empty: float = 0.0
    last_reason: str = ""

    def summary(self) -> str:
        state = self.status
        if self.cooldown_seconds > 0:
            state = f"cooldown {int(self.cooldown_seconds)}s"
        if not self.usable:
            state = "格式可疑"
        return f"#{self.index} {self.masked} · {self.key_count} 键 · {state}"


@dataclass(slots=True)
class CookieInventory:
    platform: str
    items: list[CookieInventoryItem] = field(default_factory=list)
    raw_entries: int = 0
    sanitized_count: int = 0
    duplicate_or_invalid: int = 0

    @property
    def usable_count(self) -> int:
        return sum(1 for item in self.items if item.usable)

    @property
    def suspicious_count(self) -> int:
        return sum(1 for item in self.items if not item.usable)

    @property
    def cooldown_count(self) -> int:
        return sum(1 for item in self.items if item.cooldown_seconds > 0 or item.status in {"cooldown", "disabled"})

    def summary(self) -> str:
        label = "抖音" if self.platform == "douyin" else "TikTok"
        base = f"{label} Cookie：{len(self.items)} 个，格式可用 {self.usable_count} 个"
        if self.suspicious_count:
            base += f"，可疑 {self.suspicious_count} 个"
        if self.cooldown_count:
            base += f"，冷却/禁用 {self.cooldown_count} 个"
        if self.duplicate_or_invalid:
            base += f"，已忽略重复或无效片段 {self.duplicate_or_invalid} 个"
        if not self.items:
            base = f"{label} Cookie：未配置"
        return base

    def details(self, limit: int = 8) -> str:
        if not self.items:
            return self.summary()
        shown = self.items[: max(1, limit)]
        lines = [self.summary(), *[item.summary() for item in shown]]
        if len(self.items) > len(shown):
            lines.append(f"另有 {len(self.items) - len(shown)} 个未显示。")
        return "\n".join(lines)


class SettingsCookieService:
    """Cookie pool inventory and diagnostics without exposing Cookie secrets."""

    def __init__(self, app: Any):
        self.app = app

    def analyze(self, platform: str, raw_cookie_text: str | list[str] | tuple[str, ...]) -> CookieInventory:
        platform_key = self._platform(platform)
        raw_entries = self._rough_entry_count(raw_cookie_text)
        pool = parse_cookie_pool(raw_cookie_text)
        health = self._health_snapshot(platform_key)
        items: list[CookieInventoryItem] = []
        for index, cookie in enumerate(pool, start=1):
            cookie_hash = self._cookie_hash(cookie)
            state = dict(health.get(cookie_hash, {}) or {})
            cooldown_seconds = self._remaining_seconds(state.get("cooldown_until"), state.get("disabled_until"))
            status = self._status_from_state(state, cooldown_seconds)
            items.append(
                CookieInventoryItem(
                    platform=platform_key,
                    index=index,
                    cookie_hash=cookie_hash,
                    masked=self.mask_cookie(cookie),
                    key_count=self._key_count(cookie),
                    length=len(cookie),
                    usable=cookie_looks_usable(cookie),
                    status=status,
                    cooldown_seconds=cooldown_seconds,
                    failure=float(state.get("failure") or 0.0),
                    empty=float(state.get("empty") or 0.0),
                    last_reason=str(state.get("last_reason") or ""),
                )
            )
        duplicate_or_invalid = max(0, raw_entries - len(pool))
        return CookieInventory(
            platform=platform_key,
            items=items,
            raw_entries=raw_entries,
            sanitized_count=len(pool),
            duplicate_or_invalid=duplicate_or_invalid,
        )

    def summarize_pair(self, douyin_raw: str, tiktok_raw: str) -> str:
        douyin = self.analyze("douyin", douyin_raw)
        tiktok = self.analyze("tiktok", tiktok_raw)
        return f"{douyin.summary()}\n{tiktok.summary()}"

    def register_current_pool(self, platform: str, raw_cookie_text: str) -> int:
        """Register configured cookies with the health store without writing real Cookie values."""
        pool = parse_cookie_pool(raw_cookie_text)
        store = getattr(getattr(self.app, "services", None), "cookie_health_store", None)
        if store is not None and hasattr(store, "register_pool"):
            store.register_pool(self._platform(platform), pool)
        return len(pool)

    @staticmethod
    def mask_cookie(cookie: str) -> str:
        sanitized = sanitize_cookie_header(cookie)
        if not sanitized:
            return "<empty>"
        keys = []
        for part in sanitized.split(";"):
            key = part.split("=", 1)[0].strip()
            if key:
                keys.append(key)
            if len(keys) >= 3:
                break
        key_text = ",".join(keys) if keys else "cookie"
        return f"{key_text}…({len(sanitized)} chars)"

    def _health_snapshot(self, platform: str) -> dict[str, dict[str, Any]]:
        store = getattr(getattr(self.app, "services", None), "cookie_health_store", None)
        if store is None or not hasattr(store, "snapshot"):
            return {}
        try:
            return dict(store.snapshot(platform) or {})
        except Exception:
            return {}

    def _cookie_hash(self, cookie: str) -> str:
        store = getattr(getattr(self.app, "services", None), "cookie_health_store", None)
        if store is not None and hasattr(store, "cookie_hash"):
            try:
                return str(store.cookie_hash(cookie) or "")
            except Exception:
                pass
        import hashlib

        return hashlib.sha256(str(cookie or "").encode("utf-8", errors="ignore")).hexdigest()[:24]

    @staticmethod
    def _key_count(cookie: str) -> int:
        return sum(1 for part in sanitize_cookie_header(cookie).split(";") if "=" in part)

    @staticmethod
    def _rough_entry_count(raw_cookie_text: str | list[str] | tuple[str, ...]) -> int:
        if isinstance(raw_cookie_text, (list, tuple)):
            return len([item for item in raw_cookie_text if str(item or "").strip()])
        text = str(raw_cookie_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            return 0
        blocks = [block.strip() for block in text.split("\n\n") if block.strip()]
        if len(blocks) > 1:
            return len(blocks)
        lines = [line.strip() for line in text.split("\n") if line.strip()]
        return len(lines) if len(lines) > 1 else 1

    @staticmethod
    def _remaining_seconds(*timestamps: Any) -> float:
        now = time.time()
        values = []
        for value in timestamps:
            try:
                parsed = float(value or 0.0)
            except (TypeError, ValueError):
                parsed = 0.0
            values.append(max(0.0, parsed - now))
        return round(max(values or [0.0]), 1)

    @staticmethod
    def _status_from_state(state: dict[str, Any], cooldown_seconds: float) -> str:
        if not state:
            return "unknown"
        if cooldown_seconds > 0:
            try:
                if float(state.get("disabled_until") or 0.0) > time.time():
                    return "disabled"
            except (TypeError, ValueError):
                pass
            return "cooldown"
        try:
            failure = float(state.get("failure") or 0.0)
            empty = float(state.get("empty") or 0.0)
        except (TypeError, ValueError):
            failure = empty = 0.0
        if failure >= 3 or empty >= 2:
            return "degraded"
        return "healthy"

    @staticmethod
    def _platform(platform: str) -> str:
        value = str(platform or "douyin").strip().lower()
        return value if value in {"douyin", "tiktok"} else "douyin"
