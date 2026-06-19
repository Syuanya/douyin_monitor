from __future__ import annotations

import unittest
from dataclasses import dataclass, field

from app.core.content_monitor.services.content_merge_service import ContentMergeService


@dataclass
class Item:
    item_id: str
    title: str = ""
    share_url: str = ""
    download_url: str = ""
    cover_url: str = ""
    media_type: str = "video"
    image_urls: list[str] = field(default_factory=list)
    publish_time: str = ""
    first_seen_time: str = ""
    last_seen_time: str = ""
    status: str = "active"


@dataclass
class Account:
    items: list[Item] = field(default_factory=list)
    known_item_ids: list[str] = field(default_factory=list)
    last_item_id: str = ""
    keep_recent_count: int = 0
    auto_pause_failures: int = 0
    error_count: int = 0
    monitor_enabled: bool = True
    status: str = ""


class ContentMergeServiceTest(unittest.TestCase):
    def service(self) -> ContentMergeService:
        return ContentMergeService(
            now_fn=lambda: "2026-01-01 00:00:00",
            sort_items_newest_first=lambda items: sorted(items, key=lambda item: item.item_id, reverse=True),
            is_gallery_item=lambda item: bool(item.image_urls),
        )

    def test_first_success_creates_baseline_without_new_items(self) -> None:
        account = Account()

        new_items = self.service().merge_detected_items(account, [Item("1", "first")])

        self.assertEqual(new_items, [])
        self.assertEqual(account.items[0].status, "active")
        self.assertEqual(account.known_item_ids, ["1"])

    def test_later_unknown_item_is_marked_new(self) -> None:
        account = Account(items=[Item("1")], known_item_ids=["1"])

        new_items = self.service().merge_detected_items(account, [Item("2", "second")])

        self.assertEqual([item.item_id for item in new_items], ["2"])
        self.assertEqual(account.items[0].status, "new")

    def test_auto_pause_if_needed(self) -> None:
        account = Account(auto_pause_failures=2, error_count=2)

        paused = self.service().auto_pause_if_needed(account)

        self.assertTrue(paused)
        self.assertFalse(account.monitor_enabled)
