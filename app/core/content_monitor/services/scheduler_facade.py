from __future__ import annotations

from .monitor_common import *


class ContentMonitorSchedulerMixin:
    async def start_monitor(self, account_id: str) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        account.monitor_enabled = True
        account.status = "等待检测"
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "status", "account_id": account_id})
        return True

    async def stop_monitor(self, account_id: str) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        account.monitor_enabled = False
        account.status = "已停止监控"
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "status", "account_id": account_id})
        return True

    @classmethod
    def is_periodic_task_running(cls) -> bool:
        return False

    @classmethod
    def set_periodic_task_running(cls, value: bool = True) -> None:
        return None

    async def setup_periodic_check(self) -> None:
        self._periodic_task = await self._scheduler.start()

    async def _periodic_check_once(self) -> None:
        if self._batch_check_lock.locked():
            logger.info("Douyin content monitor periodic check skipped: batch check already running")
            return
        await self.check_due_enabled()

    async def stop_periodic_check(self) -> None:
        task = self._periodic_task
        self._periodic_task = None
        await self._scheduler.stop()
