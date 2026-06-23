from __future__ import annotations

import tempfile
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.content_monitor.douyin_api_client import DouyinExternalApiClient
from app.core.network.cookie_health_store import CookieHealthStore
from app.core.parser.douyin_backends import FallbackDouyinParserBackend
from app.core.runtime.batch_job_store import BatchJobStore
from app.core.ui_services.performance_observability_service import PerformanceObservabilityService


def test_external_api_normalizes_single_video_payload() -> None:
    data = {
        "aweme_detail": {
            "aweme_id": "7123456789012345678",
            "desc": "hello",
            "video": {"play_addr": {"url_list": ["https://example.com/video.mp4"]}},
        }
    }
    normalized = DouyinExternalApiClient.normalize_single_video_payload(data, source_url="https://www.douyin.com/video/7123456789012345678")
    assert normalized["aweme_id"] == "7123456789012345678"
    assert normalized["video_data"]["nwm_video_url"] == "https://example.com/video.mp4"


@pytest.mark.asyncio
async def test_fallback_backend_passes_supported_kwargs() -> None:
    class ExternalLike:
        name = "external_like"
        platform = "douyin"

        async def health_check(self):
            from app.core.parser.backend import ParserCapabilities, ParserHealth

            return ParserHealth(True, "external_like", "ok", ParserCapabilities(parse_url=True), "test")

        def capabilities(self):
            from app.core.parser.backend import ParserCapabilities

            return ParserCapabilities(parse_url=True)

        async def parse_url(self, url: str, *, cookie: str = ""):
            return {"platform": "douyin", "type": "video", "aweme_id": "1", "video_data": {"nwm_video_url": cookie}, "image_data": {}, "author": {}}

    backend = FallbackDouyinParserBackend(ExternalLike())
    result = await backend.parse_url("https://www.douyin.com/video/1", cookie="sessionid=x")
    assert result["video_data"]["nwm_video_url"] == "sessionid=x"


def test_cookie_health_observability_and_clear() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = CookieHealthStore(tmp)
        cookie = "sessionid=test; ttwid=test;"
        store.register_pool("douyin", [cookie])
        store.record_failure("douyin", cookie, "HTTP 200 空响应", cooldown_seconds=120)
        app = SimpleNamespace(services=SimpleNamespace(cookie_health_store=store))
        service = PerformanceObservabilityService(app)
        summary = service.cookie_health_summary("douyin")
        assert summary["total"] == 1
        assert summary["cooldown"] == 1
        assert service.clear_cookie_health("douyin") == 1
        assert service.cookie_health_summary("douyin")["total"] == 0


def test_batch_job_pause_resume_cancel_snapshot_detail() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        store = BatchJobStore(tmp)
        job = store.start_or_resume("batch:key", "批量下载", 3, item_ids=["a", "b", "c"])
        store.mark_item(job.job_id, "a", "completed")
        store.mark_item(job.job_id, "b", "failed", "network")
        store.pause(job.job_id)
        detail = store.detail(job.job_id)
        assert detail["status"] == "paused"
        assert detail["completed"] == 1
        assert detail["failed"] == 1
        assert detail["remaining_ids"] == ["b", "c"]
        store.resume(job.job_id)
        assert store.detail(job.job_id)["status"] == "running"
        store.cancel(job.job_id, "user")
        assert store.is_cancelled(job.job_id)


def test_segmented_download_snapshot_available() -> None:
    from app.core.media.resumable_download import segmented_download_snapshot

    snapshot = segmented_download_snapshot()
    assert snapshot["available"] is True
    assert "blacklisted_hosts" in snapshot


def test_validation_scripts_exist() -> None:
    root = Path(__file__).resolve().parents[1]
    for relative in (
        "scripts/live_douyin_benchmark.py",
        "scripts/verify_legacy_migration.py",
        "scripts/verify_windows_package.py",
        "docs/RELEASE_CHECKLIST.md",
        "docs/PRODUCTION_CLOSURE_1_TO_9.md",
    ):
        assert (root / relative).exists()
