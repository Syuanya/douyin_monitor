from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .status_rules import is_download_failed_item, is_downloaded_item, is_gallery_item, is_pending_new_work_item


def _get(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _text(value: Any) -> str:
    return str(value or "").strip()


def parse_monitor_time(value: Any) -> float:
    text = _text(value)
    if not text or text == "-":
        return 0.0
    if text.isdigit():
        try:
            return float(int(text[:10]))
        except Exception:
            return 0.0
    normalized = text.replace("T", " ").replace("/", "-").strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(normalized[: len(fmt)], fmt).timestamp()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def item_best_timestamp(item: Any) -> float:
    return max(
        parse_monitor_time(_get(item, "publish_time")),
        parse_monitor_time(_get(item, "first_seen_time")),
        parse_monitor_time(_get(item, "last_seen_time")),
        parse_monitor_time(_get(item, "downloaded_at")),
        parse_monitor_time(_get(item, "processed_at")),
    )


def _item_id_sort_value(item: Any) -> int:
    try:
        return int(_text(_get(item, "item_id"))[:18] or 0)
    except Exception:
        return 0


def _account_name(account: Any) -> str:
    return _text(_get(account, "display_name")) or _text(_get(account, "douyin_nickname")) or "抖音用户"


def _group_name(account: Any) -> str:
    return _text(_get(account, "group_name")) or "未分组"


def account_health_insight(account: Any, *, now_ts: float | None = None, default_interval_minutes: float = 10.0) -> dict[str, Any]:
    """Return a compact, user-facing health score for one monitor account.

    The score is intentionally heuristic. It is used for prioritizing accounts that need attention,
    not for making irreversible decisions.
    """
    if now_ts is None:
        now_ts = time.time()
    items = list(_get(account, "items", []) or [])
    error_count = max(0, int(_get(account, "error_count", 0) or 0))
    last_error = _text(_get(account, "last_error"))
    monitor_enabled = bool(_get(account, "monitor_enabled", False))
    status = _text(_get(account, "status"))
    interval_minutes = float(_get(account, "monitor_interval_minutes", 0.0) or 0.0) or float(default_interval_minutes or 10.0)
    interval_seconds = max(60.0, interval_minutes * 60.0)
    last_success_ts = parse_monitor_time(_get(account, "last_success_time"))
    last_check_ts = parse_monitor_time(_get(account, "last_check_time"))
    failed_download = len([item for item in items if is_download_failed_item(item)])
    pending_new = len([item for item in items if is_pending_new_work_item(item)])
    score = 100
    reasons: list[str] = []
    next_steps: list[str] = []

    if not monitor_enabled:
        score -= 35
        reasons.append("账号未启用监控")
        next_steps.append("需要持续跟踪时，开启该账号监控")

    if error_count:
        penalty = min(35, error_count * 8)
        score -= penalty
        reasons.append(f"连续/累计异常 {error_count} 次")
        next_steps.append("查看异常详情并执行重新检测")

    if last_error:
        score -= 10
        lowered = last_error.lower()
        if any(token in lowered for token in ("cookie", "登录", "login", "403", "风控", "verify")):
            reasons.append("疑似 Cookie / 登录态 / 风控问题")
            next_steps.append("检查 Cookie 健康状态，必要时更换 Cookie 后重试")
        elif any(token in lowered for token in ("timeout", "超时", "proxy", "代理", "network", "连接")):
            reasons.append("疑似网络 / 代理连接问题")
            next_steps.append("检查代理、网络和请求超时设置")
        else:
            reasons.append("最近检测存在错误")

    if monitor_enabled and last_success_ts <= 0:
        score -= 15
        reasons.append("尚无成功检测记录")
        next_steps.append("手动同步一次作品，确认账号主页和解析链路正常")
    elif monitor_enabled:
        age = now_ts - last_success_ts
        if age > max(interval_seconds * 3, 24 * 3600):
            score -= 15
            reasons.append("最近成功检测已过期")
            next_steps.append("立即检测该账号，确认是否被限流或主页不可访问")
        if age > 7 * 24 * 3600:
            score -= 10
            reasons.append("超过 7 天无成功检测")

    if monitor_enabled and last_check_ts > 0 and now_ts - last_check_ts > max(interval_seconds * 4, 48 * 3600):
        score -= 8
        reasons.append("最近检测时间明显滞后")

    if failed_download:
        score -= min(15, failed_download * 3)
        reasons.append(f"有 {failed_download} 个下载失败作品")
        next_steps.append("优先重试可恢复的下载失败作品，跳过作品失效项")

    if pending_new >= 50:
        score -= 8
        reasons.append(f"待处理新作品较多：{pending_new} 个")
        next_steps.append("批量下载或批量标记已处理，避免新作品箱堆积")

    if any(token in status for token in ("暂停", "失败", "异常", "风控", "Cookie", "登录")):
        score -= 10
        if status:
            reasons.append(f"账号状态：{status}")

    score = max(0, min(100, int(score)))
    if not monitor_enabled:
        level = "paused"
        label = "未监控"
    elif score >= 85:
        level = "excellent"
        label = "健康"
    elif score >= 70:
        level = "good"
        label = "正常"
    elif score >= 50:
        level = "warning"
        label = "需关注"
    else:
        level = "risk"
        label = "高风险"
    if not reasons:
        reasons.append("监控、检测和下载状态正常")
    # Keep the card concise and deterministic.
    deduped_steps: list[str] = []
    for step in next_steps:
        if step and step not in deduped_steps:
            deduped_steps.append(step)
    return {
        "account_id": _text(_get(account, "account_id")),
        "account_name": _account_name(account),
        "group_name": _group_name(account),
        "score": score,
        "level": level,
        "label": label,
        "reasons": reasons[:5],
        "next_steps": deduped_steps[:4],
        "monitor_enabled": monitor_enabled,
        "last_check_time": _text(_get(account, "last_check_time")),
        "last_success_time": _text(_get(account, "last_success_time")),
        "error_count": error_count,
        "pending_new": pending_new,
        "download_failed": failed_download,
        "total_items": len(items),
    }


def health_summary(accounts: Iterable[Any], *, now_ts: float | None = None, default_interval_minutes: float = 10.0) -> dict[str, Any]:
    rows = [account_health_insight(account, now_ts=now_ts, default_interval_minutes=default_interval_minutes) for account in accounts]
    counts: dict[str, int] = {"excellent": 0, "good": 0, "warning": 0, "risk": 0, "paused": 0}
    for row in rows:
        counts[row["level"]] = counts.get(row["level"], 0) + 1
    priority = sorted(rows, key=lambda row: (row["score"], -row["error_count"], -row["download_failed"], row["account_name"]))
    avg_score = round(sum(row["score"] for row in rows) / len(rows), 1) if rows else 0.0
    return {"total": len(rows), "average_score": avg_score, "counts": counts, "accounts": rows, "priority_accounts": priority[:20]}


def group_statistics(accounts: Iterable[Any], *, now_ts: float | None = None, default_interval_minutes: float = 10.0) -> dict[str, Any]:
    groups: dict[str, dict[str, Any]] = {}
    for account in accounts:
        group = _group_name(account)
        bucket = groups.setdefault(
            group,
            {
                "group_name": group,
                "accounts_total": 0,
                "accounts_enabled": 0,
                "accounts_with_errors": 0,
                "items_total": 0,
                "pending_new": 0,
                "downloaded": 0,
                "download_failed": 0,
                "gallery": 0,
                "video": 0,
                "health_score_total": 0,
            },
        )
        items = list(_get(account, "items", []) or [])
        health = account_health_insight(account, now_ts=now_ts, default_interval_minutes=default_interval_minutes)
        bucket["accounts_total"] += 1
        bucket["accounts_enabled"] += 1 if bool(_get(account, "monitor_enabled", False)) else 0
        bucket["accounts_with_errors"] += 1 if int(_get(account, "error_count", 0) or 0) > 0 or _text(_get(account, "last_error")) else 0
        bucket["items_total"] += len([item for item in items if _text(_get(item, "status")) != "count_only"])
        bucket["pending_new"] += len([item for item in items if is_pending_new_work_item(item)])
        bucket["downloaded"] += len([item for item in items if is_downloaded_item(item)])
        bucket["download_failed"] += len([item for item in items if is_download_failed_item(item)])
        bucket["gallery"] += len([item for item in items if is_gallery_item(item)])
        bucket["video"] += len([item for item in items if not is_gallery_item(item) and _text(_get(item, "status")) != "count_only"])
        bucket["health_score_total"] += health["score"]
    rows: list[dict[str, Any]] = []
    for bucket in groups.values():
        total = max(1, int(bucket["accounts_total"] or 0))
        bucket["average_health_score"] = round(bucket.pop("health_score_total") / total, 1)
        rows.append(bucket)
    return {"total_groups": len(rows), "groups": sorted(rows, key=lambda row: (-row["pending_new"], -row["download_failed"], row["group_name"]))}


def material_collection(
    accounts: Iterable[Any],
    *,
    query: str = "",
    status: str = "pending",
    media_type: str = "all",
    group_name: str = "",
    limit: int = 200,
) -> dict[str, Any]:
    needle = _text(query).lower()
    status_filter = _text(status).lower() or "pending"
    media_filter = _text(media_type).lower() or "all"
    group_filter = _text(group_name)
    rows: list[dict[str, Any]] = []
    for account in accounts:
        account_group = _group_name(account)
        if group_filter and account_group != group_filter:
            continue
        account_name = _account_name(account)
        for item in list(_get(account, "items", []) or []):
            item_status = _text(_get(item, "status"))
            if item_status == "count_only":
                continue
            gallery = is_gallery_item(item)
            downloaded = is_downloaded_item(item)
            failed = is_download_failed_item(item)
            pending = is_pending_new_work_item(item)
            if status_filter == "pending" and not pending:
                continue
            if status_filter == "new" and item_status != "new":
                continue
            if status_filter == "downloaded" and not downloaded:
                continue
            if status_filter in {"failed", "download_failed"} and not failed:
                continue
            if status_filter == "unprocessed" and (downloaded or item_status == "active"):
                continue
            if status_filter not in {"all", "pending", "new", "downloaded", "failed", "download_failed", "unprocessed"} and item_status != status_filter:
                continue
            if media_filter in {"gallery", "image", "images", "note"} and not gallery:
                continue
            if media_filter == "video" and gallery:
                continue
            haystack = " ".join(
                _text(value)
                for value in (
                    _get(item, "title"),
                    _get(item, "share_url"),
                    _get(item, "item_id"),
                    account_name,
                    account_group,
                )
            ).lower()
            if needle and needle not in haystack:
                continue
            rows.append(
                {
                    "account_id": _text(_get(account, "account_id")),
                    "account_name": account_name,
                    "group_name": account_group,
                    "homepage_url": _text(_get(account, "homepage_url")),
                    "item_id": _text(_get(item, "item_id")),
                    "title": _text(_get(item, "title")),
                    "share_url": _text(_get(item, "share_url")),
                    "media_type": "gallery" if gallery else "video",
                    "status": item_status,
                    "publish_time": _text(_get(item, "publish_time")),
                    "first_seen_time": _text(_get(item, "first_seen_time")),
                    "download_path": _text(_get(item, "download_path")),
                    "failure_category": _text(_get(item, "failure_category")),
                    "failure_next_step": _text(_get(item, "failure_next_step")),
                    "sort_ts": item_best_timestamp(item),
                }
            )
    rows.sort(key=lambda row: (float(row.get("sort_ts") or 0.0), _item_id_sort_value(row)), reverse=True)
    max_limit = max(1, min(1000, int(limit or 200)))
    visible = rows[:max_limit]
    for row in visible:
        row.pop("sort_ts", None)
    return {"total": len(rows), "limit": max_limit, "items": visible}


def time_window_digest(accounts: Iterable[Any], *, days: int = 1, now_ts: float | None = None) -> dict[str, Any]:
    if now_ts is None:
        now_ts = time.time()
    days = max(1, min(90, int(days or 1)))
    start_ts = now_ts - days * 24 * 3600
    new_items: list[dict[str, Any]] = []
    downloaded = failed = gallery = video = 0
    account_counts: dict[str, dict[str, Any]] = {}
    for account in accounts:
        account_id = _text(_get(account, "account_id"))
        account_name = _account_name(account)
        for item in list(_get(account, "items", []) or []):
            ts = max(parse_monitor_time(_get(item, "first_seen_time")), parse_monitor_time(_get(item, "publish_time")), parse_monitor_time(_get(item, "last_seen_time")))
            if ts <= 0 or ts < start_ts:
                continue
            bucket = account_counts.setdefault(account_id, {"account_id": account_id, "account_name": account_name, "new_items": 0, "downloaded": 0, "failed": 0})
            bucket["new_items"] += 1
            if is_downloaded_item(item):
                downloaded += 1
                bucket["downloaded"] += 1
            if is_download_failed_item(item):
                failed += 1
                bucket["failed"] += 1
            if is_gallery_item(item):
                gallery += 1
            else:
                video += 1
            new_items.append({"account_id": account_id, "account_name": account_name, "item_id": _text(_get(item, "item_id")), "title": _text(_get(item, "title")), "status": _text(_get(item, "status")), "media_type": "gallery" if is_gallery_item(item) else "video", "time": datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S"), "share_url": _text(_get(item, "share_url")), "sort_ts": ts})
    new_items.sort(key=lambda row: float(row.get("sort_ts") or 0.0), reverse=True)
    for row in new_items:
        row.pop("sort_ts", None)
    top_accounts = sorted(account_counts.values(), key=lambda row: (-row["new_items"], row["account_name"]))[:20]
    return {"days": days, "new_items": len(new_items), "downloaded": downloaded, "failed": failed, "gallery": gallery, "video": video, "top_accounts": top_accounts, "items": new_items[:200]}


def export_material_links_csv(path: str | Path, rows: list[dict[str, Any]]) -> None:
    columns = ["账号", "分组", "作品ID", "标题", "类型", "状态", "发布时间", "首次发现", "作品链接", "下载位置", "失败分类", "处理建议"]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([
                row.get("account_name", ""),
                row.get("group_name", ""),
                row.get("item_id", ""),
                row.get("title", ""),
                row.get("media_type", ""),
                row.get("status", ""),
                row.get("publish_time", ""),
                row.get("first_seen_time", ""),
                row.get("share_url", ""),
                row.get("download_path", ""),
                row.get("failure_category", ""),
                row.get("failure_next_step", ""),
            ])
