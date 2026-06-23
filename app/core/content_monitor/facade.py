from __future__ import annotations

import asyncio
import os
from typing import Any

from ...utils.logger import logger
from .models import DouyinContentItem, DouyinMonitorAccount
from .services.account_repository import AccountRepository
from .services.content_merge_service import ContentMergeService
from .services.scheduler_service import PeriodicMonitorScheduler
from .services.account_service import ContentMonitorAccountMixin
from .services.base_service import ContentMonitorBaseMixin
from .services.cookie_runtime import ContentMonitorCookieMixin
from .services.download_service import ContentMonitorDownloadMixin
from .services.profile_parser import ContentMonitorProfileParserMixin
from .services.profile_sync_service import ContentMonitorProfileSyncMixin
from .services.scheduler_facade import ContentMonitorSchedulerMixin


class DouyinContentMonitorManager(
    ContentMonitorAccountMixin,
    ContentMonitorProfileSyncMixin,
    ContentMonitorDownloadMixin,
    ContentMonitorProfileParserMixin,
    ContentMonitorCookieMixin,
    ContentMonitorSchedulerMixin,
    ContentMonitorBaseMixin,
):
    """Facade for Douyin content monitoring.

    The public API remains compatible with the original manager, but concrete
    responsibilities now live in focused service mixins under
    ``app.core.content_monitor.services``:

    * account_service: account CRUD and persistence
    * profile_sync_service: monitoring and profile/work synchronization
    * profile_parser: profile HTML/JSON parsing
    * cookie_runtime: cookie-pool selection and cooldown
    * download_service: preview/download orchestration
    * scheduler_facade: start/stop periodic monitoring
    """

    def __init__(self, services):
        self.services = services
        self.settings = services.settings_config
        self.run_path = services.run_path
        self.config_path = os.path.join(self.run_path, "config", "douyin_content_monitor.json")
        self.log_path = os.path.join(self.run_path, "logs", "douyin_monitor.log")
        self._account_repository = AccountRepository(
            self.config_path,
            sqlite_store=getattr(services, "sqlite_store", None),
            mirror_json=bool(self.settings.user_config.get("sqlite_json_mirror_enabled", True)),
        )
        self._accounts: list[DouyinMonitorAccount] = []
        self._lock = asyncio.Lock()
        self._batch_check_lock = asyncio.Lock()
        self._account_scan_locks: dict[str, asyncio.Lock] = {}
        self._persist_task: asyncio.Task | None = None
        self._periodic_task: asyncio.Task | None = None
        self._persist_lock = asyncio.Lock()
        self._last_persist_at = 0.0
        self._persist_debounce_seconds = 1.5
        self._douyin_cookie_cursor = 0
        self._douyin_cookie_cooldowns: dict[str, float] = {}
        self._douyin_cookie_health: dict[str, dict[str, float]] = {}
        self._op_logger = logger.bind(douyin_monitor_event=True)
        self._merge_service = ContentMergeService(
            now_fn=self._now,
            sort_items_newest_first=self.sort_items_newest_first,
            is_gallery_item=self._is_gallery_item,
        )
        self._scheduler = PeriodicMonitorScheduler(
            run_once=self._periodic_check_once,
            interval_seconds=self._interval_seconds,
            logger=logger,
        )
        self._load_accounts()

    @property
    def accounts(self) -> list[DouyinMonitorAccount]:
        return self._accounts


__all__ = ["DouyinContentItem", "DouyinMonitorAccount", "DouyinContentMonitorManager"]
