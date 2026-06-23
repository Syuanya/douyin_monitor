from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import flet as ft

from ...core.runtime.task_center import classify_failure
from ...core.ui_services.issue_center_service import IssueCenterService
from ..base_page import PageBase


class IssueCenterPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "issue_center"
        self.issue_area = ft.Column(controls=[], spacing=8, expand=True)
        self.issue_service = IssueCenterService(app)

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
        return self.issue_service.collect_issues()

    @staticmethod
    def _storage_writable(path: str) -> bool:
        from ...core.ui_services.common import storage_writable

        return storage_writable(path)

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
