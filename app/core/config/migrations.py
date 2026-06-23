from __future__ import annotations

from typing import Any


def migrate_user_config(user_config: dict[str, Any], default_config: dict[str, Any]) -> tuple[dict[str, Any], bool, int, int]:
    current = _safe_int(user_config.get("config_version"), 0)
    target = _safe_int(default_config.get("config_version"), current or 1)
    migrated = dict(user_config or {})
    changed = False

    if current < 2 <= target:
        if not migrated.get("douyin_parser_backend"):
            migrated["douyin_parser_backend"] = "external" if migrated.get("douyin_external_api_base_url") else "internal"
            changed = True
        if not migrated.get("douyin_parser_max_pages") and migrated.get("douyin_external_api_max_pages"):
            migrated["douyin_parser_max_pages"] = migrated.get("douyin_external_api_max_pages")
            changed = True

    if current < 3 <= target:
        for key, value in {
            "secure_cookie_storage_enabled": True,
            "download_resume_enabled": True,
        }.items():
            if key not in migrated:
                migrated[key] = value
                changed = True

    if current < 4 <= target:
        if "sqlite_json_mirror_enabled" not in migrated:
            migrated["sqlite_json_mirror_enabled"] = True
            changed = True

    if current < 5 <= target:
        for key, value in {
            "auto_update_enabled": False,
            "auto_update_check_on_startup": False,
            "auto_update_manifest_url": "",
            "auto_update_channel": "stable",
            "auto_update_silent_install": False,
            "auto_update_install_kind": "installer",
        }.items():
            if key not in migrated:
                migrated[key] = value
                changed = True

    for key, value in default_config.items():
        if key not in migrated:
            migrated[key] = value
            changed = True

    if current < target:
        migrated["config_version"] = target
        changed = True

    return migrated, changed, current, target


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
