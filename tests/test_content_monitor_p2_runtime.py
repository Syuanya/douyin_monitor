from __future__ import annotations

import asyncio
import tempfile
from types import SimpleNamespace
import unittest

from app.core.content_monitor.douyin_content_monitor import DouyinContentItem, DouyinContentMonitorManager, DouyinMonitorAccount
from app.core.storage.sqlite_store import SQLiteStore


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default


class DummyTaskCenter:
    def __init__(self) -> None:
        self._active = 0

    def active_count(self) -> int:
        return self._active


class DummyBatchStore:
    def pending_jobs(self):
        return [{"job_id": "b1"}]


class DummyMediaQueue:
    def snapshot(self):
        return {"douyin_download": {"running": 1, "waiting": 0}}


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = SQLiteStore(run_path)
        self.video_parser = None
        self.task_center = DummyTaskCenter()
        self.batch_job_store = DummyBatchStore()
        self.media_task_queue = DummyMediaQueue()

    def broadcast_pubsub(self, *_args, **_kwargs) -> None:
        return None

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None

    def snapshot_bridges(self) -> list:
        return []


class ContentMonitorP2RuntimeTest(unittest.TestCase):
    def test_download_failure_records_category_next_step_and_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(DummyServices(temp_dir))
            item = DouyinContentItem(item_id="i1", status="new")
            account = DouyinMonitorAccount(account_id="a1", homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x", items=[item])
            manager._accounts = [account]

            manager._mark_download_failure(item, "HTTP 404 不存在")
            summary = manager.download_status_summary("a1")

            self.assertEqual(item.status, "download_failed")
            self.assertEqual(item.failure_category, "作品失效")
            self.assertFalse(item.failure_retryable)
            self.assertIn("打开原链接", item.failure_next_step)
            self.assertEqual(summary["latest_failure_category"], "作品失效")
            self.assertEqual(summary["retryable_failed"], 0)

            restored = DouyinContentItem.from_dict(item.to_dict())
            self.assertEqual(restored.failure_category, "作品失效")
            self.assertFalse(restored.failure_retryable)

    def test_runtime_summary_counts_tasks_items_and_persist_status(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(DummyServices(temp_dir))
            manager._accounts = [
                DouyinMonitorAccount(
                    account_id="a1",
                    homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                    monitor_enabled=True,
                    error_count=1,
                    items=[
                        DouyinContentItem(item_id="new", status="new"),
                        DouyinContentItem(item_id="failed", status="download_failed"),
                    ],
                )
            ]

            summary = manager.content_monitor_runtime_summary()

            self.assertEqual(summary["accounts_total"], 1)
            self.assertEqual(summary["accounts_enabled"], 1)
            self.assertEqual(summary["accounts_with_errors"], 1)
            self.assertEqual(summary["pending_new_items"], 2)
            self.assertEqual(summary["download_failed_items"], 1)
            self.assertEqual(summary["pending_batch_jobs"], 1)
            self.assertIn("persist", summary)
            self.assertIn("media_queue", summary)

    def test_cancel_auto_downloads_cleans_registry(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(DummyServices(temp_dir))

                async def sleeper():
                    await asyncio.sleep(5)

                task = asyncio.create_task(sleeper())
                manager._auto_download_tasks = {"a1:i1": task}

                result = await manager.cancel_auto_downloads("a1")

                self.assertEqual(result["cancelled"], 1)
                self.assertEqual(manager._auto_download_tasks, {})

        asyncio.run(run_case())

    def test_flush_persist_cancels_pending_debounce_task_safely(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(DummyServices(temp_dir))
                manager._persist_debounce_seconds = 60
                manager._last_persist_at = asyncio.get_running_loop().time()

                await manager.persist(force=False)
                self.assertTrue(manager.persist_status()["pending"])
                await manager.flush_persist()
                self.assertFalse(manager.persist_status()["pending"])

        asyncio.run(run_case())
