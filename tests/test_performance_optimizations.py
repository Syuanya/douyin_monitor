from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import time
import unittest
from pathlib import Path

MISSING_RUNTIME_DEPS = [name for name in ("httpx", "loguru") if importlib.util.find_spec(name) is None]

if not MISSING_RUNTIME_DEPS:
    from app.core.content_monitor.douyin_content_monitor import DouyinContentMonitorManager
    from app.core.media.video_parser_service import ParseProgress, ParsedVideoResult, VideoParserService


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {}
        self.cookies_config = {}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = None
        self.video_parser = None
        self.task_center = None

    def broadcast_pubsub(self, *_args, **_kwargs) -> None:
        return None

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None


class PerformanceOptimizationTest(unittest.TestCase):
    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_parse_text_stream_yields_results_before_batch_finish(self) -> None:
        async def fake_parser(url: str, minimal: bool = True, cookie: str | None = None):
            await asyncio.sleep(0.02 if url.endswith("1") else 0.05)
            item_id = url.rsplit("/", 1)[-1]
            return {
                "aweme_id": item_id,
                "type": "video",
                "platform": "douyin",
                "video_data": {"nwm_video_url": f"https://cdn.example/{item_id}.mp4"},
            }

        async def run_case():
            parser = VideoParserService(parser=fake_parser, parse_concurrency=2)
            events = []
            async for event in parser.parse_text_stream("https://www.douyin.com/video/1 https://www.douyin.com/video/2"):
                events.append(event)
            return events

        events = asyncio.run(run_case())

        self.assertIsInstance(events[0], ParseProgress)
        self.assertTrue(any(isinstance(event, ParsedVideoResult) for event in events[:-1]))
        self.assertIsInstance(events[-1], ParseProgress)
        self.assertEqual(events[-1].completed, 2)

    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_monitor_batch_uses_bounded_concurrency(self) -> None:
        async def run_case():
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(
                    DummyServices(
                        temp_dir,
                        {
                            "monitor_batch_concurrency": 2,
                            "douyin_content_check_interval_between_users_seconds": 0,
                        },
                    )
                )
                for index in range(4):
                    account = await manager.add_account(f"https://www.douyin.com/user/MS4wLjABAAAA_{index}", f"u{index}")
                    account.monitor_enabled = True
                active = 0
                peak = 0
                lock = asyncio.Lock()

                async def fake_check(account_id: str, notify: bool = True):
                    nonlocal active, peak
                    async with lock:
                        active += 1
                        peak = max(peak, active)
                    await asyncio.sleep(0.03)
                    async with lock:
                        active -= 1
                    return {"success": True, "reason": "ok", "new_items": []}

                manager.check_account = fake_check  # type: ignore[method-assign]
                result = await manager.check_all_enabled()
                return result, peak

        result, peak = asyncio.run(run_case())

        self.assertEqual(result["total"], 4)
        self.assertEqual(result["concurrency"], 2)
        self.assertLessEqual(peak, 2)

    @unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
    def test_parser_cookie_health_cools_failed_cookie(self) -> None:
        parser = VideoParserService(parse_concurrency=1)
        parser.configure_cookie_pool("douyin", ["cookie=a", "cookie=b"])
        first = parser.next_cookie("douyin")
        parser.record_cookie_failure("douyin", first, "HTTP 200 空响应")
        second = parser.next_cookie("douyin")

        self.assertNotEqual(first, second)
        snapshot = parser.cookie_health_snapshot("douyin")
        self.assertGreater(snapshot[first]["failure"], 0)
