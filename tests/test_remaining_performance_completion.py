from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import time
from pathlib import Path
import unittest

MISSING_RUNTIME_DEPS = [name for name in ("httpx", "loguru") if importlib.util.find_spec(name) is None]

if not MISSING_RUNTIME_DEPS:
    from app.core.content_monitor.douyin_content_monitor import DouyinContentItem, DouyinContentMonitorManager
    from app.core.media.video_parser_service import ParseDownloadEvent, ParsedVideoResult, VideoParserService
    from app.core.network.cookie_health_store import CookieHealthStore
    from app.core.runtime.batch_job_store import BatchJobStore


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {}
        self.cookies_config = {}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default

    def get_config_value(self, key: str, default=None):
        return self.user_config.get(key, default)


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = None
        self.video_parser = None
        self.task_center = None
        self.cookie_health_store = None
        self.douyin_request_limiter = None
        self.batch_job_store = None

    def broadcast_pubsub(self, *_args, **_kwargs) -> None:
        return None

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None


@unittest.skipIf(bool(MISSING_RUNTIME_DEPS), f"runtime dependencies missing: {MISSING_RUNTIME_DEPS}")
class RemainingPerformanceCompletionTest(unittest.TestCase):
    def test_url_extractor_deduplicates_share_variants_by_work_id(self) -> None:
        parser = VideoParserService(parse_concurrency=1)
        urls = parser.extract_urls(
            "https://www.douyin.com/video/1234567890123456789?previous_page=1 "
            "https://www.douyin.com/video/1234567890123456789 "
            "https://v.douyin.com/abcde/ https://v.douyin.com/abcde"
        )
        self.assertEqual(urls.count("https://www.douyin.com/video/1234567890123456789?previous_page=1"), 1)
        self.assertEqual(len(urls), 2)

    def test_cookie_health_store_persists_cooldown_without_raw_cookie(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            raw_cookie = "sessionid=secret-value; uid=1"
            store = CookieHealthStore(temp_dir, enabled=True)
            store.register_pool("douyin", [raw_cookie])
            store.record_failure("douyin", raw_cookie, reason="HTTP 200 空响应", cooldown_seconds=60)
            store.save()

            restored = CookieHealthStore(temp_dir, enabled=True)
            self.assertGreater(restored.cooldown_until("douyin", raw_cookie), time.time())
            payload = Path(restored.path).read_text(encoding="utf-8")
            self.assertNotIn("secret-value", payload)
            self.assertIn("empty", payload)

    def test_parse_download_pipeline_yields_download_events(self) -> None:
        async def fake_parser(url: str, minimal: bool = True, cookie: str | None = None):
            await asyncio.sleep(0.01)
            item_id = url.rsplit("/", 1)[-1]
            return {
                "aweme_id": item_id,
                "type": "video",
                "platform": "douyin",
                "video_data": {"nwm_video_url": f"https://cdn.example/{item_id}.mp4"},
            }

        class Downloader:
            async def download(self, item: ParsedVideoResult):
                await asyncio.sleep(0.01)
                return {"success": True, "path": f"/tmp/{item.item_id}.mp4", "reason": "ok"}

        async def run_case():
            parser = VideoParserService(parser=fake_parser, parse_concurrency=2)
            events = []
            async for event in parser.parse_text_download_stream(
                "https://www.douyin.com/video/100 https://www.douyin.com/video/200", Downloader(), download_concurrency=2
            ):
                events.append(event)
            return events

        events = asyncio.run(run_case())
        queued = [event for event in events if isinstance(event, ParseDownloadEvent) and event.status == "queued"]
        completed = [event for event in events if isinstance(event, ParseDownloadEvent) and event.status == "completed"]
        self.assertEqual(len(queued), 2)
        self.assertEqual(len(completed), 2)
        self.assertTrue(all(event.success for event in completed))

    def test_monitor_fast_check_skips_parser_when_count_unchanged(self) -> None:
        async def run_case():
            with tempfile.TemporaryDirectory() as temp_dir:
                manager = DouyinContentMonitorManager(DummyServices(temp_dir, {"monitor_fast_check_enabled": True}))
                account = await manager.add_account("https://www.douyin.com/user/MS4wLjABAAAA_fast", "fast")
                account.monitor_enabled = True
                account.aweme_count = 3
                account.last_aweme_count = 3
                account.items.append(DouyinContentItem(item_id="old", title="old", share_url="https://www.douyin.com/video/old"))

                async def fake_fetch_public_profile(account, include_cookie=True):
                    return "<html></html>", account.homepage_url

                async def fake_hydrate(account_id: str, force: bool = False):
                    return {"success": True, "display_name": "fast"}

                async def fake_profile_info(account):
                    return {"aweme_count": 3, "sec_uid": "MS4wLjABAAAA_fast"}

                async def should_not_call_parser(account, max_pages=None):
                    raise AssertionError("parser should be skipped by fast no-change check")

                manager.fetch_public_profile = fake_fetch_public_profile  # type: ignore[method-assign]
                manager.hydrate_account_display_name = fake_hydrate  # type: ignore[method-assign]
                manager.fetch_user_profile_info = fake_profile_info  # type: ignore[method-assign]
                manager._public_profile_page_matches_account = lambda account, text, url: True  # type: ignore[method-assign]
                manager._profile_info_matches_account = lambda account, info: True  # type: ignore[method-assign]
                manager.fetch_parser_user_posts = should_not_call_parser  # type: ignore[method-assign]
                return await manager.check_account(account.account_id)

        result = asyncio.run(run_case())
        self.assertTrue(result["success"])
        self.assertIn("快速检测", result["reason"])

    def test_batch_job_store_resumes_remaining_items(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            store = BatchJobStore(temp_dir)
            job = store.start_or_resume("job-1", total=3, item_ids=["a", "b", "c"])
            store.mark_item(job.job_id, "a", status="completed")
            store.mark_item(job.job_id, "b", status="failed", reason="boom")

            restored = BatchJobStore(temp_dir)
            resumed = restored.start_or_resume("job-1", total=3, item_ids=["a", "b", "c"])
            self.assertIn("a", resumed.completed_ids)
            self.assertIn("b", resumed.failed_ids)
            self.assertEqual(set(resumed.remaining_item_ids()), {"b", "c"})


if __name__ == "__main__":
    unittest.main()
