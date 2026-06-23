from __future__ import annotations

import os
import threading
import weakref
from typing import Any

from ..config.config_manager import ConfigManager
from ..config.language_manager import LanguageManager
from ..config.settings_config import SettingsConfig
from ..content_monitor.facade import DouyinContentMonitorManager
from ..diagnostics.health_check_service import HealthCheckService
from ..media.http_client_pool import DownloadHttpClientPool
from ..network.cookie_health_store import CookieHealthStore
from ..network.rate_limiter import DouyinRequestLimiter
from ..update import AutoUpdateService
from ..media.parsed_media_downloader import ParsedMediaDownloader
from ..media.video_parser_service import ParsedVideoResult, VideoParserService
from ..runtime.download_recovery_service import DownloadRecoveryService
from ..runtime.batch_job_store import BatchJobStore
from ..runtime.media_task_queue import MediaTaskQueue
from ..runtime.task_center import TaskCenter
from ..storage.sqlite_store import SQLiteStore
from ...utils.logger import logger


class DouyinMonitorServices:
    """Application service container independent of the Flet shell."""

    def __init__(self, run_path: str):
        self.run_path = run_path
        self.config_manager = ConfigManager(run_path)
        self.sqlite_store = SQLiteStore(run_path)
        self.sqlite_store.ensure_schema()
        self.settings_config = SettingsConfig(self)
        self.language_manager = LanguageManager.create_headless(self)
        self.task_center = TaskCenter(
            storage_path=os.path.join(run_path, "config", "task_records.json"),
            sqlite_store=self.sqlite_store,
        )
        self.health_check_service = HealthCheckService(self)
        self.download_recovery_service = DownloadRecoveryService(self.sqlite_store)
        self.download_recovery_service.initialize_recovery_state()
        self.download_http_client_pool = DownloadHttpClientPool()
        self.cookie_health_store = CookieHealthStore(
            run_path,
            enabled=bool(self.settings_config.get_config_value("cookie_health_persistence_enabled", True)),
        )
        self.douyin_request_limiter = DouyinRequestLimiter(self.settings_config)
        self.batch_job_store = BatchJobStore(run_path)
        self.auto_update_service = AutoUpdateService(self)
        self.media_task_queue = MediaTaskQueue(self.settings_config)
        self.media_task_queue.batch_state_path = os.path.join(run_path, "config", "batch_jobs.json")
        self.media_task_queue.task_center = self.task_center
        parse_concurrency = self.settings_config.get_config_value("video_parse_concurrency", 4)
        parse_batch_size = self.settings_config.get_config_value("batch_parse_size", 20)
        batch_download_concurrency = self.settings_config.get_config_value("batch_download_concurrency", 3)
        self.video_parser = VideoParserService(run_path, parse_concurrency=parse_concurrency)
        self.video_parser.settings_config = self.settings_config
        self.video_parser.cookie_health_store = self.cookie_health_store
        self.video_parser.request_limiter = self.douyin_request_limiter
        self.video_parser.parse_batch_size = max(1, int(parse_batch_size or 20))
        self.video_parser.batch_download_concurrency = max(1, int(batch_download_concurrency or 3))
        self._sync_saved_cookies_to_parser()
        self.parsed_media_downloader = ParsedMediaDownloader(self)
        self.douyin_content_monitor = DouyinContentMonitorManager(self)
        self.recording_manager = None
        self.recording_enabled = False
        self.process_manager = None
        self.subprocess_start_up_info = None
        self.tray_manager = None
        self._ui_bridges: weakref.WeakSet[Any] = weakref.WeakSet()
        self._bridges_lock = threading.Lock()

    def _sync_saved_cookies_to_parser(self) -> None:
        try:
            from ..media.cookie_utils import parse_cookie_pool, sanitize_cookie_header

            cookies_config = getattr(self.settings_config, "cookies_config", {}) or {}
            douyin_pool = parse_cookie_pool(cookies_config.get("douyin_cookie_pool") or [])
            for cookie in parse_cookie_pool(cookies_config.get("douyin_cookie") or ""):
                if cookie not in douyin_pool:
                    douyin_pool.append(cookie)
            if hasattr(self.video_parser, "configure_cookie_pool"):
                self.video_parser.configure_cookie_pool("douyin", douyin_pool)
                self.video_parser.configure_cookie_pool("tiktok", [sanitize_cookie_header(cookies_config.get("tiktok_cookie") or "")])
        except Exception as exc:
            logger.debug(f"sync saved cookies to parser failed: {exc}")

    def register_ui_bridge(self, bridge: Any) -> None:
        with self._bridges_lock:
            self._ui_bridges.add(bridge)

    def unregister_ui_bridge(self, bridge: Any) -> None:
        with self._bridges_lock:
            self._ui_bridges.discard(bridge)

    def snapshot_bridges(self) -> list[Any]:
        with self._bridges_lock:
            return list(self._ui_bridges)

    def broadcast_pubsub(self, topic: str, payload: Any) -> None:
        for bridge in self.snapshot_bridges():
            try:
                bridge.schedule_pubsub(topic, payload)
            except Exception as exc:
                logger.debug(f"standalone douyin broadcast_pubsub failed: {exc}")

    def broadcast_snack(self, text: str, **kw: Any) -> None:
        for bridge in self.snapshot_bridges():
            try:
                bridge.schedule_snack(text, **kw)
            except Exception as exc:
                logger.debug(f"standalone douyin broadcast_snack failed: {exc}")

    def broadcast_card_update(self, _recording: Any) -> None:
        return

    def broadcast_card_remove(self, _recordings: Any) -> None:
        return

    @staticmethod
    def video_parser_result_from_api_data(source_url: str, data: dict[str, Any]) -> ParsedVideoResult:
        return ParsedVideoResult.from_api_data(source_url, data)
