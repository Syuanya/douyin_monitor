from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import flet as ft
import httpx

from ...core.media.cookie_utils import cookie_looks_usable, sanitize_cookie_header
from ...core.ui_services.diagnostic_workflow import DiagnosticWorkflow
from ...utils.logger import logger
from ..base_page import PageBase


@dataclass(slots=True)
class HealthCheckResult:
    name: str
    status: str
    detail: str
    next_step: str = ""


HealthChecker = Callable[[], Awaitable[HealthCheckResult]]


class DiagnosticHealthPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "diagnostic_health"
        self.results: list[HealthCheckResult] = []
        self.running = False
        self.result_area = ft.Column(controls=[], spacing=8, expand=True, scroll=ft.ScrollMode.AUTO)
        self.loading_indicator = ft.ProgressRing(width=22, height=22, stroke_width=3, visible=False)
        self.run_button = ft.FilledButton("一键检测", icon=ft.Icons.HEALTH_AND_SAFETY, on_click=lambda e: self.run_async(self.run_checks()))
        self.workflow = DiagnosticWorkflow(app)

    async def load(self) -> None:
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self.create_title_area(),
                ft.Container(content=self.result_area, expand=True),
            ]
        )
        self.render_results()
        self.content_area.update()

    def create_title_area(self) -> ft.Row:
        return ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("诊断与健康检查", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                    ],
                    spacing=2,
                ),
                ft.IconButton(
                    icon=ft.Icons.INFO_OUTLINE,
                    tooltip="检测运行环境、依赖、Cookie、网络、抖音访问、解析器、下载策略、队列和保存目录权限。",
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.Container(expand=True),
                self.loading_indicator,
                self.run_button,
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    async def run_checks(self) -> None:
        if self.running:
            return
        self.running = True
        self.results = []
        await self.set_loading(True)
        self.render_results()
        for checker in self.checkers():
            try:
                self.results.append(await checker())
            except Exception as exc:
                logger.debug(f"health check failed unexpectedly: {exc}")
                self.results.append(HealthCheckResult("未知检测", "异常", str(exc), "请导出诊断包后查看日志。"))
            self.render_results()
        self.running = False
        await self.set_loading(False)
        await self.app.snack_bar.show_snack_bar("健康检查完成", bgcolor=ft.Colors.PRIMARY)

    def checkers(self) -> list[HealthChecker]:
        return [
            self.check_python_runtime,
            self.check_dependencies,
            self.check_sqlite,
            self.check_disk_space,
            self.check_cookie,
            self.check_network,
            self.check_proxy,
            self.check_douyin_access,
            self.check_parser,
            self.check_parser_backend,
            self.check_parser_registry,
            self.check_parser_latency,
            self.check_download_strategy,
            self.check_cookie_health_observability,
            self.check_rate_limiter_observability,
            self.check_batch_jobs,
            self.check_segmented_download,
            self.check_storage_permission,
            self.check_temp_residue,
            self.check_task_queue,
        ]

    async def check_python_runtime(self) -> HealthCheckResult:
        return await self.workflow.check_python_runtime()

    async def check_dependencies(self) -> HealthCheckResult:
        return await self.workflow.check_dependencies()

    async def check_sqlite(self) -> HealthCheckResult:
        return await self.workflow.check_sqlite()

    async def check_disk_space(self) -> HealthCheckResult:
        # Delegated implementation uses shutil.disk_usage.
        return await self.workflow.check_disk_space()

    async def check_cookie(self) -> HealthCheckResult:
        return await self.workflow.check_cookie()

    @staticmethod
    def _looks_like_cookie(value: str) -> bool:
        return cookie_looks_usable(value)

    async def check_network(self) -> HealthCheckResult:
        return await self.workflow.check_network()

    async def check_proxy(self) -> HealthCheckResult:
        return await self.workflow.check_proxy()

    async def check_douyin_access(self) -> HealthCheckResult:
        return await self.workflow.check_douyin_access()

    async def check_parser(self) -> HealthCheckResult:
        return await self.workflow.check_parser()

    async def check_parser_backend(self) -> HealthCheckResult:
        return await self.workflow.check_parser_backend()

    async def check_parser_registry(self) -> HealthCheckResult:
        return await self.workflow.check_parser_registry()

    async def check_parser_latency(self) -> HealthCheckResult:
        return await self.workflow.check_parser_latency()

    async def check_download_strategy(self) -> HealthCheckResult:
        return await self.workflow.check_download_strategy()

    @staticmethod
    def _safe_int_config(config: dict, key: str, default: int, minimum: int, maximum: int) -> int:
        return DiagnosticWorkflow.safe_int_config(config, key, default, minimum, maximum)


    async def check_cookie_health_observability(self) -> HealthCheckResult:
        return await self.workflow.check_cookie_health_observability()

    async def check_rate_limiter_observability(self) -> HealthCheckResult:
        return await self.workflow.check_rate_limiter_observability()

    async def check_batch_jobs(self) -> HealthCheckResult:
        return await self.workflow.check_batch_jobs()

    async def check_segmented_download(self) -> HealthCheckResult:
        return await self.workflow.check_segmented_download()

    async def check_storage_permission(self) -> HealthCheckResult:
        return await self.workflow.check_storage_permission()

    async def check_temp_residue(self) -> HealthCheckResult:
        return await self.workflow.check_temp_residue()

    async def check_task_queue(self) -> HealthCheckResult:
        return await self.workflow.check_task_queue()

    def storage_dir(self) -> str:
        return self.workflow.storage_dir()

    def proxy_url(self) -> str | None:
        return self.workflow.proxy_url()

    async def set_loading(self, value: bool) -> None:
        self.loading_indicator.visible = value
        self.run_button.disabled = value
        try:
            self.content_area.update()
        except Exception:
            pass

    def render_results(self) -> None:
        self.result_area.controls.clear()
        if not self.results:
            self.result_area.controls.append(
                ft.Container(
                    padding=16,
                    content=ft.Text("点击“一键检测”开始检查。", size=13, color=ft.Colors.ON_SURFACE_VARIANT),
                )
            )
        for result in self.results:
            self.result_area.controls.append(self.create_result_card(result))
        try:
            self.result_area.update()
        except Exception:
            pass

    def create_result_card(self, result: HealthCheckResult) -> ft.Container:
        color = {
            "正常": ft.Colors.GREEN,
            "可用": ft.Colors.PRIMARY,
            "需配置": ft.Colors.ORANGE,
            "异常": ft.Colors.ERROR,
        }.get(result.status, ft.Colors.ON_SURFACE_VARIANT)
        lines: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Text(result.name, weight=ft.FontWeight.BOLD, expand=True),
                    ft.Container(
                        bgcolor=color,
                        border_radius=6,
                        padding=ft.Padding.only(left=8, top=3, right=8, bottom=3),
                        content=ft.Text(result.status, size=12, color=ft.Colors.WHITE),
                    ),
                ]
            ),
            ft.Text(result.detail, selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if result.next_step:
            lines.append(ft.Text(result.next_step, selectable=True, size=12, color=ft.Colors.PRIMARY))
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=12,
            content=ft.Column(controls=lines, spacing=6),
        )

    async def _await_coro(self, coro) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Diagnostic health UI task failed: {exc}")
            await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR)

    def run_async(self, coro) -> None:
        self.page.run_task(self._await_coro, coro)
