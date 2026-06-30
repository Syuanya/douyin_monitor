from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()  # type: ignore[assignment]

from ...core.diagnostics.diagnostic_tools import export_diagnostic_bundle


class DouyinContentExportController:
    """Export, diagnostics and local-folder actions for content monitor UI."""

    WORK_EXPORT_COLUMNS = [
        "账号备注",
        "抖音昵称",
        "分组",
        "主页链接",
        "监控状态",
        "通知",
        "自动下载",
        "最近检测",
        "最近成功",
        "账号状态",
        "错误原因",
        "作品ID",
        "作品标题",
        "作品类型",
        "作品状态",
        "发布时间",
        "首次发现",
        "作品链接",
    ]

    ACCOUNT_EXPORT_COLUMNS = [
        "账号ID",
        "备注名称",
        "抖音昵称",
        "分组",
        "主页链接",
        "监控状态",
        "账号状态",
        "通知",
        "自动下载",
        "检测间隔分钟",
        "失败暂停次数",
        "保留最近作品数",
        "最近检测",
        "最近成功",
        "最近新增",
        "累计新增",
        "作品数",
        "资料作品数",
        "错误次数",
        "最近错误",
    ]

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def export_dir(self) -> str:
        return os.path.join(self.owner.app.run_path, "downloads", "monitor_exports")

    def make_path(self, prefix: str) -> str:
        os.makedirs(self.export_dir(), exist_ok=True)
        return os.path.join(self.export_dir(), f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")

    def work_rows(self) -> list[list[Any]]:
        rows: list[list[Any]] = []
        owner = self.owner
        for account in owner.manager.accounts:
            items = [item for item in getattr(account, "items", []) if getattr(item, "status", "") != "count_only"] or [None]
            for item in items:
                rows.append(
                    [
                        getattr(account, "display_name", ""),
                        getattr(account, "douyin_nickname", ""),
                        getattr(account, "group_name", ""),
                        getattr(account, "homepage_url", ""),
                        "监控中" if getattr(account, "monitor_enabled", False) else "未监控",
                        "开启" if getattr(account, "notify_enabled", False) else "关闭",
                        owner._auto_download_policy_label(getattr(account, "auto_download_policy", "none")),
                        getattr(account, "last_check_time", ""),
                        getattr(account, "last_success_time", ""),
                        getattr(account, "status", ""),
                        getattr(account, "last_error", ""),
                        getattr(item, "item_id", "") if item else "",
                        getattr(item, "title", "") if item else "",
                        "图集" if item and owner._is_gallery_item(item) else ("视频" if item else ""),
                        getattr(item, "status", "") if item else "",
                        getattr(item, "publish_time", "") if item else "",
                        getattr(item, "first_seen_time", "") if item else "",
                        getattr(item, "share_url", "") if item else "",
                    ]
                )
        return rows

    def account_rows(self) -> list[list[Any]]:
        rows: list[list[Any]] = []
        owner = self.owner
        for account in owner.manager.accounts:
            items = [item for item in getattr(account, "items", []) if getattr(item, "status", "") != "count_only"]
            rows.append(
                [
                    getattr(account, "account_id", ""),
                    getattr(account, "display_name", ""),
                    getattr(account, "douyin_nickname", ""),
                    getattr(account, "group_name", ""),
                    getattr(account, "homepage_url", ""),
                    "监控中" if getattr(account, "monitor_enabled", False) else "未监控",
                    getattr(account, "status", ""),
                    "开启" if getattr(account, "notify_enabled", False) else "关闭",
                    owner._auto_download_policy_label(getattr(account, "auto_download_policy", "none")),
                    getattr(account, "monitor_interval_minutes", 0) or "全局",
                    getattr(account, "auto_pause_failures", 0),
                    getattr(account, "keep_recent_count", 0) or "不限",
                    getattr(account, "last_check_time", ""),
                    getattr(account, "last_success_time", ""),
                    getattr(account, "last_new_count", 0),
                    getattr(account, "total_new_count", 0),
                    len(items),
                    getattr(account, "aweme_count", -1) if getattr(account, "aweme_count", -1) >= 0 else "",
                    getattr(account, "error_count", 0),
                    getattr(account, "last_error", ""),
                ]
            )
        return rows

    @staticmethod
    def write_csv(path: str, columns: list[str], rows: list[list[Any]]) -> None:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(columns)
            writer.writerows(rows)

    async def open_export_dir(self) -> None:
        path = self.export_dir()
        os.makedirs(path, exist_ok=True)
        await self.owner.open_path_or_url(path, success="已打开导出目录")

    async def export_works_csv(self) -> str:
        path = self.make_path("douyin_monitor_export")
        self.write_csv(path, self.WORK_EXPORT_COLUMNS, self.work_rows())
        await self.owner.app.snack_bar.show_snack_bar(f"已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)
        return path

    async def export_accounts_csv(self) -> str:
        path = self.make_path("douyin_monitor_accounts")
        self.write_csv(path, self.ACCOUNT_EXPORT_COLUMNS, self.account_rows())
        await self.owner.app.snack_bar.show_snack_bar(f"监控用户已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)
        return path

    async def export_diagnostics(self) -> str | None:
        try:
            path = export_diagnostic_bundle(self.owner.app.services)
            await self.owner.app.snack_bar.show_snack_bar(
                self.owner._.get("export_success", "诊断包已导出：{path}").format(path=path),
                bgcolor=ft.Colors.PRIMARY,
                duration=5000,
                show_close_icon=True,
            )
            return path
        except Exception as exc:
            await self.owner.app.snack_bar.show_snack_bar(f"{self.owner._.get('export_failed', '导出失败')}：{exc}", bgcolor=ft.Colors.ERROR)
            return None

    async def open_log_dir(self) -> None:
        log_dir = os.path.join(self.owner.app.services.run_path, "logs")
        os.makedirs(log_dir, exist_ok=True)
        await self.owner.open_path_or_url(log_dir, failed_prefix=self.owner._.get("open_failed", "打开失败"))
