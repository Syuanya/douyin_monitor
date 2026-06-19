from __future__ import annotations

from typing import Any

import flet as ft


def account_status_meta(account: Any) -> dict[str, Any]:
    if getattr(account, "last_error", "") or "异常" in str(getattr(account, "status", "")):
        return {"label": "异常", "color": ft.Colors.ORANGE, "icon": ft.Icons.WARNING_AMBER}
    if getattr(account, "last_new_count", 0):
        return {"label": "有新作品", "color": ft.Colors.PRIMARY, "icon": ft.Icons.NEW_RELEASES}
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
    if any(word in reason for word in ("Cookie", "登录", "风控", "未识别", "公开作品")):
        return "下一步：检查 Cookie 是否有效，确认主页公开可访问，然后点击“检测一次”。"
    if "HTTP" in reason:
        return "下一步：检查网络/代理设置，稍后重试检测。"
    return "下一步：点击“检测一次”重试；若仍失败，请导出诊断日志。"
