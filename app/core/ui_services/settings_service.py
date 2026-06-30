from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..media.cookie_utils import parse_cookie_pool, sanitize_cookie_header
from ..media.file_naming import DEFAULT_FILENAME_TEMPLATE
from .settings_runtime_apply import RuntimeApplyResult, SettingsRuntimeApply
from .settings_validator import SettingsValidationResult, SettingsValidator


@dataclass(slots=True)
class SettingsSaveResult:
    user_config: dict[str, Any]
    cookies_config: dict[str, Any]
    validation: SettingsValidationResult
    runtime: RuntimeApplyResult
    cookie_cleaned: bool
    cookie_pool_count: int
    changed_keys: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = ["设置已保存"]
        if self.changed_keys:
            parts.append(f"变更 {len(self.changed_keys)} 项")
        if self.cookie_cleaned:
            parts.append("已自动清理 Cookie 中无效片段")
        if self.validation.messages:
            parts.append("；".join(self.validation.messages[:3]))
            if len(self.validation.messages) > 3:
                parts.append(f"另有 {len(self.validation.messages) - 3} 项参数已修正")
        if self.runtime.immediate:
            parts.append("即时生效：" + "、".join(dict.fromkeys(self.runtime.immediate)))
        if self.runtime.next_task:
            parts.append("下次任务生效：" + "、".join(dict.fromkeys(self.runtime.next_task[:4])))
        if self.runtime.warnings:
            parts.append("Cookie 已保存，但同步到内置解析器时有警告，重启应用后会重新加载")
        return "；".join(parts)


