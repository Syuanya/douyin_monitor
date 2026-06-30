from __future__ import annotations

import os
import tempfile
import unittest

from app.core.content_monitor.douyin_content_monitor import DouyinContentItem, DouyinContentMonitorManager, DouyinMonitorAccount
from app.core.content_monitor.insights import account_health_insight, group_statistics, material_collection, time_window_digest
from app.core.storage.sqlite_store import SQLiteStore


class DummySettings:
    def __init__(self, user_config=None):
        self.user_config = user_config or {"douyin_content_monitor_interval_minutes": 10}

    def get_cookies_value(self, _key: str, default: str = "") -> str:
        return default


class DummyServices:
    def __init__(self, run_path: str, user_config=None):
        self.run_path = run_path
        self.settings_config = DummySettings(user_config)
        self.sqlite_store = SQLiteStore(run_path)
        self.video_parser = None
        self.task_center = None
        self.batch_job_store = None
        self.media_task_queue = None
        self.events = []

    def broadcast_pubsub(self, topic, payload):
        self.events.append((topic, payload))

    def broadcast_snack(self, *_args, **_kwargs) -> None:
        return None

    def snapshot_bridges(self) -> list:
        return []


def make_accounts():
    return [
        DouyinMonitorAccount(
            account_id="a1",
            homepage_url="https://www.douyin.com/user/a1",
            display_name="健康账号",
            group_name="美食",
            monitor_enabled=True,
            last_check_time="2026-06-30 09:55:00",
            last_success_time="2026-06-30 09:55:00",
            items=[
                DouyinContentItem(item_id="101", title="新视频", status="new", media_type="video", first_seen_time="2026-06-30 09:50:00", share_url="https://v.douyin.com/101"),
                DouyinContentItem(item_id="102", title="已下载图集", status="downloaded", media_type="image", image_urls=["https://img/1.jpg"], first_seen_time="2026-06-30 09:40:00", download_path="/tmp/102"),
            ],
        ),
        DouyinMonitorAccount(
            account_id="a2",
            homepage_url="https://www.douyin.com/user/a2",
            display_name="异常账号",
            group_name="美食",
            monitor_enabled=True,
            last_check_time="2026-06-20 09:55:00",
            last_success_time="2026-06-20 09:55:00",
            error_count=3,
            last_error="Cookie 失效 403",
            items=[
                DouyinContentItem(item_id="201", title="失败作品", status="download_failed", failure_category="作品失效", failure_retryable=False, failure_next_step="打开原链接确认", first_seen_time="2026-06-30 09:10:00"),
            ],
        ),
        DouyinMonitorAccount(
            account_id="a3",
            homepage_url="https://www.douyin.com/user/a3",
            display_name="暂停账号",
            group_name="旅游",
            monitor_enabled=False,
            items=[DouyinContentItem(item_id="301", title="旧作品", status="active", first_seen_time="2026-06-01 09:10:00")],
        ),
    ]


class ContentMonitorP3InsightsTest(unittest.TestCase):
    def test_account_health_prioritizes_error_cookie_account(self) -> None:
        accounts = make_accounts()
        healthy = account_health_insight(accounts[0], now_ts=1782784800, default_interval_minutes=10)
        risky = account_health_insight(accounts[1], now_ts=1782784800, default_interval_minutes=10)

        self.assertGreaterEqual(healthy["score"], 70)
        self.assertLess(risky["score"], healthy["score"])
        self.assertIn("Cookie", " ".join(risky["reasons"] + risky["next_steps"]))
        self.assertEqual(risky["download_failed"], 1)

    def test_group_statistics_counts_pending_downloaded_failed_and_media_types(self) -> None:
        stats = group_statistics(make_accounts(), now_ts=1782784800)
        groups = {row["group_name"]: row for row in stats["groups"]}

        self.assertEqual(groups["美食"]["accounts_total"], 2)
        self.assertEqual(groups["美食"]["pending_new"], 2)
        self.assertEqual(groups["美食"]["downloaded"], 1)
        self.assertEqual(groups["美食"]["download_failed"], 1)
        self.assertEqual(groups["美食"]["gallery"], 1)

    def test_material_collection_filters_pending_gallery_query_and_group(self) -> None:
        all_pending = material_collection(make_accounts(), status="pending", media_type="all", group_name="美食")
        gallery = material_collection(make_accounts(), status="downloaded", media_type="gallery")
        query = material_collection(make_accounts(), query="失败", status="all")

        self.assertEqual(all_pending["total"], 2)
        self.assertEqual(gallery["total"], 1)
        self.assertEqual(gallery["items"][0]["media_type"], "gallery")
        self.assertEqual(query["items"][0]["item_id"], "201")

    def test_time_window_digest_summarizes_recent_materials(self) -> None:
        digest = time_window_digest(make_accounts(), days=1, now_ts=1782784800)

        self.assertEqual(digest["new_items"], 3)
        self.assertEqual(digest["downloaded"], 1)
        self.assertEqual(digest["failed"], 1)
        self.assertEqual(digest["top_accounts"][0]["account_name"], "健康账号")

    def test_manager_p3_methods_and_export_material_links(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = DouyinContentMonitorManager(DummyServices(temp_dir))
            manager._accounts = make_accounts()

            health = manager.content_monitor_health_summary()
            groups = manager.content_monitor_group_statistics()
            materials = manager.content_monitor_material_collection(status="pending")
            export = manager.export_content_monitor_material_links(status="pending")
            detail = manager.account_health_detail("a2")

            self.assertEqual(health["total"], 3)
            self.assertEqual(groups["total_groups"], 2)
            self.assertEqual(materials["total"], 2)
            self.assertTrue(export["success"])
            self.assertTrue(os.path.exists(export["path"]))
            self.assertTrue(detail["success"])
            self.assertEqual(detail["account_id"], "a2")
            self.assertIn("download_summary", detail)


if __name__ == "__main__":
    unittest.main()
