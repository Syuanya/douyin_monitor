from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable


@dataclass(slots=True)
class WebJob:
    job_id: str
    title: str
    status: str = "running"  # running | completed | failed | cancelled
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    result: Any = None
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "title": self.title,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "result": self.result,
            "error": self.error,
        }


class WebJobRegistry:
    """Small in-memory async job registry for remote web actions."""

    def __init__(self, max_jobs: int = 200) -> None:
        self.max_jobs = max(20, int(max_jobs or 200))
        self._jobs: dict[str, WebJob] = {}
        self._tasks: dict[str, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start(self, title: str, coro_factory: Callable[[], Awaitable[Any]]) -> WebJob:
        job = WebJob(job_id=uuid.uuid4().hex, title=str(title or "后台任务"))
        async with self._lock:
            self._jobs[job.job_id] = job
            self._trim_locked()

        async def runner() -> None:
            try:
                result = await coro_factory()
                async with self._lock:
                    current = self._jobs.get(job.job_id)
                    if current is not None and current.status != "cancelled":
                        current.status = "completed"
                        current.result = result
                        current.updated_at = time.time()
            except asyncio.CancelledError:
                async with self._lock:
                    current = self._jobs.get(job.job_id)
                    if current is not None:
                        current.status = "cancelled"
                        current.error = "任务已取消"
                        current.updated_at = time.time()
                raise
            except Exception as exc:
                async with self._lock:
                    current = self._jobs.get(job.job_id)
                    if current is not None:
                        current.status = "failed"
                        current.error = str(exc)
                        current.updated_at = time.time()

        self._tasks[job.job_id] = asyncio.create_task(runner())
        return job

    async def cancel(self, job_id: str) -> bool:
        task = self._tasks.get(str(job_id or ""))
        if task is None or task.done():
            return False
        task.cancel()
        return True

    async def detail(self, job_id: str) -> dict[str, Any] | None:
        async with self._lock:
            job = self._jobs.get(str(job_id or ""))
            return job.to_dict() if job else None

    async def snapshot(self, limit: int = 80) -> list[dict[str, Any]]:
        async with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)[: max(1, int(limit or 80))]
            return [job.to_dict() for job in jobs]

    def _trim_locked(self) -> None:
        if len(self._jobs) <= self.max_jobs:
            return
        ordered = sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
        keep = {job.job_id for job in ordered[: self.max_jobs]}
        for job_id in list(self._jobs):
            if job_id not in keep:
                self._jobs.pop(job_id, None)
                self._tasks.pop(job_id, None)
