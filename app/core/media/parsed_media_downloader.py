from __future__ import annotations

import os
import asyncio
import time
from pathlib import Path
from typing import Any

import httpx

from ..runtime.media_task_queue import report_media_task_progress
from .file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename, safe_filename
from .image_conversion import save_image_as_png
from .image_urls import deduplicate_image_urls
from .resumable_download import download_http_file
from .video_parser_service import ParsedVideoResult


class ParsedMediaDownloader:
    def __init__(self, services: Any):
        self.services = services

    async def download(self, item: ParsedVideoResult) -> dict[str, Any]:
        if item.media_type == "image" or item.image_urls:
            return await self._download_gallery(item)
        return await self._download_video(item)

    async def cache_video_preview(
        self,
        url: str,
        cache_key: str,
        title: str = "",
        priority: str = "foreground",
    ) -> dict[str, Any]:
        if not url:
            return {"success": False, "reason": "未获取到视频预览直链"}
        save_path = self._preview_cache_path(cache_key or url)
        if self._valid_file(save_path):
            return {"success": True, "reason": "使用本地预览缓存", "path": save_path}

        async def run_download() -> str:
            if self._valid_file(save_path):
                return save_path
            await self._download_file(url, save_path)
            return save_path

        path = await self.services.media_task_queue.run(
            "video_preview",
            title or cache_key or "视频预览",
            run_download,
            priority=priority,
            dedupe_key=save_path,
        )
        return {"success": True, "reason": "视频预览缓存完成", "path": path}

    async def _download_video(self, item: ParsedVideoResult) -> dict[str, Any]:
        url = item.no_watermark_url or item.watermark_url
        if not url:
            return {"success": False, "reason": "未获取到可下载视频直链"}
        save_path = self._video_save_path(item)
        if self._valid_file(save_path):
            return {"success": True, "reason": "文件已存在", "path": save_path}

        async def run_download() -> str:
            if self._valid_file(save_path):
                return save_path
            await self._download_file(url, save_path)
            return save_path

        path = await self.services.media_task_queue.run(
            "video_download",
            item.description or item.item_id or "video",
            run_download,
            priority=self._download_priority(item),
            dedupe_key=save_path,
        )
        return {"success": True, "reason": "下载完成", "path": path}

    async def _download_gallery(self, item: ParsedVideoResult) -> dict[str, Any]:
        urls = deduplicate_image_urls(item.image_urls or item.watermark_image_urls)
        if not urls:
            return {"success": False, "reason": "未获取到图集图片直链"}
        save_dir = self._gallery_save_dir(item)
        os.makedirs(save_dir, exist_ok=True)
        if self._gallery_complete(save_dir, len(urls)):
            files = self._gallery_files(save_dir)
            return {"success": True, "reason": "图集文件已存在", "path": save_dir, "files": files}

        async def run_download() -> str:
            for index, url in enumerate(urls, start=1):
                save_path = os.path.join(save_dir, f"{self._safe_item_id(item)}_{index:03d}.png")
                if self._valid_file(save_path):
                    continue
                await self._download_image_as_png(url, save_path)
            return save_dir

        path = await self.services.media_task_queue.run(
            "gallery_download",
            item.description or item.item_id or "gallery",
            run_download,
            priority=self._download_priority(item),
            dedupe_key=save_dir,
        )
        files = self._gallery_files(path)
        return {"success": True, "reason": "图集下载完成", "path": path, "files": files}

    @staticmethod
    def _download_priority(item: ParsedVideoResult) -> str:
        raw_data = getattr(item, "raw_data", {})
        if isinstance(raw_data, dict):
            value = str(raw_data.get("download_priority") or "").strip().lower()
            if value in {"foreground", "background", "normal"}:
                return value
        return "foreground"

    def _base_download_dir(self, item: ParsedVideoResult | None = None) -> str:
        raw_data = getattr(item, "raw_data", {}) if item is not None else {}
        if isinstance(raw_data, dict):
            custom_dir = str(raw_data.get("download_base_dir") or "").strip()
            if custom_dir:
                return custom_dir
        settings = getattr(self.services, "settings_config", None)
        base = ""
        if settings is not None:
            base = str(getattr(settings, "user_config", {}).get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.services.run_path, "downloads", "douyin_content")
        return os.path.join(base, "parsed")

    def _video_save_path(self, item: ParsedVideoResult) -> str:
        return os.path.join(self._base_download_dir(item), f"{self._media_filename(item)}.mp4")

    def _gallery_save_dir(self, item: ParsedVideoResult) -> str:
        return os.path.join(self._base_download_dir(item), self._media_filename(item))

    def _preview_cache_path(self, cache_key: str) -> str:
        base = os.path.join(self.services.run_path, "cache", "video_previews")
        return os.path.join(base, f"{safe_filename(cache_key, fallback='video_preview')}.mp4")

    def _filename_template(self) -> str:
        settings = getattr(self.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        return str(config.get("douyin_content_filename_template") or DEFAULT_FILENAME_TEMPLATE)

    def _media_filename(self, item: ParsedVideoResult) -> str:
        raw_data = getattr(item, "raw_data", {})
        if isinstance(raw_data, dict):
            custom_name = str(raw_data.get("download_filename") or "").strip()
            if custom_name:
                return safe_filename(custom_name, fallback=item.item_id or "parsed")
        return format_media_filename(
            self._filename_template(),
            {
                "platform": item.platform or "douyin",
                "author": getattr(item, "author_nickname", "") or getattr(item, "author_name", "") or getattr(item, "author", "") or "",
                "item_id": item.item_id or "parsed",
                "title": item.description or item.item_id or "parsed",
            },
            fallback=item.item_id or "parsed",
        )

    @staticmethod
    def _safe_item_id(item: ParsedVideoResult) -> str:
        return safe_filename(item.item_id or "parsed", fallback="parsed")

    @staticmethod
    def _valid_file(path: str) -> bool:
        try:
            return os.path.isfile(path) and os.path.getsize(path) > 0
        except OSError:
            return False

    def _gallery_files(self, folder: str) -> list[str]:
        try:
            return [str(path) for path in sorted(Path(folder).glob("*.png")) if self._valid_file(str(path))]
        except OSError:
            return []

    def _gallery_complete(self, folder: str, expected_count: int) -> bool:
        if expected_count <= 0 or not os.path.isdir(folder):
            return False
        return len(self._gallery_files(folder)) >= expected_count

    async def _download_image_as_png(self, url: str, save_path: str) -> None:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        tmp_path = save_path + ".download"
        try:
            await self._download_file(url, tmp_path)
            save_image_as_png(tmp_path, save_path)
        except asyncio.CancelledError:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            raise
        finally:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass

    async def _download_file(self, url: str, save_path: str) -> None:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/",
        }
        recovery = getattr(self.services, "download_recovery_service", None)
        download_id = recovery.start(url=url, save_path=save_path, kind="parsed_media", label=os.path.basename(save_path)) if recovery else ""
        try:
            await download_http_file(
                url,
                save_path,
                headers=headers,
                timeout=self._download_timeout(),
                chunk_size=1024 * 256,
                progress_interval=self._progress_interval(),
                progress_formatter=self._download_progress_text,
                progress_reporter=report_media_task_progress,
                progress_callback=(lambda downloaded, total: recovery.mark_progress(download_id, downloaded, total)) if recovery and download_id else None,
                resume_enabled=self._resume_enabled(),
            )
            if recovery and download_id:
                recovery.mark_completed(download_id)
        except asyncio.CancelledError:
            if recovery and download_id:
                recovery.mark_cancelled(download_id)
            raise
        except Exception as exc:
            if recovery and download_id:
                recovery.mark_failed(download_id, str(exc))
            raise

    def _download_timeout(self) -> httpx.Timeout:
        settings = getattr(self.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        try:
            total = float(config.get("media_download_timeout_seconds", 180) or 180)
        except (TypeError, ValueError):
            total = 180.0
        total = max(30.0, total)
        return httpx.Timeout(total, connect=15.0, read=total, write=30.0, pool=15.0)

    def _progress_interval(self) -> float:
        settings = getattr(self.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        try:
            return max(0.5, min(10.0, float(config.get("media_download_progress_interval_seconds", 1.5) or 1.5)))
        except (TypeError, ValueError):
            return 1.5

    def _resume_enabled(self) -> bool:
        settings = getattr(self.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        value = config.get("download_resume_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @classmethod
    def _download_progress_text(cls, downloaded: int, total: int, started: float) -> str:
        elapsed = max(0.1, time.monotonic() - started)
        speed = downloaded / elapsed
        if total > 0:
            percent = min(100.0, downloaded * 100.0 / total)
            return f"下载中：{percent:.1f}%  {cls._format_bytes(downloaded)}/{cls._format_bytes(total)}  {cls._format_bytes(speed)}/s"
        return f"下载中：{cls._format_bytes(downloaded)}  {cls._format_bytes(speed)}/s"

    @staticmethod
    def _format_bytes(value: float) -> str:
        size = float(max(0.0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
            size /= 1024
        return f"{size:.1f}GB"
