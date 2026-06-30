from __future__ import annotations

import asyncio
import tempfile
from types import SimpleNamespace
import unittest

from app.core.content_monitor.douyin_content_monitor import DouyinContentItem, DouyinContentMonitorManager, DouyinMonitorAccount
from app.core.runtime.task_center import TaskCenter
from app.core.storage.sqlite_store import SQLiteStore
from app.core.ui_services.task_center_service import TaskCenterFacadeService


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default


class DummyBatchJob:
    def __init__(self, job_id="job-1"):
        self.job_id = job_id
        self.completed_ids = []
        self.status = "running"


class DummyBatchStore:
    def __init__(self):
        self.job = DummyBatchJob()
        self.cancelled = []
        self.finished = []
        self.marked = []

    def start_or_resume(self, *_args, **_kwargs):
        return self.job

    def get(self, job_id):
        return self.job if job_id == self.job.job_id else None

    def mark_item(self, job_id, item_id, status, reason=""):
        self.marked.append((job_id, item_id, status, reason))

    def finish(self, job_id, success=True):
        self.finished.append((job_id, success))
        self.job.status = "completed" if success else "failed"

    def pause(self, job_id):
        self.job.status = "paused"

    def cancel(self, job_id, reason=""):
        self.cancelled.append((job_id, reason))
        self.job.status = "cancelled"

    def pending_jobs(self):
        return []


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = SQLiteStore(run_path)
        self.video_parser = None
        self.task_center = TaskCenter(sqlite_store=self.sqlite_store)
        self.batch_job_store = DummyBatchStore()
        self.media_task_queue = SimpleNamespace(snapshot=lambda: {})
        self.events = []

    def broadcast_pubsub(self, topic, payload):
        self.events.append((topic, payload))

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None

    def snapshot_bridges(self) -> list:
        return []


class ContentMonitorP2CompleteTest(unittest.TestCase):
    def test_task_center_cancel_batch_job_broadcasts_monitor_update(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                app = SimpleNamespace(services=services)
                result = await TaskCenterFacadeService(app).cancel_record(
                    {"cancel_action": "batch_job", "cancel_payload": {"job_id": "job-1"}}
                )

                self.assertTrue(result["success"])
                self.assertEqual(services.batch_job_store.cancelled, [("job-1", "用户在任务中心取消")])
                self.assertEqual(services.events[-1][0], "douyin_monitor_update")
                self.assertEqual(services.events[-1][1]["event"], "task_cancelled")
                self.assertEqual(services.events[-1][1]["job_id"], "job-1")

        asyncio.run(run_case())

    def test_download_batch_task_records_cancel_action_for_batch_job(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                manager = DouyinContentMonitorManager(services)
                manager._accounts = [
                    DouyinMonitorAccount(
                        account_id="a1",
                        homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                        display_name="账号A",
                        items=[DouyinContentItem(item_id="i1", title="作品", status="new")],
                    )
                ]

                async def fake_download_item(account_id: str, item_id: str, priority: str = "foreground"):
                    return {"success": True, "reason": "ok"}

                manager.download_item = fake_download_item  # type: ignore[method-assign]
                result = await manager.download_items_batch("a1", ["i1"])
                record = services.task_center.snapshot(10)[0]

                self.assertTrue(result["success"])
                self.assertEqual(record["cancel_action"], "batch_job")
                self.assertEqual(record["cancel_payload"], {"job_id": "job-1"})
                self.assertTrue(record["retry_payload"]["retryable_only"])
                self.assertEqual(record["retry_payload"]["all_item_ids"], ["i1"])

        asyncio.run(run_case())

    def test_retry_record_broadcasts_monitor_update(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                manager = DouyinContentMonitorManager(services)
                manager._accounts = [
                    DouyinMonitorAccount(
                        account_id="a1",
                        homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                        items=[DouyinContentItem(item_id="i1", status="download_failed", failure_retryable=True)],
                    )
                ]
                services.douyin_content_monitor = manager

                async def fake_download_item(account_id: str, item_id: str, priority: str = "foreground"):
                    return {"success": True, "reason": "ok"}

                manager.download_item = fake_download_item  # type: ignore[method-assign]
                app = SimpleNamespace(services=services)
                result = await TaskCenterFacadeService(app).retry_record(
                    {"retry_action": "content_download_items", "retry_payload": {"account_id": "a1", "item_ids": ["i1"]}}
                )

                self.assertTrue(result["success"])
                self.assertEqual(services.events[-1][0], "douyin_monitor_update")
                self.assertEqual(services.events[-1][1]["event"], "task_retry")
                self.assertEqual(services.events[-1][1]["account_id"], "a1")

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
