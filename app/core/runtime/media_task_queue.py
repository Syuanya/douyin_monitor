from __future__ import annotations

import asyncio
import contextvars
import os
import time
import threading
from collections import defaultdict
from typing import Awaitable, Callable, TypeVar

from ...utils.logger import logger
from .task_center import TASK_STATUS_RUNNING, TASK_STATUS_WAITING

T = TypeVar("T")

_CURRENT_QUEUE: contextvars.ContextVar["MediaTaskQueue | None"] = contextvars.ContextVar("douyin_current_media_queue", default=None)
_CURRENT_TASK_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar("douyin_current_media_task_id", default=None)


def report_media_task_progress(detail: str, **updates) -> None:
    queue = _CURRENT_QUEUE.get()
    task_id = _CURRENT_TASK_ID.get()
    if queue is None or not task_id:
        return
    queue._task_progress(task_id, detail=detail, **updates)


class MediaTaskQueue:
    """Bound Douyin download work with small, safe queues."""

    def __init__(self, settings_config):
        self.settings = settings_config
        self.task_center = None
        self._paused = False
        self._cancel_generation = 0
        self._locks: dict[tuple[int, str], asyncio.Semaphore] = {}
        self._global_locks: dict[int, asyncio.Semaphore] = {}
        self._inflight: dict[tuple[int, str, str], asyncio.Task] = {}
        self._stats = defaultdict(lambda: {"running": 0, "waiting": 0, "completed": 0, "failed": 0})
        self._priority = defaultdict(lambda: {"foreground_waiting": 0, "foreground_running": 0})
        self._labels = defaultdict(lambda: {"waiting": [], "running": []})
        self._progress_last: dict[str, dict[str, object]] = {}
        self._stats_lock = threading.Lock()
        self._op_logger = logger.bind(douyin_monitor_event=True)

    def _get_config(self, key: str, default=None):
        try:
            return self.settings.user_config.get(key, default)
        except Exception:
            return default

    def _get_bool_config(self, key: str, default: bool = True) -> bool:
        value = self._get_config(key, default)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _get_int_config(self, key: str, default: int) -> int:
        value = self._get_config(key, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _cpu_count() -> int:
        try:
            return max(1, int(os.cpu_count() or 1))
        except Exception:
            return 1

    def _auto_limit(self, kind: str) -> int:
        cpu = self._cpu_count()
        return max(1, min(4, cpu // 2 or 1))

    def _limit(self, kind: str) -> int:
        explicit = self._get_int_config("max_parallel_downloads", 0)
        if explicit > 0:
            return max(1, explicit)
        if self._get_bool_config("media_queue_auto_tune", True):
            return self._auto_limit(kind)
        return 2

    def _semaphore(self, kind: str) -> asyncio.Semaphore:
        # asyncio.Semaphore is loop-affine.  Keep one semaphore per event loop
        # so desktop/web/background loops do not share unsafe primitives.
        limit = self._limit(kind)
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = 0
        key = (loop_id, kind)
        sem = self._locks.get(key)
        if sem is None or getattr(sem, "_douyin_monitor_limit", None) != limit:
            sem = asyncio.Semaphore(limit)
            setattr(sem, "_douyin_monitor_limit", limit)
            self._locks[key] = sem
        return sem

    def _global_semaphore(self) -> asyncio.Semaphore:
        limit = self._limit("__global__")
        try:
            loop_id = id(asyncio.get_running_loop())
        except RuntimeError:
            loop_id = 0
        sem = self._global_locks.get(loop_id)
        if sem is None or getattr(sem, "_douyin_monitor_limit", None) != limit:
            sem = asyncio.Semaphore(limit)
            setattr(sem, "_douyin_monitor_limit", limit)
            self._global_locks[loop_id] = sem
        return sem

    async def run(
        self,
        kind: str,
        label: str,
        coro_factory: Callable[[], Awaitable[T]],
        priority: str = "normal",
        dedupe_key: str = "",
    ) -> T:
        try:
            loop = asyncio.get_running_loop()
            loop_id = id(loop)
        except RuntimeError:
            loop = None
            loop_id = 0
        task_key = (loop_id, str(kind or ""), str(dedupe_key or label or ""))
        if loop is not None and task_key[2]:
            existing = self._inflight.get(task_key)
            if existing is not None and not existing.done():
                if self._get_bool_config("media_task_queue_log_enabled", True):
                    self._op_logger.info(f"Media queue joined existing task: kind={kind}, label={label}")
                return await existing

            task = loop.create_task(self._run_once(kind, label, coro_factory, priority=priority))
            self._inflight[task_key] = task
            try:
                return await task
            finally:
                if self._inflight.get(task_key) is task:
                    self._inflight.pop(task_key, None)

        return await self._run_once(kind, label, coro_factory, priority=priority)

    async def _run_once(self, kind: str, label: str, coro_factory: Callable[[], Awaitable[T]], priority: str = "normal") -> T:
        sem = self._semaphore(kind)
        limit = int(getattr(sem, "_douyin_monitor_limit", 1) or 1)
        global_sem = self._global_semaphore()
        global_limit = int(getattr(global_sem, "_douyin_monitor_limit", 1) or 1)
        log_enabled = self._get_bool_config("media_task_queue_log_enabled", True)
        cancel_generation = self._cancel_generation
        retry_count = self._retry_count()
        started = time.time()
        task_id = self._task_start(kind, label, f"等待下载线程，全局并发上限 {global_limit}，分类并发上限 {limit}")
        with self._stats_lock:
            self._stats[kind]["waiting"] += 1
            self._add_label_locked(kind, "waiting", label)
            if priority == "foreground":
                self._priority["__global__"]["foreground_waiting"] += 1
        waiting_registered = True
        running_registered = False
        if log_enabled:
            self._op_logger.info(f"Media queue waiting: kind={kind}, limit={limit}, label={label}")
        try:
            self._raise_if_cancelled(cancel_generation)
            await self._wait_if_paused(task_id, cancel_generation)
            await self._wait_for_foreground(priority, task_id, cancel_generation)
            async with global_sem:
                self._raise_if_cancelled(cancel_generation)
                await self._wait_if_paused(task_id, cancel_generation)
                await self._wait_for_foreground(priority, task_id, cancel_generation)
                async with sem:
                    self._raise_if_cancelled(cancel_generation)
                    await self._wait_if_paused(task_id, cancel_generation)
                    await self._wait_for_foreground(priority, task_id, cancel_generation)
                    wait_seconds = time.time() - started
                    with self._stats_lock:
                        if waiting_registered:
                            self._stats[kind]["waiting"] = max(0, self._stats[kind]["waiting"] - 1)
                            self._remove_label_locked(kind, "waiting", label)
                            waiting_registered = False
                            if priority == "foreground":
                                self._priority["__global__"]["foreground_waiting"] = max(0, self._priority["__global__"]["foreground_waiting"] - 1)
                        self._stats[kind]["running"] += 1
                        self._add_label_locked(kind, "running", label)
                        if priority == "foreground":
                            self._priority["__global__"]["foreground_running"] += 1
                        running_registered = True
                    self._task_progress(task_id, status=TASK_STATUS_RUNNING, detail=f"已开始下载，全局并发上限 {global_limit}，分类并发上限 {limit}")
                    if log_enabled:
                        self._op_logger.info(
                            f"Media queue started: kind={kind}, global_limit={global_limit}, limit={limit}, wait={wait_seconds:.2f}s, label={label}"
                        )
                    try:
                        result = await self._run_with_retries(coro_factory, retry_count, task_id, cancel_generation)
                        with self._stats_lock:
                            self._stats[kind]["completed"] += 1
                        self._task_finish(task_id, True, "下载完成")
                        if log_enabled:
                            elapsed = time.time() - started
                            self._op_logger.info(f"Media queue completed: kind={kind}, elapsed={elapsed:.2f}s, label={label}")
                        return result
                    except asyncio.CancelledError as exc:
                        with self._stats_lock:
                            self._stats[kind]["failed"] += 1
                        self._task_cancel(task_id, "下载已取消")
                        self._op_logger.info(f"Media queue cancelled: kind={kind}, label={label}")
                        raise exc
                    except Exception as exc:
                        with self._stats_lock:
                            self._stats[kind]["failed"] += 1
                        self._task_finish(task_id, False, str(exc) or exc.__class__.__name__)
                        self._op_logger.error(f"Media queue failed: kind={kind}, label={label}, error={exc}")
                        raise
                    finally:
                        with self._stats_lock:
                            if running_registered:
                                self._stats[kind]["running"] = max(0, self._stats[kind]["running"] - 1)
                                self._remove_label_locked(kind, "running", label)
                                if priority == "foreground":
                                    self._priority["__global__"]["foreground_running"] = max(0, self._priority["__global__"]["foreground_running"] - 1)
                                running_registered = False
        finally:
            if waiting_registered:
                with self._stats_lock:
                    self._stats[kind]["waiting"] = max(0, self._stats[kind]["waiting"] - 1)
                    self._remove_label_locked(kind, "waiting", label)
                    if priority == "foreground":
                        self._priority["__global__"]["foreground_waiting"] = max(0, self._priority["__global__"]["foreground_waiting"] - 1)

    def snapshot(self) -> dict:
        """Return a cheap diagnostic snapshot without awaiting locks."""
        kinds = sorted({kind for _loop_id, kind in self._locks.keys()} | set(self._stats.keys()))
        with self._stats_lock:
            snapshot = {
                kind: {
                    "limit": self._limit(kind),
                    **dict(self._stats.get(kind, {})),
                    "waiting_labels": list(self._labels[kind]["waiting"][:5]),
                    "running_labels": list(self._labels[kind]["running"][:5]),
                }
                for kind in kinds
            }
            active_labels = []
            waiting_labels = []
            for kind in kinds:
                active_labels.extend(str(label) for label in self._labels[kind]["running"][:5])
                waiting_labels.extend(str(label) for label in self._labels[kind]["waiting"][:5])
        snapshot["__global__"] = {
            "limit": self._limit("__global__"),
            "paused": self.is_paused(),
            "inflight": len([task for task in self._inflight.values() if not task.done()]),
            "running_labels": active_labels[:8],
            "waiting_labels": waiting_labels[:8],
            **dict(self._priority.get("__global__", {})),
        }
        return snapshot

    @staticmethod
    def _clean_label(label: str) -> str:
        text = str(label or "").strip()
        return text[:80] if text else "下载任务"

    def _add_label_locked(self, kind: str, bucket: str, label: str) -> None:
        labels = self._labels[kind][bucket]
        text = self._clean_label(label)
        labels.append(text)
        if len(labels) > 20:
            del labels[:-20]

    def _remove_label_locked(self, kind: str, bucket: str, label: str) -> None:
        labels = self._labels[kind][bucket]
        text = self._clean_label(label)
        try:
            labels.remove(text)
        except ValueError:
            pass

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    def is_paused(self) -> bool:
        return bool(self._paused)

    def cancel_all(self) -> None:
        self._cancel_generation += 1
        for task in list(self._inflight.values()):
            if not task.done():
                task.cancel()

    async def _wait_if_paused(self, task_id: str | None, cancel_generation: int | None = None) -> None:
        if not self._paused:
            return
        self._task_progress(task_id, status=TASK_STATUS_WAITING, detail="下载队列已暂停，点击任务中心的继续下载后执行")
        while self._paused:
            self._raise_if_cancelled(cancel_generation)
            await asyncio.sleep(0.5)

    def _raise_if_cancelled(self, cancel_generation: int | None) -> None:
        if cancel_generation is not None and cancel_generation != self._cancel_generation:
            raise asyncio.CancelledError("下载已取消")

    async def _run_with_retries(
        self,
        coro_factory: Callable[[], Awaitable[T]],
        retry_count: int,
        task_id: str | None,
        cancel_generation: int | None,
    ) -> T:
        last_exc: Exception | None = None
        for attempt in range(retry_count + 1):
            self._raise_if_cancelled(cancel_generation)
            queue_token = _CURRENT_QUEUE.set(self)
            task_token = _CURRENT_TASK_ID.set(task_id)
            try:
                return await coro_factory()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_exc = exc
                if attempt >= retry_count:
                    break
                detail = f"下载失败，准备第 {attempt + 1}/{retry_count} 次重试：{exc}"
                self._task_progress(task_id, status=TASK_STATUS_RUNNING, detail=detail)
                await asyncio.sleep(min(3.0, 0.6 * (attempt + 1)))
            finally:
                _CURRENT_TASK_ID.reset(task_token)
                _CURRENT_QUEUE.reset(queue_token)
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("下载失败")

    def _retry_count(self) -> int:
        value = self._get_int_config("media_download_retry_count", 1)
        return max(0, min(5, value))

    def _progress_interval(self) -> float:
        value = self._get_config("media_task_progress_interval_seconds", 1.5)
        try:
            return max(0.3, min(10.0, float(value)))
        except (TypeError, ValueError):
            return 1.5

    async def _wait_for_foreground(self, priority: str, task_id: str | None, cancel_generation: int | None = None) -> None:
        if priority != "background":
            return
        while True:
            self._raise_if_cancelled(cancel_generation)
            with self._stats_lock:
                waiting = int(self._priority["__global__"].get("foreground_waiting", 0) or 0)
                running = int(self._priority["__global__"].get("foreground_running", 0) or 0)
            if waiting <= 0 and running <= 0:
                return
            self._task_progress(task_id, status=TASK_STATUS_WAITING, detail="后台自动下载等待前台手动任务完成")
            await asyncio.sleep(0.5)

    def _task_start(self, kind: str, label: str, detail: str) -> str | None:
        center = getattr(self, "task_center", None)
        if center is None:
            return None
        try:
            return center.start(str(label or kind or "下载任务"), self._task_category(kind), detail=detail, total=1)
        except Exception as exc:
            logger.debug(f"Media queue task center start failed: {exc}")
            return None

    def _task_progress(self, task_id: str | None, **updates) -> None:
        if not task_id:
            return
        if not self._should_emit_task_progress(task_id, updates):
            return
        center = getattr(self, "task_center", None)
        if center is None:
            return
        try:
            center.progress(task_id, **updates)
        except Exception as exc:
            logger.debug(f"Media queue task center progress failed: {exc}")

    def _should_emit_task_progress(self, task_id: str, updates: dict) -> bool:
        force_keys = {"total", "completed", "success_count", "failed_count", "retry_payload"}
        if force_keys.intersection(updates):
            return True
        now = time.monotonic()
        interval = self._progress_interval()
        status = str(updates.get("status") or "")
        detail = str(updates.get("detail") or "")
        with self._stats_lock:
            previous = self._progress_last.get(task_id)
            if previous is None:
                self._progress_last[task_id] = {"time": now, "status": status, "detail": detail}
                return True
            previous_status = str(previous.get("status") or "")
            if status and status != previous_status:
                self._progress_last[task_id] = {"time": now, "status": status, "detail": detail}
                return True
            if now - float(previous.get("time") or 0.0) >= interval:
                self._progress_last[task_id] = {"time": now, "status": status or previous_status, "detail": detail}
                return True
        return False

    def _task_finish(self, task_id: str | None, success: bool, detail: str) -> None:
        if not task_id:
            return
        center = getattr(self, "task_center", None)
        if center is None:
            return
        try:
            center.progress(task_id, completed=1, success_count=1 if success else 0, failed_count=0 if success else 1)
            center.finish(task_id, success=success, detail=detail)
            with self._stats_lock:
                self._progress_last.pop(task_id, None)
        except Exception as exc:
            logger.debug(f"Media queue task center finish failed: {exc}")

    def _task_cancel(self, task_id: str | None, detail: str) -> None:
        if not task_id:
            return
        center = getattr(self, "task_center", None)
        if center is None:
            return
        try:
            if hasattr(center, "cancel"):
                center.cancel(task_id, detail)
            else:
                center.finish(task_id, success=False, detail=detail)
            with self._stats_lock:
                self._progress_last.pop(task_id, None)
        except Exception as exc:
            logger.debug(f"Media queue task center cancel failed: {exc}")

    @staticmethod
    def _task_category(kind: str) -> str:
        mapping = {
            "video_download": "视频下载",
            "gallery_download": "图片下载",
            "content_download": "内容监控下载",
            "douyin_download": "内容监控下载",
        }
        return mapping.get(str(kind or ""), "下载任务")
