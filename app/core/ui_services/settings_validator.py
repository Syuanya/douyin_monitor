from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..media.file_naming import DEFAULT_FILENAME_TEMPLATE
from .settings_proxy_service import SettingsProxyService


@dataclass(slots=True)
class SettingsValidationResult:
    values: dict[str, Any]
    messages: list[str] = field(default_factory=list)

    @property
    def has_messages(self) -> bool:
        return bool(self.messages)


class SettingsValidator:
    """Normalize settings form values and report user-visible corrections.

    The settings page should not silently coerce invalid input.  This helper
    keeps the validation policy in one place so desktop, fallback UI and future
    web endpoints can use the same constraints.
    """

    DOWNLOAD_STRATEGY_KEYS = {"conservative", "standard", "fast", "custom"}
    GALLERY_IMAGE_FORMATS = {"original", "png"}
    AUTO_UPDATE_CHANNELS = {"stable", "beta", "dev"}
    AUTO_UPDATE_INSTALL_KINDS = {"installer", "portable"}

    INT_LIMITS: dict[str, tuple[str, int, int, int]] = {
        "max_parallel_downloads": ("下载并发数", 2, 1, 16),
        "video_parse_concurrency": ("解析并发数", 4, 1, 16),
        "media_download_retry_count": ("下载失败重试次数", 1, 0, 5),
        "monitor_batch_concurrency": ("监控并发", 2, 1, 16),
        "batch_parse_size": ("解析批大小", 20, 1, 500),
        "batch_download_concurrency": ("批量下载并发", 3, 1, 32),
        "download_chunk_size_kb": ("下载块 KB", 512, 64, 8192),
        "gallery_image_concurrency": ("图集图片并发", 4, 1, 32),
        "douyin_cookie_cooldown_seconds": ("Cookie 冷却秒", 600, 60, 3600),
        "douyin_monitor_incremental_pages": ("增量页数", 3, 1, 20),
        "segmented_download_parts": ("分片数", 4, 2, 16),
        "segmented_download_min_size_mb": ("分片阈值 MB", 50, 1, 4096),
    }

    @classmethod
    def validate(cls, raw_values: dict[str, Any], current: dict[str, Any] | None = None) -> SettingsValidationResult:
        current = dict(current or {})
        values = dict(raw_values or {})
        messages: list[str] = []

        language = str(values.get("language") or current.get("language") or "Chinese")
        values["language"] = language
        values["download_path"] = str(values.get("download_path") or "").strip()
        values["filename_template"] = str(values.get("filename_template") or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE

        strategy = str(values.get("download_strategy_preset") or current.get("download_strategy_preset") or "standard")
        if strategy not in cls.DOWNLOAD_STRATEGY_KEYS:
            messages.append(f"下载策略 {strategy} 无效，已改为 standard。")
            strategy = "standard"
        values["download_strategy_preset"] = strategy

        for key, (label, default, minimum, maximum) in cls.INT_LIMITS.items():
            raw = values.get(key, current.get(key, default))
            parsed, note = cls._bounded_int(raw, default, minimum, maximum, label)
            values[key] = parsed
            if note:
                messages.append(note)

        monitor_raw = values.get("douyin_content_monitor_interval_minutes", current.get("douyin_content_monitor_interval_minutes", 10))
        monitor_interval, note = cls._bounded_float(monitor_raw, 10.0, 1.0, 10080.0, "监控间隔分钟")
        values["douyin_content_monitor_interval_minutes"] = monitor_interval
        if note:
            messages.append(note)

        gallery_format = str(values.get("gallery_image_save_format") or current.get("gallery_image_save_format") or "original")
        if gallery_format not in cls.GALLERY_IMAGE_FORMATS:
            messages.append(f"图集保存格式 {gallery_format} 无效，已改为 original。")
            gallery_format = "original"
        values["gallery_image_save_format"] = gallery_format

        channel = str(values.get("auto_update_channel") or current.get("auto_update_channel") or "stable")
        if channel not in cls.AUTO_UPDATE_CHANNELS:
            messages.append(f"更新通道 {channel} 无效，已改为 stable。")
            channel = "stable"
        values["auto_update_channel"] = channel

        install_kind = str(values.get("auto_update_install_kind") or current.get("auto_update_install_kind") or "installer")
        if install_kind not in cls.AUTO_UPDATE_INSTALL_KINDS:
            messages.append(f"更新包类型 {install_kind} 无效，已改为 installer。")
            install_kind = "installer"
        values["auto_update_install_kind"] = install_kind

        bool_defaults = {
            "monitor_fast_check_enabled": True,
            "development_bypass_risk_controls_enabled": False,
            "global_request_limiter_enabled": True,
            "cookie_cooldown_enabled": True,
            "risk_backoff_enabled": True,
            "cookie_health_persistence_enabled": True,
            "batch_parse_download_pipeline_enabled": False,
            "segmented_download_enabled": False,
            "auto_update_enabled": False,
            "auto_update_check_on_startup": False,
            "auto_update_silent_install": False,
            "enable_proxy": False,
        }
        for key, default in bool_defaults.items():
            values[key] = cls._as_bool(values.get(key, current.get(key, default)))

        if values["development_bypass_risk_controls_enabled"]:
            changed = []
            for key, label in (
                ("global_request_limiter_enabled", "全局请求限速"),
                ("cookie_cooldown_enabled", "Cookie 失败冷却"),
                ("risk_backoff_enabled", "风控退避"),
            ):
                if values.get(key):
                    changed.append(label)
                values[key] = False
            if changed:
                messages.append("开发模式已开启，" + "、".join(changed) + "已按实际运行逻辑自动关闭。")

        proxy_validation = SettingsProxyService.validate(
            str(values.get("proxy_address") or "").strip(),
            enabled=bool(values.get("enable_proxy", False)),
        )
        values["proxy_address"] = proxy_validation.normalized if proxy_validation.ok and proxy_validation.enabled else str(values.get("proxy_address") or "").strip()
        if bool(values.get("enable_proxy", False)):
            if not proxy_validation.ok:
                messages.append(proxy_validation.summary())
            elif proxy_validation.warning:
                messages.append(proxy_validation.warning)
        values["auto_update_manifest_url"] = str(values.get("auto_update_manifest_url") or "").strip()
        return SettingsValidationResult(values=values, messages=messages)

    @staticmethod
    def _bounded_int(value: Any, default: int, minimum: int, maximum: int, label: str) -> tuple[int, str | None]:
        raw_text = "" if value is None else str(value).strip()
        try:
            parsed = int(raw_text if raw_text else default)
        except (TypeError, ValueError):
            return default, f"{label}输入无效，已改为默认值 {default}。"
        bounded = max(minimum, min(maximum, parsed))
        if bounded != parsed:
            return bounded, f"{label} {parsed} 超出范围 {minimum}-{maximum}，已修正为 {bounded}。"
        return bounded, None

    @staticmethod
    def _bounded_float(value: Any, default: float, minimum: float, maximum: float, label: str) -> tuple[float, str | None]:
        raw_text = "" if value is None else str(value).strip()
        try:
            parsed = float(raw_text if raw_text else default)
        except (TypeError, ValueError):
            return default, f"{label}输入无效，已改为默认值 {default:g}。"
        bounded = max(minimum, min(maximum, parsed))
        if bounded != parsed:
            return bounded, f"{label} {parsed:g} 超出范围 {minimum:g}-{maximum:g}，已修正为 {bounded:g}。"
        return bounded, None

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"", "0", "false", "no", "off", "disabled"}
        return bool(value)
