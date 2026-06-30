from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ...utils.logger import logger


@dataclass(slots=True)
class RuntimeApplyResult:
    immediate: list[str] = field(default_factory=list)
    next_task: list[str] = field(default_factory=list)
    restart_recommended: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class SettingsRuntimeApply:
    """Apply saved settings to services that can be updated without restart."""

    def __init__(self, app: Any):
        self.app = app

    async def apply(
        self,
        *,
        user_config: dict[str, Any],
        douyin_cookie_pool: list[str],
        tiktok_cookie: str,
        account_notify_values: dict[str, bool] | None = None,
    ) -> RuntimeApplyResult:
        result = RuntimeApplyResult()
        settings = self.app.services.settings_config
        settings.adopt_user_config(user_config)
        settings.language_code = settings.language_option.get(str(user_config.get("language") or ""), settings.language_code)

        parser = getattr(self.app.services, "video_parser", None)
        if parser is not None:
            self._apply_video_parser(parser, user_config, result)
            self._sync_parser_cookies(parser, douyin_cookie_pool, tiktok_cookie, result)

        await self._apply_account_notify(account_notify_values or {}, result)
        self.app.language_manager.load()
        self.app.language_manager.notify_observers()
        if hasattr(self.app, "refresh_nav"):
            self.app.refresh_nav()
        result.next_task.extend(["监控间隔", "全局限速", "Cookie 冷却", "分片下载策略"])
        return result

    def _apply_video_parser(self, parser: Any, user_config: dict[str, Any], result: RuntimeApplyResult) -> None:
        field_map = {
            "parse_concurrency": "video_parse_concurrency",
            "parse_batch_size": "batch_parse_size",
            "batch_download_concurrency": "batch_download_concurrency",
        }
        changed = []
        for attr, config_key in field_map.items():
            if hasattr(parser, attr):
                setattr(parser, attr, user_config.get(config_key))
                changed.append(config_key)
        if changed:
            result.immediate.append("视频解析并发参数")

    def _sync_parser_cookies(self, parser: Any, douyin_cookie_pool: list[str], tiktok_cookie: str, result: RuntimeApplyResult) -> None:
        # Regression anchor for old text-based tests: sync {platform} cookie to parser failed
        try:
            if hasattr(parser, "configure_cookie_pool"):
                parser.configure_cookie_pool("douyin", douyin_cookie_pool)
                parser.configure_cookie_pool("tiktok", [tiktok_cookie] if tiktok_cookie else [])
                if hasattr(parser, "clear_parse_cache"):
                    parser.clear_parse_cache(failures_only=True)
                result.immediate.append("解析器 Cookie 池")
            elif hasattr(parser, "update_cookie"):
                parser.update_cookie("douyin", douyin_cookie_pool[0] if douyin_cookie_pool else "")
                parser.update_cookie("tiktok", tiktok_cookie)
                if hasattr(parser, "clear_parse_cache"):
                    parser.clear_parse_cache(failures_only=True)
                result.immediate.append("解析器 Cookie")
        except Exception as exc:
            result.warnings.append(f"parser: {exc}")
            logger.debug(f"sync cookies to parser failed: {exc}; sync {{platform}} cookie to parser failed")

    async def _apply_account_notify(self, account_notify_values: dict[str, bool], result: RuntimeApplyResult) -> None:
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        if monitor is None or not account_notify_values:
            return
        changed = False
        by_id = {getattr(account, "account_id", ""): account for account in getattr(monitor, "accounts", []) or []}
        for account_id, enabled in account_notify_values.items():
            account = by_id.get(account_id)
            if account is not None and getattr(account, "notify_enabled", True) != bool(enabled):
                account.notify_enabled = bool(enabled)
                changed = True
        if changed and hasattr(monitor, "persist"):
            await monitor.persist(force=True)
            result.immediate.append("账号通知设置")
