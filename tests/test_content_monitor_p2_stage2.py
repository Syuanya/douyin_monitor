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


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = SQLiteStore(run_path)
        self.video_parser = None
        self.task_center = TaskCenter(sqlite_store=self.sqlite_store)
        self.batch_job_store = SimpleNamespace(pending_jobs=lambda: [])
        self.media_task_queue = SimpleNamespace(snapshot=lambda: {})

    def broadcast_pubsub(self, *_args, **_kwargs) -> None:
        return None

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None

    def snapshot_bridges(self) -> list:
        return []


class ContentMonitorP2Stage2Test(unittest.TestCase):
    def test_task_center_retry_skips_non_retryable_content_failures(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                manager = DouyinContentMonitorManager(services)
                account = DouyinMonitorAccount(
                    account_id="a1",
                    homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                    display_name="账号A",
                    items=[
                        DouyinContentItem(item_id="expired", status="download_failed", failure_retryable=False, failure_category="作品失效"),
                        DouyinContentItem(item_id="network", status="download_failed", failure_retryable=True, failure_category="网络异常"),
                    ],
                )
                manager._accounts = [account]
                services.douyin_content_monitor = manager
                app = SimpleNamespace(services=services)
                called: list[str] = []

                async def fake_download_item(account_id: str, item_id: str, priority: str = "foreground"):
                    called.append(item_id)
                    return {"success": True, "reason": "ok"}

                manager.download_item = fake_download_item  # type: ignore[method-assign]
                result = await TaskCenterFacadeService(app).retry_content_download_items(
                    {"account_id": "a1", "item_ids": ["expired", "network"]}
                )

                self.assertTrue(result["success"])
                self.assertEqual(result["skipped_count"], 1)
                self.assertEqual(called, ["network"])

        asyncio.run(run_case())

    def test_task_center_can_cancel_specific_auto_download(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                manager = DouyinContentMonitorManager(services)
                services.douyin_content_monitor = manager

                async def sleeper():
                    await asyncio.sleep(5)

                task = asyncio.create_task(sleeper())
                manager._auto_download_tasks = {"a1:i1": task}
                manager._auto_download_task_meta = {"a1:i1": {"account_id": "a1", "item_ids": ["i1"], "task_key": "a1:i1"}}
                app = SimpleNamespace(services=services)

                result = await TaskCenterFacadeService(app).cancel_record(
                    {
                        "cancel_action": "content_auto_download",
                        "cancel_payload": {"account_id": "a1", "item_ids": ["i1"], "task_key": "a1:i1"},
                    }
                )

                self.assertTrue(result["success"])
                self.assertEqual(result["cancelled"], 1)
                self.assertEqual(manager._auto_download_tasks, {})
                self.assertEqual(manager._auto_download_task_meta, {})

        asyncio.run(run_case())

    def test_download_summary_counts_failure_categories_and_non_retryable(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(DummyServices(temp_dir))
            manager._accounts = [
                DouyinMonitorAccount(
                    account_id="a1",
                    homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                    items=[
                        DouyinContentItem(item_id="a", status="download_failed", failure_category="作品失效", failure_retryable=False),
                        DouyinContentItem(item_id="b", status="download_failed", failure_category="网络异常", failure_retryable=True),
                        DouyinContentItem(item_id="c", status="download_failed", failure_category="网络异常", failure_retryable=True),
                    ],
                )
            ]

            summary = manager.download_status_summary("a1")

            self.assertEqual(summary["failed"], 3)
            self.assertEqual(summary["retryable_failed"], 2)
            self.assertEqual(summary["non_retryable_failed"], 1)
            self.assertEqual(summary["failure_categories"], {"作品失效": 1, "网络异常": 2})

    def test_retry_failed_downloads_skips_non_retryable_items(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(DummyServices(temp_dir))
                manager._accounts = [
                    DouyinMonitorAccount(
                        account_id="a1",
                        homepage_url="https://www.douyin.com/user/MS4wLjABAAAA_x",
                        items=[
                            DouyinContentItem(item_id="expired", status="download_failed", failure_retryable=False),
                            DouyinContentItem(item_id="retry", status="download_failed", failure_retryable=True),
                        ],
                    )
                ]
                called: list[list[str]] = []

                async def fake_batch(account_id: str, item_ids: list[str], title_prefix: str = ""):
                    called.append(list(item_ids))
                    return {"success": True, "reason": "done", "total": len(item_ids), "success_count": len(item_ids), "failed_count": 0}

                manager.download_items_batch = fake_batch  # type: ignore[method-assign]
                result = await manager.retry_failed_downloads("a1")

                self.assertTrue(result["success"])
                self.assertEqual(result["skipped_count"], 1)
                self.assertEqual(called, [["retry"]])

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
