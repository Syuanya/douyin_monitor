from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from ..models import DouyinContentItem
else:
    DouyinContentItem = Any


class ContentMergeService:
    """Rules for merging detected works into an account state."""

    def __init__(
        self,
        *,
        now_fn: Callable[[], str],
        sort_items_newest_first: Callable[[list[DouyinContentItem]], list[DouyinContentItem]],
        is_gallery_item: Callable[[DouyinContentItem], bool],
    ):
        self.now_fn = now_fn
        self.sort_items_newest_first = sort_items_newest_first
        self.is_gallery_item = is_gallery_item

    def merge_detected_items(self, account: Any, detected_items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        now = self.now_fn()
        known = set(getattr(account, "known_item_ids", []) or [])
        first_success = not known and not getattr(account, "items", [])
        by_id = {item.item_id: item for item in getattr(account, "items", [])}
        new_items: list[DouyinContentItem] = []
        for item in detected_items:
            existing = by_id.get(item.item_id)
            if existing:
                existing.last_seen_time = now
                if existing.status not in {"new", "downloaded", "download_failed"}:
                    existing.status = "active"
                if item.title and existing.title.startswith("抖音作品 "):
                    existing.title = item.title
                if item.publish_time and not existing.publish_time:
                    existing.publish_time = item.publish_time
                if item.share_url:
                    existing.share_url = item.share_url
                if item.download_url and self.is_gallery_item(item):
                    existing.download_url = item.download_url
                if item.cover_url:
                    existing.cover_url = item.cover_url
                if item.media_type:
                    existing.media_type = item.media_type
                if item.image_urls:
                    existing.image_urls = item.image_urls
            else:
                item.first_seen_time = now
                item.last_seen_time = now
                item.status = "new" if not first_success and item.item_id not in known else "active"
                account.items.insert(0, item)
                if not first_success and item.item_id not in known:
                    new_items.append(item)
        account.items = self.sort_items_newest_first(account.items)[:200]
        account.known_item_ids = list(dict.fromkeys([item.item_id for item in detected_items] + list(account.known_item_ids)))[:500]
        account.last_item_id = detected_items[0].item_id if detected_items else account.last_item_id
        return new_items

    def apply_retention(self, account: Any) -> None:
        limit = int(getattr(account, "keep_recent_count", 0) or 0)
        if limit <= 0:
            return
        normal_items = [item for item in self.sort_items_newest_first(account.items) if item.status != "count_only"]
        count_items = [item for item in account.items if item.status == "count_only"]
        keep_items = normal_items[:limit] + count_items[: min(len(count_items), 20)]
        keep_ids = {item.item_id for item in keep_items}
        account.items = keep_items
        account.known_item_ids = [item_id for item_id in account.known_item_ids if item_id in keep_ids]

    @staticmethod
    def auto_pause_if_needed(account: Any) -> bool:
        threshold = int(getattr(account, "auto_pause_failures", 0) or 0)
        if threshold <= 0 or int(getattr(account, "error_count", 0) or 0) < threshold:
            return False
        account.monitor_enabled = False
        account.status = f"已自动暂停：连续失败 {account.error_count} 次"
        return True
