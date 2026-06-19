from __future__ import annotations

from typing import Any


BOOL_KEYS = {
    "startup_cleanup_enabled",
    "onboarding_completed",
    "diagnostic_redact_sensitive_urls",
    "secure_cookie_storage_enabled",
    "media_queue_auto_tune",
    "media_task_queue_log_enabled",
    "download_resume_enabled",
    "sqlite_json_mirror_enabled",
    "douyin_content_notify_enabled",
    "enable_proxy",
}

INT_RANGES = {
    "config_version": (1, 999),
    "diagnostic_export_recent_log_kb": (64, 10240),
    "media_download_retry_count": (0, 5),
    "douyin_external_api_max_pages": (1, 200),
    "douyin_parser_max_pages": (1, 200),
    "video_parse_concurrency": (1, 32),
    "max_parallel_downloads": (0, 64),
}

FLOAT_RANGES = {
    "media_task_progress_interval_seconds": (0.3, 10.0),
    "media_download_progress_interval_seconds": (0.5, 10.0),
    "douyin_content_monitor_interval_minutes": (1.0, 1440.0),
    "douyin_content_check_interval_between_users_seconds": (0.0, 3600.0),
    "douyin_content_request_timeout_seconds": (5.0, 300.0),
}

ENUMS = {
    "theme_mode": {"light", "dark", "system"},
    "douyin_parser_backend": {"internal", "external"},
}


def validate_user_config(user_config: dict[str, Any], default_config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return a sanitized config without mutating the input."""
    defaults = dict(default_config or {})
    result = dict(defaults)
    result.update(user_config or {})

    for key in BOOL_KEYS:
        if key in result:
            result[key] = _as_bool(result[key], bool(defaults.get(key, False)))

    for key, (minimum, maximum) in INT_RANGES.items():
        if key in result:
            result[key] = _clamp_int(result[key], int(defaults.get(key, minimum)), minimum, maximum)

    for key, (minimum, maximum) in FLOAT_RANGES.items():
        if key in result:
            result[key] = _clamp_float(result[key], float(defaults.get(key, minimum)), minimum, maximum)

    for key, allowed in ENUMS.items():
        if key in result:
            value = str(result.get(key) or defaults.get(key) or "").strip().lower()
            default_value = str(defaults.get(key) or next(iter(allowed))).strip().lower()
            result[key] = value if value in allowed else default_value

    return result


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        text = value.strip().lower()
        if text in {"1", "true", "yes", "on", "y"}:
            return True
        if text in {"0", "false", "no", "off", "n"}:
            return False
    if value in (0, 1):
        return bool(value)
    return default


def _clamp_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _clamp_float(value: Any, default: float, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))
