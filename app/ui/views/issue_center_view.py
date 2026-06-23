from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import flet as ft

from ...core.runtime.task_center import classify_failure
from ...core.ui_services.issue_center_service import IssueCenterService
from ...core.ui_services.performance_observability_service import PerformanceObservabilityService
from ..base_page import PageBase


class IssueCenterPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "issue_center"
        self.issue_area = ft.Column(controls=[], spacing=8, expand=False)
        self.issue_service = IssueCenterService(app)
        self.performance_observability = PerformanceObservabilityService(app)
        self.risk_control_values: dict[str, bool] = {}
        self.risk_control_buttons: dict[str, ft.TextButton] = {}
        self.risk_control_status_text: ft.Text | None = None
        self.risk_control_summary_text: ft.Text | None = None

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self._title_area(),
                self._risk_control_card(),
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

    def _load_risk_control_values(self) -> dict[str, bool]:
        settings = self.app.services.settings_config
        user_config = dict(getattr(settings, "user_config", {}) or {})
        return {
            "development_bypass_risk_controls_enabled": bool(user_config.get("development_bypass_risk_controls_enabled", False)),
            "global_request_limiter_enabled": bool(user_config.get("global_request_limiter_enabled", True)),
            "cookie_cooldown_enabled": bool(user_config.get("cookie_cooldown_enabled", True)),
            "risk_backoff_enabled": bool(user_config.get("risk_backoff_enabled", True)),
        }

    @staticmethod
    def _toggle_label(label: str, enabled: bool) -> str:
        return f"{'已开启' if enabled else '已关闭'} · {label}"

    @staticmethod
    def _toggle_icon(enabled: bool) -> str:
        return ft.Icons.CHECK_CIRCLE if enabled else ft.Icons.PAUSE_CIRCLE_OUTLINE

    def _make_toggle_button(self, key: str, label: str) -> ft.TextButton:
        enabled = bool(self.risk_control_values.get(key, False))
        # Use TextButton instead of Switch/OutlinedButton. The Windows Flet
        # runtime used by the desktop build has rendered several complex/empty
        # controls as a large gray placeholder on some machines. TextButton is
        # already used widely in stable pages such as download history.
        button = ft.TextButton(
            self._toggle_label(label, enabled),
            icon=self._toggle_icon(enabled),
            on_click=lambda e, item_key=key: self._toggle_risk_control(item_key),
        )
        self.risk_control_buttons[key] = button
        return button

    def _toggle_risk_control(self, key: str) -> None:
        self.risk_control_values[key] = not bool(self.risk_control_values.get(key, False))
        labels = {
            "development_bypass_risk_controls_enabled": "开发模式：跳过冷却/限速/退避",
            "global_request_limiter_enabled": "全局请求限速",
            "cookie_cooldown_enabled": "Cookie 失败冷却",
            "risk_backoff_enabled": "风控退避",
        }
        button = self.risk_control_buttons.get(key)
        if button is not None:
            enabled = bool(self.risk_control_values.get(key, False))
            button.text = self._toggle_label(labels.get(key, key), enabled)
            button.icon = self._toggle_icon(enabled)
            try:
                button.update()
            except Exception:
                pass
        if self.risk_control_status_text is not None:
            self.risk_control_status_text.value = "开关已变更，点击“保存开关”后生效。"
        if self.risk_control_summary_text is not None:
            self.risk_control_summary_text.value = self._risk_control_summary_text(include_pending=True)
        try:
            self.content_area.update()
        except Exception:
            pass

    def _risk_control_card(self) -> ft.Control:
        """Return a conservative, non-expanding control block.

        Do not use Switch, large placeholder containers, or expanding empty
        areas here. Several Windows/Flet combinations render those controls as
        a full-size gray rectangle, which hides the whole page.
        """
        self.risk_control_values = self._load_risk_control_values()
        self.risk_control_buttons = {}
        self.risk_control_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.risk_control_summary_text = ft.Text(self._risk_control_summary_text(), size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        return ft.Column(
            controls=[
                ft.Text("风控与调试开关", weight=ft.FontWeight.BOLD),
                ft.Text("开发阶段可临时跳过冷却、限速和退避；正式批量同步建议恢复开启。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ft.Row(
                    controls=[
                        self._make_toggle_button("development_bypass_risk_controls_enabled", "开发模式：跳过冷却/限速/退避"),
                        self._make_toggle_button("global_request_limiter_enabled", "全局请求限速"),
                        self._make_toggle_button("cookie_cooldown_enabled", "Cookie 失败冷却"),
                        self._make_toggle_button("risk_backoff_enabled", "风控退避"),
                    ],
                    spacing=4,
                    wrap=True,
                ),
                ft.Row(
                    controls=[
                        ft.TextButton("保存开关", icon=ft.Icons.SAVE, on_click=lambda e: self.run_async(self.save_risk_controls())),
                        ft.TextButton("清理 Cookie 冷却", icon=ft.Icons.CLEANING_SERVICES, on_click=lambda e: self.run_async(self.clear_cookie_health_records())),
                    ],
                    spacing=4,
                    wrap=True,
                ),
                self.risk_control_summary_text,
                self.risk_control_status_text,
                ft.Divider(height=1),
            ],
            spacing=6,
            expand=False,
        )

    def _risk_control_summary_text(self, include_pending: bool = False) -> str:
        try:
            limiter = self.performance_observability.rate_limiter_summary()
            cookie = self.performance_observability.cookie_health_summary("douyin")
            if include_pending:
                return (
                    f"待保存：开发跳过={self.risk_control_values.get('development_bypass_risk_controls_enabled', False)}；"
                    f"限速={self.risk_control_values.get('global_request_limiter_enabled', True)}；"
                    f"Cookie 冷却={self.risk_control_values.get('cookie_cooldown_enabled', True)}；"
                    f"风控退避={self.risk_control_values.get('risk_backoff_enabled', True)}。"
                )
            return (
                f"当前：开发跳过={bool(limiter.get('development_bypass', False))}；"
                f"限速={bool(limiter.get('enabled', False))}；"
                f"风控退避={bool(limiter.get('risk_backoff_enabled', False))}；"
                f"Cookie 冷却={cookie.get('cooldown', 0)}；Cookie 降级={cookie.get('degraded', 0)}。"
            )
        except Exception as exc:
            return f"当前状态读取失败：{exc}"

    async def save_risk_controls(self) -> None:
        settings = self.app.services.settings_config
        user_config = dict(getattr(settings, "user_config", {}) or {})
        values = dict(self.risk_control_values or self._load_risk_control_values())
        user_config["development_bypass_risk_controls_enabled"] = bool(values.get("development_bypass_risk_controls_enabled", False))
        user_config["global_request_limiter_enabled"] = bool(values.get("global_request_limiter_enabled", True))
        user_config["cookie_cooldown_enabled"] = bool(values.get("cookie_cooldown_enabled", True))
        user_config["risk_backoff_enabled"] = bool(values.get("risk_backoff_enabled", True))
        settings.adopt_user_config(user_config)
        await self.app.services.config_manager.save_user_config(user_config)
        if self.risk_control_summary_text is not None:
            self.risk_control_summary_text.value = self._risk_control_summary_text()
        if self.risk_control_status_text is not None:
            self.risk_control_status_text.value = "已保存风控与开发调试开关。"
        try:
            self.content_area.update()
        except Exception:
            pass

    async def clear_cookie_health_records(self) -> None:
        cleared = self.performance_observability.clear_cookie_health("douyin")
        if self.risk_control_summary_text is not None:
            self.risk_control_summary_text.value = self._risk_control_summary_text()
        if self.risk_control_status_text is not None:
            self.risk_control_status_text.value = f"已清理 Cookie 健康/冷却记录 {cleared} 条。"
        try:
            self.content_area.update()
        except Exception:
            pass

    async def refresh(self) -> None:
        issues = self._collect_issues()
        self.issue_area.controls.clear()
        if not issues:
            self.issue_area.controls.append(
                ft.Text("暂无需要处理的问题。", color=ft.Colors.ON_SURFACE_VARIANT)
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
