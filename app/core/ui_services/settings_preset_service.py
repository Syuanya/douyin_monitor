from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class SettingsPreset:
    key: str
    label: str
    description: str
    values: dict[str, Any]


@dataclass(slots=True)
class SettingsPresetApplyResult:
    preset: SettingsPreset
    values: dict[str, Any]
    changed_keys: list[str]

    def summary(self) -> str:
        if not self.changed_keys:
            return f"已选择 {self.preset.label}，当前表单无需调整。"
        names = SettingsPresetService.labels_for_keys(self.changed_keys[:8])
        suffix = "" if len(self.changed_keys) <= 8 else f"，另有 {len(self.changed_keys) - 8} 项"
        return f"已套用 {self.preset.label}：调整 {len(self.changed_keys)} 项（{'、'.join(names)}{suffix}）。请点击保存后生效。"


class SettingsPresetService:
    """Runtime-mode presets for the settings page.

    These presets intentionally operate on the form values only.  They do not
    persist anything until the user clicks Save, which keeps the operation safe
    and reversible.
    """

    KEY_LABELS: dict[str, str] = {
        "download_strategy_preset": "下载策略",
        "max_parallel_downloads": "下载并发",
        "video_parse_concurrency": "解析并发",
        "media_download_retry_count": "失败重试",
        "monitor_batch_concurrency": "监控并发",
        "batch_parse_size": "解析批大小",
        "batch_download_concurrency": "批量下载并发",
        "download_chunk_size_kb": "下载块",
        "gallery_image_concurrency": "图集并发",
        "douyin_cookie_cooldown_seconds": "Cookie 冷却",
        "douyin_monitor_incremental_pages": "增量页数",
        "segmented_download_parts": "分片数",
        "segmented_download_min_size_mb": "分片阈值",
        "monitor_fast_check_enabled": "快速检查",
        "development_bypass_risk_controls_enabled": "开发模式",
        "global_request_limiter_enabled": "全局限速",
        "cookie_cooldown_enabled": "Cookie 冷却开关",
        "risk_backoff_enabled": "风控退避",
        "cookie_health_persistence_enabled": "Cookie 健康持久化",
        "batch_parse_download_pipeline_enabled": "解析下载流水线",
        "segmented_download_enabled": "分片下载",
    }

    PRESETS: dict[str, SettingsPreset] = {
        "stable": SettingsPreset(
            key="stable",
            label="稳定长期运行",
            description="低并发、强限速、强冷却，适合账号多、长时间后台监控。",
            values={
                "download_strategy_preset": "conservative",
                "max_parallel_downloads": 1,
                "video_parse_concurrency": 2,
                "media_download_retry_count": 2,
                "monitor_batch_concurrency": 1,
                "batch_parse_size": 10,
                "batch_download_concurrency": 1,
                "download_chunk_size_kb": 512,
                "gallery_image_concurrency": 2,
                "douyin_cookie_cooldown_seconds": 900,
                "douyin_monitor_incremental_pages": 2,
                "segmented_download_parts": 4,
                "segmented_download_min_size_mb": 100,
                "monitor_fast_check_enabled": False,
                "development_bypass_risk_controls_enabled": False,
                "global_request_limiter_enabled": True,
                "cookie_cooldown_enabled": True,
                "risk_backoff_enabled": True,
                "cookie_health_persistence_enabled": True,
                "batch_parse_download_pipeline_enabled": False,
                "segmented_download_enabled": False,
            },
        ),
        "standard": SettingsPreset(
            key="standard",
            label="标准日常使用",
            description="默认平衡配置，兼顾解析速度和风控安全，适合大多数场景。",
            values={
                "download_strategy_preset": "standard",
                "max_parallel_downloads": 2,
                "video_parse_concurrency": 4,
                "media_download_retry_count": 1,
                "monitor_batch_concurrency": 2,
                "batch_parse_size": 20,
                "batch_download_concurrency": 3,
                "download_chunk_size_kb": 512,
                "gallery_image_concurrency": 4,
                "douyin_cookie_cooldown_seconds": 600,
                "douyin_monitor_incremental_pages": 3,
                "segmented_download_parts": 4,
                "segmented_download_min_size_mb": 50,
                "monitor_fast_check_enabled": True,
                "development_bypass_risk_controls_enabled": False,
                "global_request_limiter_enabled": True,
                "cookie_cooldown_enabled": True,
                "risk_backoff_enabled": True,
                "cookie_health_persistence_enabled": True,
                "batch_parse_download_pipeline_enabled": False,
                "segmented_download_enabled": False,
            },
        ),
        "fast": SettingsPreset(
            key="fast",
            label="高速批量处理",
            description="提高解析和下载并发，适合短时间批量解析下载；风控风险高于标准模式。",
            values={
                "download_strategy_preset": "fast",
                "max_parallel_downloads": 4,
                "video_parse_concurrency": 6,
                "media_download_retry_count": 1,
                "monitor_batch_concurrency": 4,
                "batch_parse_size": 50,
                "batch_download_concurrency": 5,
                "download_chunk_size_kb": 1024,
                "gallery_image_concurrency": 6,
                "douyin_cookie_cooldown_seconds": 600,
                "douyin_monitor_incremental_pages": 5,
                "segmented_download_parts": 6,
                "segmented_download_min_size_mb": 80,
                "monitor_fast_check_enabled": True,
                "development_bypass_risk_controls_enabled": False,
                "global_request_limiter_enabled": True,
                "cookie_cooldown_enabled": True,
                "risk_backoff_enabled": True,
                "cookie_health_persistence_enabled": True,
                "batch_parse_download_pipeline_enabled": True,
                "segmented_download_enabled": True,
            },
        ),
        "diagnostic": SettingsPreset(
            key="diagnostic",
            label="开发诊断模式",
            description="仅用于排查问题；保存后会跳过冷却、限速和风控退避，不建议长期使用。",
            values={
                "download_strategy_preset": "standard",
                "max_parallel_downloads": 2,
                "video_parse_concurrency": 3,
                "media_download_retry_count": 0,
                "monitor_batch_concurrency": 1,
                "batch_parse_size": 10,
                "batch_download_concurrency": 2,
                "download_chunk_size_kb": 512,
                "gallery_image_concurrency": 3,
                "douyin_cookie_cooldown_seconds": 60,
                "douyin_monitor_incremental_pages": 1,
                "segmented_download_parts": 4,
                "segmented_download_min_size_mb": 100,
                "monitor_fast_check_enabled": False,
                "development_bypass_risk_controls_enabled": True,
                "global_request_limiter_enabled": False,
                "cookie_cooldown_enabled": False,
                "risk_backoff_enabled": False,
                "cookie_health_persistence_enabled": True,
                "batch_parse_download_pipeline_enabled": False,
                "segmented_download_enabled": False,
            },
        ),
    }

    @classmethod
    def get(cls, key: str) -> SettingsPreset:
        return cls.PRESETS.get(str(key or "standard"), cls.PRESETS["standard"])

    @classmethod
    def labels_for_keys(cls, keys: list[str]) -> list[str]:
        return [cls.KEY_LABELS.get(key, key) for key in keys]

    @classmethod
    def apply(cls, current_values: dict[str, Any], preset_key: str) -> SettingsPresetApplyResult:
        preset = cls.get(preset_key)
        values = dict(current_values or {})
        changed_keys: list[str] = []
        for key, value in preset.values.items():
            old = values.get(key)
            if cls._normalize_compare(old) != cls._normalize_compare(value):
                changed_keys.append(key)
            values[key] = value
        return SettingsPresetApplyResult(preset=preset, values=values, changed_keys=changed_keys)

    @staticmethod
    def _normalize_compare(value: Any) -> str:
        if isinstance(value, bool):
            return "1" if value else "0"
        return str(value if value is not None else "").strip()
