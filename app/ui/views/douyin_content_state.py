from __future__ import annotations

from typing import Any, Iterable, Sequence

from ...core.content_monitor import status_rules

PENDING_NEW_WORK_STATUSES = status_rules.PENDING_NEW_WORK_STATUSES
COUNT_ONLY_STATUS = status_rules.COUNT_ONLY_STATUS
DOWNLOAD_FAILED_STATUS = status_rules.DOWNLOAD_FAILED_STATUS
DOWNLOADED_STATUS = status_rules.DOWNLOADED_STATUS
DEFAULT_WORK_PAGE_SIZE = 20
DEFAULT_ACCOUNT_PAGE_SIZE = 30


def item_status(item: Any) -> str:
    return status_rules.item_status(item)


def is_pending_new_work_item(item: Any) -> bool:
    return status_rules.is_pending_new_work_item(item)


def is_count_only_item(item: Any) -> bool:
    return status_rules.is_count_only_item(item)


def is_gallery_item(item: Any) -> bool:
    return status_rules.is_gallery_item(item)


def pending_new_work_count(accounts: Iterable[Any]) -> int:
    return sum(1 for account in accounts for item in getattr(account, "items", []) or [] if is_pending_new_work_item(item))


def pending_new_work_count_for_account(account: Any) -> int:
    return sum(1 for item in getattr(account, "items", []) or [] if is_pending_new_work_item(item))


def sync_account_last_new_count(account: Any) -> int:
    count = pending_new_work_count_for_account(account)
    account.last_new_count = count
    return count


def new_work_entries(accounts: Iterable[Any]) -> list[tuple[Any, Any]]:
    entries: list[tuple[Any, Any]] = []
    for account in accounts:
        for item in getattr(account, "items", []) or []:
            if is_pending_new_work_item(item):
                entries.append((account, item))
    entries.sort(key=lambda entry: getattr(entry[1], "first_seen_time", "") or getattr(entry[1], "publish_time", ""), reverse=True)
    return entries


def filter_accounts(accounts: Sequence[Any], mode: str) -> list[Any]:
    normalized = str(mode or "all")
    if normalized == "enabled":
        return [account for account in accounts if getattr(account, "monitor_enabled", False)]
    if normalized == "new":
        return [account for account in accounts if pending_new_work_count_for_account(account) > 0]
    if normalized == "error":
        return [account for account in accounts if getattr(account, "last_error", "") or "异常" in str(getattr(account, "status", ""))]
    if normalized == "stopped":
        return [account for account in accounts if not getattr(account, "monitor_enabled", False)]
    return list(accounts)


def visible_accounts(
    accounts: Sequence[Any],
    *,
    mode: str = "all",
    group_filter: str = "all",
    search_query: str = "",
) -> list[Any]:
    filtered = filter_accounts(accounts, mode)
    group = str(group_filter or "all")
    if group == "__ungrouped__":
        filtered = [account for account in filtered if not str(getattr(account, "group_name", "") or "").strip()]
    elif group != "all":
        filtered = [account for account in filtered if str(getattr(account, "group_name", "") or "").strip() == group]
    query = str(search_query or "").strip().lower()
    if query:
        filtered = [
            account
            for account in filtered
            if query in str(getattr(account, "display_name", "") or "").lower()
            or query in str(getattr(account, "douyin_nickname", "") or "").lower()
            or query in str(getattr(account, "group_name", "") or "").lower()
            or query in str(getattr(account, "homepage_url", "") or "").lower()
        ]
    return filtered


def filter_work_items(items: Iterable[Any], mode: str) -> list[Any]:
    normalized = str(mode or "all").lower()
    base = [item for item in items if not is_count_only_item(item)]
    if normalized == "new":
        return [item for item in base if item_status(item) == "new"]
    if normalized == "pending":
        return [item for item in base if item_status(item) not in {DOWNLOADED_STATUS, DOWNLOAD_FAILED_STATUS}]
    if normalized == "downloaded":
        return [item for item in base if item_status(item) == DOWNLOADED_STATUS]
    if normalized == "failed":
        return [item for item in base if item_status(item) == DOWNLOAD_FAILED_STATUS]
    if normalized == "video":
        return [item for item in base if not is_gallery_item(item)]
    if normalized == "gallery":
        return [item for item in base if is_gallery_item(item)]
    return base


def filter_download_items(items: Iterable[Any], mode: str) -> list[Any]:
    normalized = str(mode or "all").lower()
    base = [item for item in items if not is_count_only_item(item)]
    if normalized == "new":
        return [item for item in base if item_status(item) == "new"]
    if normalized == "pending":
        return [item for item in base if item_status(item) not in {DOWNLOADED_STATUS, DOWNLOAD_FAILED_STATUS}]
    if normalized == "failed":
        return [item for item in base if item_status(item) == DOWNLOAD_FAILED_STATUS]
    if normalized == "downloaded":
        return [item for item in base if item_status(item) == DOWNLOADED_STATUS]
    if normalized == "gallery":
        return [item for item in base if is_gallery_item(item)]
    if normalized == "video":
        return [item for item in base if not is_gallery_item(item)]
    return base


def download_filter_label(filter_mode: str) -> str:
    mapping = {
        "new": "新作品",
        "pending": "未下载作品",
        "downloaded": "已下载作品",
        "failed": "下载失败作品",
        "gallery": "图集作品",
        "video": "视频作品",
    }
    return mapping.get(str(filter_mode or "all").lower(), "全部作品")


def download_status_counts(items: Iterable[Any]) -> dict[str, int]:
    counts = {"total": 0, "pending": 0, "new": 0, "downloaded": 0, "failed": 0, "count_only": 0, "gallery": 0, "video": 0}
    for item in items:
        counts["total"] += 1
        status = item_status(item)
        if status == "new":
            counts["new"] += 1
        if status == DOWNLOADED_STATUS:
            counts["downloaded"] += 1
        elif status == DOWNLOAD_FAILED_STATUS:
            counts["failed"] += 1
        elif status == COUNT_ONLY_STATUS:
            counts["count_only"] += 1
        else:
            counts["pending"] += 1
        if not is_count_only_item(item):
            if is_gallery_item(item):
                counts["gallery"] += 1
            else:
                counts["video"] += 1
    return counts


def batch_failure_category(reason: str) -> str:
    text = str(reason or "").lower()
    if any(token in text for token in ("空响应", "empty", "风控", "captcha", "verify", "429", "418")):
        return "risk_control"
    if any(token in text for token in ("cookie", "登录", "mstoken", "a_bogus")):
        return "cookie"
    if any(token in text for token in ("不存在", "不可访问", "无公开", "private", "404")):
        return "profile"
    if any(token in text for token in ("取消", "cancel")):
        return "cancelled"
    return "other"


def clamp_page_size(value: Any, *, default: int, minimum: int = 1, maximum: int = 500) -> int:
    try:
        parsed = int(value or default)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def display_window(total: int, visible_count: Any, page_size: int) -> tuple[int, int]:
    if total <= 0:
        return 0, 0
    visible = max(1, min(total, clamp_page_size(visible_count, default=page_size, maximum=max(total, page_size))))
    next_visible = min(total, visible + max(1, int(page_size or 1)))
    return visible, next_visible
