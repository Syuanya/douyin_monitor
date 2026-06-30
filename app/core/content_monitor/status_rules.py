from __future__ import annotations

from typing import Any

NEW_STATUS = "new"
COUNT_ONLY_STATUS = "count_only"
DOWNLOADED_STATUS = "downloaded"
DOWNLOAD_FAILED_STATUS = "download_failed"
ACTIVE_STATUS = "active"
PENDING_NEW_WORK_STATUSES = {NEW_STATUS, COUNT_ONLY_STATUS, DOWNLOAD_FAILED_STATUS}
GALLERY_MEDIA_TYPES = {"image", "images", "gallery", "note"}


def item_status(item: Any) -> str:
    if isinstance(item, dict):
        return str(item.get("status") or "")
    return str(getattr(item, "status", "") or "")


def is_pending_new_work_item(item: Any) -> bool:
    return item_status(item) in PENDING_NEW_WORK_STATUSES


def is_count_only_item(item: Any) -> bool:
    return item_status(item) == COUNT_ONLY_STATUS


def is_download_failed_item(item: Any) -> bool:
    return item_status(item) == DOWNLOAD_FAILED_STATUS


def is_downloaded_item(item: Any) -> bool:
    return item_status(item) == DOWNLOADED_STATUS


def is_gallery_item(item: Any) -> bool:
    if isinstance(item, dict):
        media_type = str(item.get("media_type") or "").lower()
        return bool(item.get("image_urls")) or media_type in GALLERY_MEDIA_TYPES
    media_type = str(getattr(item, "media_type", "") or "").lower()
    return bool(getattr(item, "image_urls", None)) or media_type in GALLERY_MEDIA_TYPES
