from __future__ import annotations

import inspect
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

from ..base_page import PageBase
from ..components.common.safe_icons import icon
from ...utils.logger import logger
from ...core.ui_services.home_dashboard_service import HomeDashboardService


class HomeDashboardPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "home_dashboard"
        self.refreshing = False
        self.dashboard_service = HomeDashboardService(app)

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        self.content_area.controls.clear()
        self.content_area.controls.extend(self._build())
        self.content_area.update()

    def _build(self) -> list[ft.Control]:
        stats = self._stats()
        return [
            self._hero(stats),
            self._metric_area(stats),
            self._quick_start_area(stats),
            self._feature_monitor_area(stats),
            self._common_actions_area(),
        ]

    def _hero(self, stats: dict[str, Any]) -> ft.Control:
        status_text = "系统可用"
        status_color = ft.Colors.GREEN
        if stats["failed_tasks"] or stats["error_accounts"]:
            status_text = "需要关注"
            status_color = ft.Colors.ORANGE
        if not stats["cookie_ready"]:
            status_text = "需配置 Cookie"
            status_color = ft.Colors.ERROR
        return ft.Container(
            padding=18,
            border_radius=8,
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text("Douyin Monitor 主页", theme_style=ft.TextThemeStyle.HEADLINE_SMALL),
                            ft.Text(
                                "从这里开始添加监控用户、解析作品、查看任务和检查功能状态。",
                                size=13,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    self._status_pill(status_text, status_color),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="刷新主页状态",
                        on_click=lambda e: self.run_async(self.refresh_dashboard()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _metric_area(self, stats: dict[str, Any]) -> ft.Control:
        return ft.Row(
            controls=[
                self._metric("监控账号", str(stats["accounts"]), "监控中 {running} / 异常 {errors}".format(running=stats["running_accounts"], errors=stats["error_accounts"]), "GROUP"),
                self._metric("作品资料", str(stats["works"]), "新作品 {new} 个 / 今日下载 {today}".format(new=stats["new_works"], today=stats["today_downloads"]), "VIDEO_LIBRARY"),
                self._metric("任务状态", str(stats["tasks"]), "运行 {running} / 失败率 {rate}".format(running=stats["running_tasks"], rate=stats["failure_rate"]), "TASK_ALT"),
                self._metric("下载队列", str(stats["queue_running"]), "等待 {waiting} / 全局并发 {limit}".format(waiting=stats["queue_waiting"], limit=stats["queue_limit"]), "DOWNLOADING"),
                self._metric("磁盘空间", stats["disk_free"], "总容量 {total}".format(total=stats["disk_total"]), "STORAGE"),
            ],
            spacing=10,
            wrap=True,
        )

    def _quick_start_area(self, stats: dict[str, Any]) -> ft.Control:
        steps = [
            ("1", "配置 Cookie", "设置页填写抖音 Cookie，解析和监控更稳定。", self.app.settings_page.page_name, "SETTINGS", not stats["cookie_ready"]),
            ("2", "添加监控用户", "粘贴抖音主页链接；备注为空时会自动填充抖音昵称。", self.app.douyin_content.page_name, "PERSON_ADD", stats["accounts"] == 0),
            ("3", "同步作品", "进入内容监控页，点击同步作品或检测一次建立基线。", self.app.douyin_content.page_name, "CLOUD_SYNC", stats["accounts"] > 0 and stats["works"] == 0),
            ("4", "查看任务和下载", "任务中心显示下载、解析、失败原因和重试入口。", self.app.task_center_page.page_name, "TASK_ALT", False),
        ]
        return ft.Container(
            padding=14,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Column(
                controls=[
                    self._section_title("快速开始", "新用户按这几步即可完成基础配置和监控。"),
                    ft.Row(
                        controls=[self._guide_step(*step) for step in steps],
                        spacing=10,
                        wrap=True,
                    ),
                ],
                spacing=12,
            ),
        )

    def _feature_monitor_area(self, stats: dict[str, Any]) -> ft.Control:
        checks = [
            self._feature_state("内容监控", "正常" if stats["accounts"] else "待添加", f"账号 {stats['accounts']}，监控中 {stats['running_accounts']}", stats["accounts"] > 0, self.app.douyin_content.page_name),
            self._feature_state("视频解析", "可用" if stats["parser_ready"] else "需检查", f"并发 {stats['parse_concurrency']}，Cookie {'已配置' if stats['cookie_ready'] else '未配置'}", stats["parser_ready"], self.app.video_parse.page_name),
            self._feature_state("任务队列", "正常" if not stats["queue_paused"] else "已暂停", f"运行 {stats['queue_running']}，等待 {stats['queue_waiting']}；{stats['queue_active_text']}", not stats["queue_paused"], self.app.task_center_page.page_name),
            self._feature_state("存储目录", "正常" if stats["storage_ready"] else "需配置", stats["storage_path"], stats["storage_ready"], self.app.storage_page.page_name),
            self._feature_state("异常任务", "正常" if not stats["failed_tasks"] else "有失败", f"失败 {stats['failed_tasks']} 个，今日失败 {stats['today_failed_tasks']} 个", not stats["failed_tasks"], self.app.task_center_page.page_name),
            self._feature_state("账号异常", "正常" if not stats["error_accounts"] else "有异常", f"异常 {stats['error_accounts']} 个", not stats["error_accounts"], self.app.douyin_content.page_name),
        ]
        return ft.Container(
            padding=14,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Column(
                controls=[
                    self._section_title("功能监测", "这里只做本地状态检测，不发起网络请求。完整检测请进入诊断页。"),
                    ft.Row(controls=checks, spacing=10, wrap=True),
                ],
                spacing=12,
            ),
        )

    def _common_actions_area(self) -> ft.Control:
        return ft.Container(
            padding=14,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Column(
                controls=[
                    self._section_title("常用入口", "按使用场景直接进入对应功能。"),
                    ft.Row(
                        controls=[
                            self._action_button("添加监控用户", "PERSON_ADD", self.app.douyin_content.page_name),
                            self._action_button("解析作品链接", "TRAVEL_EXPLORE", self.app.video_parse.page_name),
                            self._action_button("任务中心", "TASK_ALT", self.app.task_center_page.page_name),
                            self._action_button("问题中心", "ERROR_OUTLINE", self.app.issue_center_page.page_name),
                            self._action_button("一键诊断", "HEALTH_AND_SAFETY", self.app.diagnostic_health_page.page_name),
                            self._action_button("打开存储", "FOLDER_OPEN", self.app.storage_page.page_name),
                            self._action_button("设置 Cookie", "COOKIE", self.app.settings_page.page_name),
                        ],
                        spacing=10,
                        wrap=True,
                    ),
                    ft.Text(
                        "提示：如果解析失败，优先检查 Cookie、代理和任务中心失败原因；如果下载慢，降低并发或暂停后台自动下载。",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                spacing=12,
            ),
        )

    def _stats(self) -> dict[str, Any]:
        # Decoupled service owns today_downloads, failure_rate, disk_free,
        # queue_running_labels and queue_waiting_labels calculations.
        return self.dashboard_service.stats()

    @staticmethod
    def _task_time(task: dict[str, Any]) -> str:
        return HomeDashboardService.task_time(task)

    @classmethod
    def _disk_usage_text(cls, path: str) -> tuple[str, str]:
        return HomeDashboardService.disk_usage_text(path)

    @staticmethod
    def _format_bytes(value: int) -> str:
        from ...core.ui_services.common import format_bytes

        return format_bytes(value)

    @staticmethod
    def _storage_ready(path: str) -> bool:
        from ...core.ui_services.common import storage_writable

        return storage_writable(path)

    def _metric(self, title: str, value: str, detail: str, icon_name: str) -> ft.Control:
        return ft.Container(
            width=230,
            padding=14,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(icon(icon_name, "INFO_OUTLINE"), size=28, color=ft.Colors.PRIMARY),
                    ft.Column(
                        controls=[
                            ft.Text(title, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(value, size=24, weight=ft.FontWeight.BOLD),
                            ft.Text(detail, size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=1,
                    ),
                ],
                spacing=10,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _guide_step(self, number: str, title: str, detail: str, page_name: str, icon_name: str, highlighted: bool) -> ft.Control:
        border_color = ft.Colors.PRIMARY if highlighted else ft.Colors.OUTLINE_VARIANT
        return ft.Container(
            width=260,
            padding=12,
            border=ft.Border.all(1.5 if highlighted else 1, border_color),
            border_radius=8,
            bgcolor=ft.Colors.PRIMARY_CONTAINER if highlighted else None,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self._number_badge(number),
                            ft.Icon(icon(icon_name, "INFO_OUTLINE"), color=ft.Colors.PRIMARY),
                            ft.Text(title, weight=ft.FontWeight.BOLD, expand=True),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(detail, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.TextButton("去处理", icon=ft.Icons.ARROW_FORWARD, on_click=lambda e, target=page_name: self.run_async(self.go(target))),
                ],
                spacing=8,
            ),
        )

    def _feature_state(self, title: str, status: str, detail: str, ok: bool, page_name: str) -> ft.Control:
        color = ft.Colors.GREEN if ok else ft.Colors.ORANGE
        return ft.Container(
            width=300,
            padding=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_CIRCLE if ok else ft.Icons.ERROR_OUTLINE, color=color),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(title, weight=ft.FontWeight.BOLD),
                                    self._status_pill(status, color),
                                ],
                                spacing=8,
                            ),
                            ft.Text(detail, size=12, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.OPEN_IN_NEW,
                        tooltip="打开相关功能",
                        on_click=lambda e, target=page_name: self.run_async(self.go(target)),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _action_button(self, label: str, icon_name: str, page_name: str) -> ft.Control:
        return ft.FilledTonalButton(
            label,
            icon=icon(icon_name, "INFO_OUTLINE"),
            on_click=lambda e, target=page_name: self.run_async(self.go(target)),
        )

    @staticmethod
    def _section_title(title: str, subtitle: str) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                ft.Text(subtitle, size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True),
            ],
            vertical_alignment=ft.CrossAxisAlignment.END,
        )

    @staticmethod
    def _status_pill(label: str, color: str) -> ft.Control:
        return ft.Container(
            content=ft.Text(label, size=11, color=ft.Colors.WHITE),
            bgcolor=color,
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        )

    @staticmethod
    def _number_badge(value: str) -> ft.Control:
        return ft.Container(
            content=ft.Text(value, size=12, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            width=24,
            height=24,
            alignment=ft.Alignment(0, 0),
            bgcolor=ft.Colors.PRIMARY,
            border_radius=12,
        )

    async def refresh_dashboard(self) -> None:
        if self.refreshing:
            return
        self.refreshing = True
        try:
            await self.load()
            await self.app.snack_bar.show_snack_bar("主页状态已刷新", bgcolor=ft.Colors.PRIMARY)
        finally:
            self.refreshing = False

    async def go(self, page_name: str) -> None:
        result = self.app.switch_page(page_name)
        if inspect.isawaitable(result):
            await result

    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Home dashboard task failed: {exc}")
            await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR)

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
