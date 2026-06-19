from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any


class PeriodicMonitorScheduler:
    def __init__(
        self,
        *,
        run_once: Callable[[], Awaitable[Any]],
        interval_seconds: Callable[[], int],
        logger: Any,
    ):
        self.run_once = run_once
        self.interval_seconds = interval_seconds
        self.logger = logger
        self.task: asyncio.Task | None = None

    async def start(self) -> asyncio.Task:
        if self.task is not None and not self.task.done():
            self.logger.info("Douyin content monitor already running for this app instance, skipping")
            return self.task
        self.task = asyncio.create_task(self._loop())
        self.logger.info(f"Initialized Douyin content monitor interval={self.interval_seconds()}s")
        return self.task

    async def stop(self) -> None:
        task = self.task
        self.task = None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def _loop(self) -> None:
        self.logger.info("Starting Douyin content monitor background task")
        try:
            while True:
                try:
                    await self.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self.logger.error(f"Douyin content monitor periodic check failed: {exc}")
                await asyncio.sleep(min(60.0, self.interval_seconds()))
        except asyncio.CancelledError:
            self.logger.info("Douyin content monitor background task stopped")
            raise
