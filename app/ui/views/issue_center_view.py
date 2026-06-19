from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import flet as ft

from ...core.runtime.task_center import classify_failure
from ..base_page import PageBase


class IssueCenterPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "issue_center"
        self.issue_area = ft.Column(controls=[], spacing=8, expand=True)

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self._title_area(),
                self.issue_area,
            ]
        )
        await self.refresh()
        self.content_area.update()

    def _title_area(self) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("问题中心", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.Text("集中查看失败任务、异常账号、配置缺失和存储问题。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    tooltip="刷新问题",
                    on_click=lambda e: self.run_async(self.refresh()),
                    icon_color=ft.Colors.PRIMARY,
                ),
                ft.IconButton(
                    icon=ft.Icons.HEALTH_AND_SAFETY,
                    tooltip="打开诊断",
                    on_click=lambda e: self.run_async(self.go(self.app.diagnostic_health_page.page_name)),
                    icon_color=ft.Colors.PRIMARY,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def refresh(self) -> None:
        issues = self._collect_issues()
        self.issue_area.controls.clear()
        if not issues:
            self.issue_area.controls.append(
                ft.Container(
                    padding=16,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    content=ft.Text("暂无需要处理的问题。", color=ft.Colors.ON_SURFACE_VARIANT),
                )
            )
        else:
            for issue in issues:
                self.issue_area.controls.append(self._issue_card(issue))
        try:
            self.issue_area.update()
        except Exception:
            pass

    def _collect_issues(self) -> list[dict[str, Any]]:
        issues: list[dict[str, Any]] = []
        settings = getattr(self.app.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        douyin_cookie = str(cookies.get("douyin_cookie") or "").strip()
        if not (douyin_cookie and "=" in douyin_cookie and len(douyin_cookie) >= 20):
            issues.append(
                {
                    "level": "高",
                    "title": "抖音 Cookie 未配置或格式异常",
                    "detail": "解析、同步作品和监控主页可能失败。",
                    "next_step": "打开设置页填写完整 Cookie，并点击 Cookie 测试。",
                    "page": self.app.settings_page.page_name,
                }
            )

        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        storage_path = str(user_config.get("douyin_content_download_path") or "").strip()
        if not storage_path:
            storage_path = os.path.join(self.app.run_path, "downloads", "douyin_content")
        if not self._storage_writable(storage_path):
            issues.append(
                {
                    "level": "高",
                    "title": "下载目录不可写",
                    "detail": storage_path,
                    "next_step": "检查目录权限，或在设置页更换保存路径。",
                    "page": self.app.settings_page.page_name,
                }
            )

        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is not None and hasattr(queue, "snapshot"):
            snapshot = queue.snapshot()
            global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
            if global_state.get("paused"):
                issues.append(
                    {
                        "level": "中",
                        "title": "下载队列已暂停",
                        "detail": "后台下载任务不会继续执行。",
                        "next_step": "打开任务中心点击继续下载。",
                        "page": self.app.task_center_page.page_name,
                    }
                )

        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        for account in list(getattr(monitor, "accounts", []) or []):
            reason = str(getattr(account, "last_error", "") or "")
            status = str(getattr(account, "status", "") or "")
            if reason or "异常" in status:
                issues.append(
                    {
                        "level": "中",
                        "title": f"账号异常：{account.display_name or account.douyin_nickname or account.account_id}",
                        "detail": reason or status,
                        "next_step": "打开内容监控页检查账号，必要时更新 Cookie 后重新检测。",
                        "page": self.app.douyin_content.page_name,
                    }
                )

        task_center = getattr(self.app.services, "task_center", None)
        records = task_center.snapshot(200) if task_center is not None and hasattr(task_center, "snapshot") else []
        for record in records:
            if str(record.get("status") or "") != "失败":
                continue
            failure = classify_failure(str(record.get("detail") or ""))
            issues.append(
                {
                    "level": "中",
                    "title": f"任务失败：{record.get('title') or '未命名任务'}",
                    "detail": f"{failure.get('category') or '执行失败'}：{record.get('detail') or '-'}",
                    "next_step": failure.get("next_step") or "打开任务中心查看详情并重试。",
                    "page": self.app.task_center_page.page_name,
                }
            )
        return issues[:100]

    @staticmethod
    def _storage_writable(path: str) -> bool:
        try:
            target = Path(path)
            target.mkdir(parents=True, exist_ok=True)
            return target.exists() and os.access(target, os.W_OK)
        except Exception:
            return False

    def _issue_card(self, issue: dict[str, Any]) -> ft.Control:
        level = str(issue.get("level") or "中")
        color = ft.Colors.ERROR if level == "高" else ft.Colors.ORANGE
        return ft.Container(
            padding=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ERROR_OUTLINE, color=color),
                    ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(str(issue.get("title") or "问题"), weight=ft.FontWeight.BOLD, expand=True),
                                    ft.Container(
                                        content=ft.Text(level, size=11, color=ft.Colors.WHITE),
                                        bgcolor=color,
                                        border_radius=10,
                                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                    ),
                                ],
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            ft.Text(str(issue.get("detail") or "-"), size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                            ft.Text(str(issue.get("next_step") or ""), size=12, color=ft.Colors.PRIMARY),
                        ],
                        spacing=4,
                        expand=True,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.OPEN_IN_NEW,
                        tooltip="去处理",
                        on_click=lambda e, target=str(issue.get("page") or ""): self.run_async(self.go(target)),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.START,
            ),
        )

    async def go(self, page_name: str) -> None:
        if page_name and hasattr(self.app, "switch_page"):
            await self.app.switch_page(page_name)

    async def _await_coro(self, coro) -> None:
        await coro

    def run_async(self, coro) -> None:
        self.page.run_task(self._await_coro, coro)
