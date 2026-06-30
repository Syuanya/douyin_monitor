from __future__ import annotations

from typing import Any

import flet as ft

from . import douyin_content_state as content_state


def has_pending_new_work(account: Any) -> bool:
    return content_state.pending_new_work_count_for_account(account) > 0


def account_status_meta(account: Any) -> dict[str, Any]:
    status_text = str(getattr(account, "status", "") or "")
    if "自动暂停" in status_text:
        return {"label": "已暂停", "color": ft.Colors.ERROR, "icon": ft.Icons.PAUSE_CIRCLE}
    if getattr(account, "last_error", "") or "异常" in status_text:
        return {"label": "异常", "color": ft.Colors.ORANGE, "icon": ft.Icons.WARNING_AMBER}
    if has_pending_new_work(account):
        failed = any(content_state.item_status(item) == content_state.DOWNLOAD_FAILED_STATUS for item in getattr(account, "items", []) or [])
        return {"label": "有失败项" if failed else "有新作品", "color": ft.Colors.ERROR if failed else ft.Colors.PRIMARY, "icon": ft.Icons.ERROR_OUTLINE if failed else ft.Icons.NEW_RELEASES}
    if getattr(account, "monitor_enabled", False):
        return {"label": "监控中", "color": ft.Colors.GREEN, "icon": ft.Icons.RADAR}
    return {"label": "未监控", "color": ft.Colors.ON_SURFACE_VARIANT, "icon": ft.Icons.PAUSE_CIRCLE}


def auto_download_policy_label(policy: str) -> str:
    return {
        "none": "不自动下载",
        "video": "只下载视频",
        "gallery": "只下载图集",
        "all": "自动下载全部",
    }.get(str(policy or "none"), "不自动下载")


def account_next_step(account: Any) -> str:
    reason = str(getattr(account, "last_error", "") or getattr(account, "status", "") or "")
    if not reason:
        return ""
    lower = reason.lower()
    if any(word in reason for word in ("Cookie", "登录", "msToken", "a_bogus")) or "cookie" in lower:
        return "下一步：到设置页更新 Cookie / Cookie 池，然后重新检测该账号。"
    if any(word in reason for word in ("风控", "空响应", "验证")) or any(token in lower for token in ("captcha", "verify", "429", "418")):
        return "下一步：降低检测并发和频率，等待冷却后重试；多账号同时失败时先暂停批量任务。"
    if any(word in reason for word in ("主页", "公开作品", "不存在", "不可访问", "无公开")) or any(token in lower for token in ("private", "404")):
        return "下一步：打开主页确认账号是否可访问；如果主页正常，再同步作品列表。"
    if "http" in lower or "timeout" in lower or "proxy" in lower:
        return "下一步：检查网络/代理设置，稍后重试检测。"
    return "下一步：点击“快速检测更新”重试；若仍失败，请导出诊断日志。"
