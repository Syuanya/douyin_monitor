from __future__ import annotations

import asyncio
import tempfile
import unittest

from app.core.diagnostics.health_check_service import HealthCheckService
from app.core.storage.sqlite_store import SQLiteStore


class DummySettings:
    user_config = {"douyin_parser_backend": "internal", "max_parallel_downloads": 2}
    cookies_config = {}


class DummyQueue:
    def snapshot(self):
        return {"__global__": {"limit": 2}}


class DummyServices:
    def __init__(self, run_path: str):
        self.run_path = run_path
        self.settings_config = DummySettings()
        self.sqlite_store = SQLiteStore(run_path)
        self.media_task_queue = DummyQueue()
        self.video_parser = object()


class HealthCheckServiceTest(unittest.TestCase):
    def test_sqlite_health_check(self) -> None:
        async def run_case():
            with tempfile.TemporaryDirectory() as temp_dir:
                service = HealthCheckService(DummyServices(temp_dir))
                return await service.check_sqlite()

        result = asyncio.run(run_case())

        self.assertEqual(result.status, "正常")
        self.assertEqual(result.name, "SQLite")