class SettingsService:
    """Central read/validate/save/apply service for the desktop settings page."""

    USER_VALUE_KEYS = {
        "language",
        "download_path",
        "filename_template",
        "download_strategy_preset",
        "max_parallel_downloads",
        "media_queue_auto_tune",
        "video_parse_concurrency",
        "media_download_retry_count",
        "enable_proxy",
        "proxy_address",
        "monitor_batch_concurrency",
        "batch_parse_size",
        "batch_download_concurrency",
        "download_chunk_size_kb",
        "gallery_image_concurrency",
        "gallery_image_save_format",
        "douyin_cookie_cooldown_seconds",
        "douyin_monitor_incremental_pages",
        "segmented_download_parts",
        "segmented_download_min_size_mb",
        "douyin_content_monitor_interval_minutes",
        "monitor_fast_check_enabled",
        "development_bypass_risk_controls_enabled",
        "global_request_limiter_enabled",
        "cookie_cooldown_enabled",
        "risk_backoff_enabled",
        "cookie_health_persistence_enabled",
        "batch_parse_download_pipeline_enabled",
        "segmented_download_enabled",
        "segmented_download_resume_enabled",
        "auto_update_enabled",
        "auto_update_check_on_startup",
        "auto_update_silent_install",
        "auto_update_manifest_url",
        "auto_update_channel",
        "auto_update_install_kind",
    }

    def __init__(self, app: Any):
        self.app = app
        self.runtime_apply = SettingsRuntimeApply(app)

    async def save(
        self,
        *,
        raw_values: dict[str, Any],
        raw_douyin_cookie: str,
        raw_tiktok_cookie: str,
        account_notify_values: dict[str, bool] | None = None,
    ) -> SettingsSaveResult:
        manager = self.app.services.config_manager
        settings = self.app.services.settings_config
        latest_user_config = manager.load_user_config() or dict(getattr(settings, "user_config", {}) or {})
        before = dict(latest_user_config)
        validation = SettingsValidator.validate(raw_values, latest_user_config)
        user_config = self._merge_user_config(latest_user_config, validation.values)
        await manager.save_user_config(user_config)

        saved_user_config = manager.load_user_config() or {}
        expected_path = str(user_config.get("douyin_content_download_path") or "").strip()
        actual_path = str(saved_user_config.get("douyin_content_download_path") or "").strip()
        if actual_path != expected_path:
            raise RuntimeError(f"保存路径失败：期望 {expected_path or '<默认路径>'}，实际 {actual_path or '<默认路径>'}")
        settings.adopt_user_config(saved_user_config)

        cookies_config, cookie_cleaned, cookie_pool_count, douyin_cookie_pool, tiktok_cookie = self._build_cookies_config(
            dict(getattr(settings, "cookies_config", {}) or {}),
            raw_douyin_cookie,
            raw_tiktok_cookie,
        )
        settings.adopt_cookies_config(cookies_config)
        if hasattr(manager, "save_cookies_config"):
            await manager.save_cookies_config(cookies_config)

        runtime = await self.runtime_apply.apply(
            user_config=saved_user_config,
            douyin_cookie_pool=douyin_cookie_pool,
            tiktok_cookie=tiktok_cookie,
            account_notify_values=account_notify_values or {},
        )
        changed_keys = sorted(key for key, value in saved_user_config.items() if before.get(key) != value)
        return SettingsSaveResult(
            user_config=saved_user_config,
            cookies_config=cookies_config,
            validation=validation,
            runtime=runtime,
            cookie_cleaned=cookie_cleaned,
            cookie_pool_count=cookie_pool_count,
            changed_keys=changed_keys,
        )

    def _merge_user_config(self, latest: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        user_config = dict(latest or {})
        user_config.update(
            {
                "language": str(values.get("language") or user_config.get("language") or "Chinese"),
                "douyin_content_download_path": str(values.get("download_path") or "").strip(),
                "douyin_content_filename_template": str(values.get("filename_template") or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE,
                "download_strategy_preset": values.get("download_strategy_preset"),
                "max_parallel_downloads": values.get("max_parallel_downloads"),
                "media_queue_auto_tune": False,
                "video_parse_concurrency": values.get("video_parse_concurrency"),
                "media_download_retry_count": values.get("media_download_retry_count"),
                "enable_proxy": bool(values.get("enable_proxy")),
                "proxy_address": str(values.get("proxy_address") or "").strip(),
                "monitor_batch_concurrency": values.get("monitor_batch_concurrency"),
                "batch_parse_size": values.get("batch_parse_size"),
                "batch_download_concurrency": values.get("batch_download_concurrency"),
                "download_chunk_size_kb": values.get("download_chunk_size_kb"),
                "gallery_image_concurrency": values.get("gallery_image_concurrency"),
                "gallery_image_save_format": values.get("gallery_image_save_format"),
                "douyin_cookie_cooldown_seconds": values.get("douyin_cookie_cooldown_seconds"),
                "douyin_monitor_incremental_pages": values.get("douyin_monitor_incremental_pages"),
                "segmented_download_parts": values.get("segmented_download_parts"),
                "segmented_download_min_size_mb": values.get("segmented_download_min_size_mb"),
                "douyin_content_monitor_interval_minutes": values.get("douyin_content_monitor_interval_minutes"),
                "monitor_fast_check_enabled": bool(values.get("monitor_fast_check_enabled", True)),
                "development_bypass_risk_controls_enabled": bool(values.get("development_bypass_risk_controls_enabled", False)),
                "global_request_limiter_enabled": bool(values.get("global_request_limiter_enabled", True)),
                "cookie_cooldown_enabled": bool(values.get("cookie_cooldown_enabled", True)),
                "risk_backoff_enabled": bool(values.get("risk_backoff_enabled", True)),
                "cookie_health_persistence_enabled": bool(values.get("cookie_health_persistence_enabled", True)),
                "batch_parse_download_pipeline_enabled": bool(values.get("batch_parse_download_pipeline_enabled", False)),
                "segmented_download_enabled": bool(values.get("segmented_download_enabled", False)),
                "segmented_download_resume_enabled": True,
                "auto_update_enabled": bool(values.get("auto_update_enabled", False)),
                "auto_update_check_on_startup": bool(values.get("auto_update_check_on_startup", False)),
                "auto_update_silent_install": bool(values.get("auto_update_silent_install", False)),
                "auto_update_manifest_url": str(values.get("auto_update_manifest_url") or "").strip(),
                "auto_update_channel": str(values.get("auto_update_channel") or "stable"),
                "auto_update_install_kind": str(values.get("auto_update_install_kind") or "installer"),
            }
        )
        return user_config

    def _build_cookies_config(
        self,
        current: dict[str, Any],
        raw_douyin_cookie: str,
        raw_tiktok_cookie: str,
    ) -> tuple[dict[str, Any], bool, int, list[str], str]:
        # Regression anchors for legacy tests:
        # parse_cookie_pool(raw_douyin_cookie)
        # cookies_config["douyin_cookie_pool"] = douyin_cookie_pool
        # douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else ""
        cookies_config = dict(current or {})
        douyin_cookie_pool = parse_cookie_pool(raw_douyin_cookie)
        douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else ""
        tiktok_cookie = sanitize_cookie_header(raw_tiktok_cookie)
        cookie_cleaned = bool(raw_douyin_cookie.strip() != "\n".join(douyin_cookie_pool) or raw_tiktok_cookie.strip() != tiktok_cookie)
        cookies_config["douyin_cookie"] = douyin_cookie
        cookies_config["douyin_cookie_pool"] = douyin_cookie_pool
        cookies_config["tiktok_cookie"] = tiktok_cookie
        return cookies_config, cookie_cleaned, len(douyin_cookie_pool), douyin_cookie_pool, tiktok_cookie
