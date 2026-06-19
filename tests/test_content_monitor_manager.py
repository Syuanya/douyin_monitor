from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import unittest

MISSING_RUNTIME_DEPS = [
    name
    for name in ("httpx", "loguru")
    if importlib.util.find_spec(name) is None
]

if not MISSING_RUNTIME_DEPS:
    from app.core.content_monitor.douyin_content_monitor import DouyinContentItem, DouyinContentMonitorManager
    from app.core.storage.sqlite_store import SQLiteStore


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = None
        self.video_parser = None

    def broadcast_pubsub(self, *_args, **_kwargs) -> None:
        return None

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None

    def snapshot_bridges(self) -> list:
        return []


class ContentMonitorManagerTest(unittest.TestCase):
    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_parser_backend_defaults_to_internal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(DummyServices(temp_dir))

            self.assertEqual(manager._parser_backend(), "internal")

    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_parser_backend_uses_legacy_external_url(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(
                DummyServices(temp_dir, {"douyin_external_api_base_url": "http://127.0.0.1:8000"})
            )

            self.assertEqual(manager._parser_backend(), "external")

    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_periodic_task_can_be_stopped(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(
                    DummyServices(
                        temp_dir,
                        {
                            "douyin_content_monitor_interval_minutes": 10,
                            "douyin_content_check_interval_between_users_seconds": 0,
                        },
                    )
                )

                await manager.setup_periodic_check()
                self.assertIsNotNone(manager._periodic_task)
                await asyncio.sleep(0)
                await manager.stop_periodic_check()
                self.assertIsNone(manager._periodic_task)

        asyncio.run(run_case())

    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_sync_account_works_persists_parser_items_to_sqlite(self) -> None:
        class FakeVideoParser:
            async def fetch_all_douyin_user_posts(self, sec_user_id: str, max_pages: int = 20, count: int = 20):
                return [
                    DouyinContentItem(
                        item_id="100000001",
                        title=f"work-{sec_user_id}",
                        share_url="https://www.douyin.com/video/100000001",
                    )
                ]

        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                services = DummyServices(temp_dir)
                services.sqlite_store = SQLiteStore(temp_dir)
                services.video_parser = FakeVideoParser()
                manager = DouyinContentMonitorManager(services)
                account = await manager.add_account("https://www.douyin.com/user/MS4wLjABAAAA_test", "demo")

                result = await manager.sync_account_works(account.account_id)

                self.assertTrue(result["success"])
                self.assertEqual(result["total"], 1)
                stored = services.sqlite_store.load_monitor_accounts()
                self.assertEqual(stored[0]["items"][0]["item_id"], "100000001")

        asyncio.run(run_case())
