from __future__ import annotations

import inspect
import os
import zipfile
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from ..media.cookie_utils import cookie_looks_usable, parse_cookie_pool, sanitize_cookie_header
from ..media.file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename


class SettingsWorkflow:
    """Settings-page workflow that contains validation, preview and persistence helpers."""

    DOWNLOAD_STRATEGIES = {
        "conservative": {"label": "保守模式", "max_parallel_downloads": 1, "video_parse_concurrency": 2, "media_download_retry_count": 2, "monitor_batch_concurrency": 1, "gallery_image_concurrency": 2, "batch_download_concurrency": 1},
        "standard": {"label": "标准模式", "max_parallel_downloads": 2, "video_parse_concurrency": 4, "media_download_retry_count": 1, "monitor_batch_concurrency": 2, "gallery_image_concurrency": 4, "batch_download_concurrency": 3},
        "fast": {"label": "快速模式", "max_parallel_downloads": 4, "video_parse_concurrency": 6, "media_download_retry_count": 1, "monitor_batch_concurrency": 4, "gallery_image_concurrency": 6, "batch_download_concurrency": 5},
        "custom": {"label": "自定义", "max_parallel_downloads": None, "video_parse_concurrency": None, "media_download_retry_count": None},
    }

    def __init__(self, app: Any):
        self.app = app

    def strategy_values(self, preset: str) -> dict[str, Any]:
        return dict(self.DOWNLOAD_STRATEGIES.get(str(preset or "standard"), self.DOWNLOAD_STRATEGIES["standard"]))

    @staticmethod
    def bounded_int(value: Any, default: int, minimum: int, maximum: int) -> int:
        try:
            parsed = int(value if value not in (None, "") else default)
        except (TypeError, ValueError):
            parsed = default
        return max(minimum, min(maximum, parsed))

    def storage_dir(self) -> str:
        settings = self.app.services.settings_config
        path = str(getattr(settings, "user_config", {}).get("douyin_content_download_path") or "").strip()
        return path or os.path.join(self.app.run_path, "downloads", "douyin_content")

    def filename_preview(self, template: str) -> str:
        template = str(template or DEFAULT_FILENAME_TEMPLATE)
        filename = format_media_filename(
            template,
            {
                "platform": "douyin",
                "author": "示例作者",
                "item_id": "7123456789012345678",
                "title": "示例作品标题",
                "date": "20260616",
            },
            fallback="preview",
        )
        return f"命名预览：{os.path.join(self.storage_dir(), filename)}.mp4"

    @staticmethod
    def looks_like_cookie(cookie: str) -> bool:
        return cookie_looks_usable(cookie)

    @staticmethod
    def format_cookie_pool_for_field(cookies_config: dict[str, Any], platform: str) -> str:
        if platform == "douyin":
            pool = [str(item).strip() for item in cookies_config.get("douyin_cookie_pool", []) if str(item).strip()]
            if pool:
                return "\n".join(pool)
            return str(cookies_config.get("douyin_cookie") or "")
        return str(cookies_config.get(f"{platform}_cookie") or "")

    async def default_cookie_test(self, platform: str, cookie: str, proxy: str | None = None) -> dict[str, Any]:
        if not cookie:
            return {"success": False, "reason": "Cookie 为空"}
        url = "https://www.douyin.com/" if platform == "douyin" else "https://www.tiktok.com/"
        cookie = sanitize_cookie_header(cookie)
        headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie}
        try:
            async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=8, follow_redirects=True) as client:
                response = await client.get(url)
            return {"success": response.status_code < 400, "reason": f"{platform} Cookie 检测：HTTP {response.status_code}"}
        except Exception as exc:
            return {"success": False, "reason": f"{platform} Cookie 检测失败：{exc}"}

    def build_user_config(self, current: dict[str, Any], values: dict[str, Any]) -> dict[str, Any]:
        user_config = dict(current or {})
        language = values.get("language") or user_config.get("language") or "Chinese"
        download_strategy = str(values.get("download_strategy_preset") or user_config.get("download_strategy_preset") or "standard")
        if download_strategy not in self.DOWNLOAD_STRATEGIES:
            download_strategy = "standard"
        user_config.update(
            {
                "language": str(language),
                "douyin_content_download_path": str(values.get("download_path") or "").strip(),
                "douyin_content_filename_template": str(values.get("filename_template") or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE,
                "download_strategy_preset": download_strategy,
                "max_parallel_downloads": self.bounded_int(values.get("max_parallel_downloads"), 2, 1, 16),
                "media_queue_auto_tune": False,
                "video_parse_concurrency": self.bounded_int(values.get("video_parse_concurrency"), 4, 1, 16),
                "media_download_retry_count": self.bounded_int(values.get("media_download_retry_count"), 1, 0, 5),
                "enable_proxy": bool(values.get("enable_proxy")),
                "proxy_address": str(values.get("proxy_address") or "").strip(),

                "monitor_batch_concurrency": self.bounded_int(values.get("monitor_batch_concurrency"), 2, 1, 16),
                "batch_parse_size": self.bounded_int(values.get("batch_parse_size"), 20, 1, 500),
                "batch_download_concurrency": self.bounded_int(values.get("batch_download_concurrency"), 3, 1, 32),
                "download_chunk_size_kb": self.bounded_int(values.get("download_chunk_size_kb"), 512, 64, 8192),
                "gallery_image_concurrency": self.bounded_int(values.get("gallery_image_concurrency"), 4, 1, 32),
                "douyin_cookie_cooldown_seconds": self.bounded_int(values.get("douyin_cookie_cooldown_seconds"), 600, 60, 3600),
                "douyin_monitor_incremental_pages": self.bounded_int(values.get("douyin_monitor_incremental_pages"), 3, 1, 20),
                "segmented_download_parts": self.bounded_int(values.get("segmented_download_parts"), 4, 2, 16),
                "segmented_download_min_size_mb": self.bounded_int(values.get("segmented_download_min_size_mb"), 50, 1, 4096),
                "monitor_fast_check_enabled": bool(values.get("monitor_fast_check_enabled", True)),
                "development_bypass_risk_controls_enabled": bool(values.get("development_bypass_risk_controls_enabled", False)),
                "global_request_limiter_enabled": bool(values.get("global_request_limiter_enabled", True)),
                "cookie_cooldown_enabled": bool(values.get("cookie_cooldown_enabled", True)),
                "risk_backoff_enabled": bool(values.get("risk_backoff_enabled", True)),
                "cookie_health_persistence_enabled": bool(values.get("cookie_health_persistence_enabled", True)),
                "batch_parse_download_pipeline_enabled": bool(values.get("batch_parse_download_pipeline_enabled", False)),
                "segmented_download_enabled": bool(values.get("segmented_download_enabled", False)),
            }
        )
        try:
            monitor_interval = float(values.get("douyin_content_monitor_interval_minutes") or 10)
        except (TypeError, ValueError):
            monitor_interval = 10.0
        user_config["douyin_content_monitor_interval_minutes"] = max(1.0, monitor_interval)
        return user_config

    @staticmethod
    def build_cookies_config(current: dict[str, Any], raw_douyin_cookie: str, raw_tiktok_cookie: str) -> tuple[dict[str, Any], bool, int]:
        cookies_config = dict(current or {})
        douyin_cookie_pool = parse_cookie_pool(raw_douyin_cookie)
        douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else ""
        tiktok_cookie = sanitize_cookie_header(raw_tiktok_cookie)
        cookie_cleaned = bool(raw_douyin_cookie.strip() != "\n".join(douyin_cookie_pool) or raw_tiktok_cookie.strip() != tiktok_cookie)
        cookies_config["douyin_cookie"] = douyin_cookie
        cookies_config["douyin_cookie_pool"] = douyin_cookie_pool
        cookies_config["tiktok_cookie"] = tiktok_cookie
        return cookies_config, cookie_cleaned, len(douyin_cookie_pool)

    async def export_config_package(self) -> Path:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "config_exports")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        include_names = {"user_settings.json", "language.json", "default_settings.json"}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in include_names:
                    zf.write(file, arcname=file.name)
        return path

    async def export_full_backup(self) -> Path:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "backups")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        include_names = {
            "user_settings.json",
            "language.json",
            "default_settings.json",
            "cookies.json",
            "douyin_content_monitor.json",
            "accounts.json",
            "recordings.json",
            "web_auth.json",
        }
        manifest = {"type": "douyin_monitor_full_backup", "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "files": []}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in include_names and file.exists():
                    zf.write(file, arcname=f"config/{file.name}")
                    manifest["files"].append(f"config/{file.name}")
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return path

    async def maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value
