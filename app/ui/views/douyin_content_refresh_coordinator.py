from __future__ import annotations

import time
from typing import Any

from ...utils.logger import logger


class DouyinContentRefreshCoordinator:
    """Coordinate content-monitor UI refreshes across pubsub and long-running jobs.

    Content monitoring can emit many update events while batch detection or downloads
    are still running. Refreshing the full page for every event can rebuild long
    lists repeatedly, lose scroll position, and create the grey/blank-region style
    regressions that are hard to debug. This coordinator centralizes three rules:

    * defer pubsub refreshes while a batch job or download queue is active;
    * throttle repeated pubsub refreshes;
    * force one final refresh after the long-running job completes.
    """

    def __init__(self, owner: Any, *, min_interval_seconds: float = 0.8) -> None:
        self.owner = owner
        self.min_interval_seconds = max(0.1, float(min_interval_seconds or 0.8))
        self.pending = False
        self.last_refresh_at = 0.0
        self.last_event: dict[str, Any] = {}
        self.refresh_count = 0
        self.deferred_count = 0

    def is_active_page(self) -> bool:
        return bool(getattr(self.owner, "_is_active_page", lambda: False)())

    def is_busy(self) -> bool:
        return bool(getattr(self.owner, "batch_job_running", False) or getattr(self.owner, "download_in_progress", False))

    def mark_pending(self, event: dict[str, Any] | None = None) -> None:
        self.pending = True
        self.deferred_count += 1
        if isinstance(event, dict):
            self.last_event = dict(event)
        setattr(self.owner, "_pending_monitor_refresh", True)

    async def handle_pubsub(self, event: dict[str, Any] | None = None) -> bool:
        """Handle a pubsub update. Returns True when a refresh was executed."""
        if not self.is_active_page():
            return False
        if self.is_busy():
            self.mark_pending(event)
            return False
        now = time.monotonic()
        if now - self.last_refresh_at < self.min_interval_seconds:
            self.mark_pending(event)
            return False
        return await self.force_refresh(event=event)

    async def force_refresh(self, event: dict[str, Any] | None = None) -> bool:
        """Refresh immediately, preserving the page's scroll restoration contract."""
        if not self.is_active_page():
            return False
        if isinstance(event, dict):
            self.last_event = dict(event)
        try:
            await self.owner.refresh_view()
            self.owner.safe_content_update()
            if getattr(self.owner, "view_mode", "") == "accounts":
                await self.owner.restore_pending_account_scroll_position()
            self.pending = False
            setattr(self.owner, "_pending_monitor_refresh", False)
            now = time.monotonic()
            self.last_refresh_at = now
            setattr(self.owner, "_last_pubsub_refresh_at", now)
            self.refresh_count += 1
            return True
        except Exception as exc:  # pragma: no cover - defensive UI guard
            logger.debug(f"douyin content refresh failed: {exc}")
            return False

    async def flush_after_long_task(self, *, force: bool = True) -> bool:
        """Run the mandatory final refresh after a batch/download task finishes."""
        if not self.is_active_page():
            return False
        if self.is_busy():
            self.mark_pending(self.last_event)
            return False
        if force or self.pending:
            return await self.force_refresh(event={"event": "final_refresh"} | dict(self.last_event or {}))
        return False

    def snapshot(self) -> dict[str, Any]:
        return {
            "pending": self.pending,
            "last_event": dict(self.last_event or {}),
            "refresh_count": self.refresh_count,
            "deferred_count": self.deferred_count,
            "last_refresh_at": self.last_refresh_at,
        }
