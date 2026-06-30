from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_refresh_coordinator import DouyinContentRefreshCoordinator


class Owner:
    def __init__(self) -> None:
        self.batch_job_running = False
        self.download_in_progress = False
        self.view_mode = "accounts"
        self._pending_monitor_refresh = False
        self._last_pubsub_refresh_at = 0.0
        self.refreshes = 0
        self.safe_updates = 0
        self.restores = 0
        self.active = True

    def _is_active_page(self) -> bool:
        return self.active

    async def refresh_view(self) -> None:
        self.refreshes += 1

    def safe_content_update(self) -> bool:
        self.safe_updates += 1
        return True

    async def restore_pending_account_scroll_position(self) -> None:
        self.restores += 1


@pytest.mark.asyncio
async def test_refresh_coordinator_defers_while_busy_and_flushes_final_refresh() -> None:
    owner = Owner()
    coordinator = DouyinContentRefreshCoordinator(owner, min_interval_seconds=0.8)
    owner.batch_job_running = True

    refreshed = await coordinator.handle_pubsub({"event": "checked", "account_id": "a1"})

    assert refreshed is False
    assert coordinator.pending is True
    assert owner._pending_monitor_refresh is True
    assert owner.refreshes == 0

    owner.batch_job_running = False
    flushed = await coordinator.flush_after_long_task(force=True)

    assert flushed is True
    assert coordinator.pending is False
    assert owner._pending_monitor_refresh is False
    assert owner.refreshes == 1
    assert owner.safe_updates == 1
    assert owner.restores == 1


@pytest.mark.asyncio
async def test_refresh_coordinator_throttles_burst_events() -> None:
    owner = Owner()
    coordinator = DouyinContentRefreshCoordinator(owner, min_interval_seconds=60)

    assert await coordinator.handle_pubsub({"event": "first"}) is True
    assert await coordinator.handle_pubsub({"event": "second"}) is False

    assert owner.refreshes == 1
    assert coordinator.pending is True
    assert coordinator.last_event["event"] == "second"


@pytest.mark.asyncio
async def test_refresh_coordinator_ignores_inactive_page() -> None:
    owner = Owner()
    owner.active = False
    coordinator = DouyinContentRefreshCoordinator(owner)

    assert await coordinator.handle_pubsub({"event": "checked"}) is False
    assert await coordinator.flush_after_long_task(force=True) is False
    assert owner.refreshes == 0
