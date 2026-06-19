from __future__ import annotations

import asyncio
import csv
import inspect
import os
import re
import time
from datetime import datetime
from typing import Any

import flet as ft

from ...core.diagnostics.diagnostic_tools import export_diagnostic_bundle
from ...core.content_monitor.douyin_content_monitor import DouyinMonitorAccount
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.business.image_preview_dialog import ImagePreviewDialog
from ..components.business.video_player import VideoPlayer
from ..components.common.safe_icons import icon
from .douyin_content_account_card import build_account_card
from .douyin_content_bulk_components import BatchImportControls, build_batch_import_dialog, build_work_bulk_action_rows
from .douyin_content_item_cards import build_history_item_card, build_inbox_item_card, build_work_status_chip
from .douyin_content_presenter import account_next_step, account_status_meta, auto_download_policy_label


class DouyinContentMonitorPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "douyin_content"
        self.app.language_manager.add_observer(self)
        self.load_language()
        self.url_input: ft.TextField | None = None
        self.name_input: ft.TextField | None = None
        self.cards_area: ft.Column | None = None
        self.history_area: ft.GridView | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.selected_account_id: str | None = None
        self.view_mode = "accounts"
        self.account_select_mode = False
        self.selected_account_ids: set[str] = set()
        self.account_search_query = ""
        self.account_filter = "all"
        self.account_group_filter = "all"
        self.return_account_anchor_id: str | None = None
        self.pending_account_scroll_anchor_id: str | None = None
        self.account_scroll_anchor_hold_until = 0.0
        self.work_select_mode = False
        self.selected_work_ids: set[str] = set()
        self.work_filter = "all"
        self.visible_work_count = 12
        self.work_page_size = 12
        self.download_in_progress = False
        self.download_stop_requested = False
        self.download_progress_text = ""
        self.download_failure_reasons: list[str] = []
        self.batch_result_lines: list[str] = []
        self.batch_job_running = False
        self.batch_cancel_requested = False
        self.image_preview = ImagePreviewDialog(app, "作品图集")
        self.recent_deleted_accounts: list[dict[str, Any]] = []
        self.deleted_account_batches: list[list[dict[str, Any]]] = []
        self._subscribed = False
        self.init()

    @property
    def manager(self):
        return self.app.services.douyin_content_monitor

    def load_language(self):
        language = self.app.language_manager.language
        for key in ("douyin_content_page", "base"):
            self._.update(language.get(key, {}))

    def init(self):
        self.url_input = ft.TextField(
            label=self._.get("profile_url", "抖音主页链接"),
            hint_text="https://www.douyin.com/user/...",
            expand=True,
            dense=True,
            on_submit=self.add_account_on_click,
        )
        self.name_input = ft.TextField(
            label=self._.get("display_name", "备注名称"),
            width=180,
            dense=True,
            on_submit=self.add_account_on_click,
        )
        self.cards_area = ft.Column(
            controls=[],
            spacing=8,
            expand=True,
            scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.history_area = ft.GridView(
            controls=[],
            expand=True,
            max_extent=260,
            spacing=10,
            run_spacing=10,
            child_aspect_ratio=0.62,
            build_controls_on_demand=True,
        )
        self.loading_indicator = ft.ProgressRing(width=24, height=24, stroke_width=3, visible=False)
        if not self._subscribed:
            self.app.page.pubsub.subscribe_topic("douyin_monitor_update", self.subscribe_update)
            self._subscribed = True

    async def load(self):
        self.content_area.scroll = None
        await self.render_current_view()

    def _is_active_page(self) -> bool:
        return self.is_active_page()

    async def render_current_view(self):
        if not self._is_active_page():
            return
        self.content_area.controls.clear()
        if self.view_mode == "works":
            self.content_area.controls.extend(
                [
                    self.create_works_title_area(),
                    self.create_works_area(),
                ]
            )
        elif self.view_mode == "inbox":
            self.content_area.controls.extend(
                [
                    self.create_inbox_title_area(),
                    self.create_works_area(),
                ]
            )
        else:
            self.content_area.controls.extend(
                [
                    self.create_title_area(),
                    self.create_main_area(),
                ]
            )
        await self.refresh_view()
        updated = self.safe_content_update()
        if updated and self.view_mode == "accounts":
            await self.restore_pending_account_scroll_position()

    async def load_legacy(self):
        self.content_area.controls.extend(
            [
                self.create_title_area(),
                self.create_add_area(),
                self.create_main_area(),
            ]
        )
        await self.refresh_view()
        self.safe_content_update()

    def create_title_area(self):
        batch_controls = []
        if not self.account_select_mode:
            batch_controls.append(
                ft.TextButton(
                    "批量选择",
                    icon=ft.Icons.CHECKLIST,
                    on_click=lambda e: self.run_async(self.toggle_account_select_mode()),
                )
            )
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text(self._.get("title", "抖音内容监控"), theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            tooltip=self._.get("subtitle", "低频检测公开主页作品更新"),
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        *batch_controls,
                        ft.Container(expand=True),
                        self.loading_indicator,
                        ft.IconButton(
                            icon=ft.Icons.STOP_CIRCLE,
                            tooltip="取消当前批量检测/同步",
                            disabled=not self.batch_job_running,
                            on_click=lambda e: self.run_async(self.cancel_batch_job()),
                            icon_color=ft.Colors.ERROR,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.SEARCH,
                            tooltip="搜索监控用户",
                            on_click=lambda e: self.run_async(self.search_accounts_on_click()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.INBOX,
                            tooltip="新作品收件箱",
                            on_click=lambda e: self.run_async(self.open_new_work_inbox()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.ADD,
                            tooltip="添加监控用户",
                            on_click=lambda e: self.run_async(self.show_add_account_dialog()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CHECKLIST,
                            tooltip="批量导入账号",
                            on_click=lambda e: self.run_async(self.show_batch_import_dialog()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip=self._.get("refresh", "刷新"),
                            on_click=self.refresh_on_click,
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.BUG_REPORT_OUTLINED,
                            tooltip=self._.get("export_diagnostics", "导出诊断包"),
                            on_click=self.export_diagnostics_on_click,
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip=self._.get("open_log_dir", "打开日志目录"),
                            on_click=self.open_log_dir_on_click,
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.RESTORE,
                            tooltip="恢复最近删除的账号",
                            visible=bool(self.recent_deleted_accounts or self.deleted_account_batches),
                            on_click=lambda e: self.run_async(self.restore_recent_deleted_accounts()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                    ],
                    alignment=ft.MainAxisAlignment.START,
                ),
                ft.Row(
                    controls=[
                        self._monitor_summary_chip(),
                        *self._account_filter_buttons(),
                        ft.IconButton(
                            icon=ft.Icons.REFRESH,
                            tooltip="检测全部监控",
                            on_click=lambda e: self.run_async(self.check_all_enabled_on_click()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLOUD_SYNC,
                            tooltip="同步全部作品",
                            on_click=lambda e: self.run_async(self.sync_all_accounts_on_click()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD,
                            tooltip="导出作品明细CSV",
                            on_click=lambda e: self.run_async(self.export_monitor_csv()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.GROUP,
                            tooltip="导出监控用户CSV",
                            on_click=lambda e: self.run_async(self.export_monitor_accounts_csv()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="打开导出目录",
                            on_click=lambda e: self.run_async(self.open_monitor_export_dir()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.LIST_ALT,
                            tooltip="查看最近批量结果",
                            disabled=not self.batch_result_lines,
                            on_click=lambda e: self.run_async(self.show_batch_result_dialog()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                    ],
                    spacing=8,
                    wrap=True,
                ),
                self._account_group_filter_area(),
                *([self._batch_account_toolbar()] if self.account_select_mode else []),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _monitor_summary_chip(self) -> ft.Container:
        accounts = list(self.manager.accounts)
        enabled = len([account for account in accounts if account.monitor_enabled])
        new_count = len([account for account in accounts if account.last_new_count])
        error_count = len([account for account in accounts if account.last_error or "异常" in str(account.status)])
        works = sum(len(account.items) for account in accounts)
        return ft.Container(
            content=ft.Text(
                f"账号 {len(accounts)} / 监控 {enabled} / 新作品 {new_count} / 异常 {error_count} / 作品 {works}",
                size=12,
                color=ft.Colors.PRIMARY,
            ),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=16,
        )

    def _account_filter_buttons(self) -> list[ft.Control]:
        options = [
            ("all", "全部"),
            ("enabled", "监控中"),
            ("new", "有新作品"),
            ("error", "异常"),
            ("stopped", "未监控"),
        ]
        return [
            ft.TextButton(
                label,
                icon=ft.Icons.CHECK if self.account_filter == key else None,
                disabled=self.account_filter == key,
                on_click=lambda e, mode=key: self.run_async(self.set_account_filter(mode)),
            )
            for key, label in options
        ]

    def _account_group_filter_area(self) -> ft.Row:
        groups = sorted({str(account.group_name or "").strip() for account in self.manager.accounts if str(account.group_name or "").strip()})
        options = [("all", "全部分组"), ("__ungrouped__", "未分组")]
        options.extend((group, group) for group in groups[:10])
        controls: list[ft.Control] = [
            ft.Text("分组：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            *[
                ft.TextButton(
                    label,
                    icon=ft.Icons.CHECK if self.account_group_filter == key else None,
                    disabled=self.account_group_filter == key,
                    on_click=lambda e, group=key: self.run_async(self.set_account_group_filter(group)),
                )
                for key, label in options
            ],
        ]
        if len(groups) > 10:
            controls.append(ft.Text(f"+{len(groups) - 10}", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        return ft.Row(controls=controls, spacing=6, wrap=True)

    def _batch_account_toolbar(self) -> ft.Container:
        visible_accounts = self._visible_accounts()
        visible_ids = {account.account_id for account in visible_accounts}
        selected_visible = len(self.selected_account_ids & visible_ids)
        selected_total = len(self.selected_account_ids)
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            content=ft.Row(
                controls=[
                    ft.Text(f"批量模式：当前列表已选 {selected_visible}/{len(visible_accounts)}，总已选 {selected_total}", size=12, color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.SELECT_ALL, tooltip="全选当前列表", on_click=lambda e: self.run_async(self.select_all_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.CHECKLIST, tooltip="反选当前列表", on_click=lambda e: self.run_async(self.invert_visible_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.CLEAR, tooltip="清空选择", disabled=not selected_total, on_click=lambda e: self.run_async(self.clear_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.REFRESH, tooltip="检测选中", disabled=not selected_total, on_click=lambda e: self.run_async(self.check_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.CLOUD_SYNC, tooltip="同步选中", disabled=not selected_total, on_click=lambda e: self.run_async(self.sync_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="批量设置", disabled=not selected_total, on_click=lambda e: self.run_async(self.show_batch_account_settings_dialog()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="开始监控", disabled=not selected_total, on_click=lambda e: self.run_async(self.start_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.STOP, tooltip="停止监控", disabled=not selected_total, on_click=lambda e: self.run_async(self.stop_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="删除选中", disabled=not selected_total, on_click=lambda e: self.run_async(self.delete_selected_accounts()), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.CLOSE, tooltip="退出批量选择", on_click=lambda e: self.run_async(self.toggle_account_select_mode()), icon_color=ft.Colors.PRIMARY),
                ],
                spacing=6,
                wrap=True,
            ),
        )

    def account_status_meta(self, account: DouyinMonitorAccount) -> dict[str, Any]:
        return account_status_meta(account)

    @staticmethod
    def _auto_download_policy_label(policy: str) -> str:
        return auto_download_policy_label(policy)

    @staticmethod
    def account_next_step(account: DouyinMonitorAccount) -> str:
        return account_next_step(account)

    def show_confirm_dialog(self, title: str, message: str, on_confirm) -> None:
        dialog_ref: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def close_dialog(_=None):
            dialog = dialog_ref.get("dialog")
            if dialog is not None:
                dialog.open = False
            self.app.dialog_area.update()

        async def confirm(_=None):
            close_dialog()
            await on_confirm()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton(self._.get("cancel", "取消"), icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.FilledButton(self._.get("confirm", "确认"), icon=ft.Icons.CHECK, on_click=lambda e: self.run_async(confirm())),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    def create_works_title_area(self):
        account = self.manager.find_account(self.selected_account_id) if self.selected_account_id else None
        title = account.display_name or account.douyin_nickname or account.homepage_url if account else "作品浏览"
        has_selected = bool(self.selected_work_ids)
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            tooltip="返回",
                            on_click=lambda e: self.run_async(self.back_to_accounts()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM, expand=True, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(f"{len(account.items) if account else 0} 个作品", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        self.loading_indicator,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    visible=bool(self.download_progress_text),
                    content=ft.Text(self.download_progress_text, size=12, color=ft.Colors.PRIMARY),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=4),
                    border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
                    border_radius=8,
                ),
                *build_work_bulk_action_rows(self, account, has_selected),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def create_inbox_title_area(self):
        items = self._new_work_entries()
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            tooltip="返回账号列表",
                            on_click=lambda e: self.run_async(self.back_to_accounts()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.Text("新作品收件箱", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, expand=True),
                        ft.Text(f"{len(items)} 个新作品", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        self.loading_indicator,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.CLOUD_SYNC,
                            tooltip="同步全部作品",
                            on_click=lambda e: self.run_async(self.sync_all_accounts_on_click()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD,
                            tooltip="下载全部新作品",
                            disabled=self.download_in_progress or not items,
                            on_click=lambda e: self.run_async(self.download_new_inbox_items()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DONE_ALL,
                            tooltip="标记全部新作品为已处理",
                            disabled=not items,
                            on_click=lambda e: self.run_async(self.mark_all_new_items_seen()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                    ],
                    spacing=6,
                    wrap=True,
                ),
            ],
            spacing=6,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _work_filter_buttons(self) -> list[ft.Control]:
        options = [
            ("all", "全部"),
            ("new", "新作品"),
            ("pending", "未下载"),
            ("downloaded", "已下载"),
            ("failed", "失败"),
            ("video", "视频"),
            ("gallery", "图集"),
        ]
        return [
            ft.TextButton(
                label,
                icon=ft.Icons.CHECK if self.work_filter == key else None,
                disabled=self.work_filter == key,
                on_click=lambda e, mode=key: self.run_async(self.set_work_filter(mode)),
            )
            for key, label in options
        ]

    def create_works_area(self):
        return ft.Container(content=self.history_area, expand=True)

    def create_add_area(self):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            self.url_input,
                            self.name_input,
                            ft.IconButton(
                                icon=ft.Icons.INFO_OUTLINE,
                                tooltip=self._.get(
                                    "mode_hint",
                                    "仅监控用户提供的公开抖音主页；不会绕过登录、验证码、私密账号或平台风控。首次检测只建立基线，后续新增作品才提醒。",
                                ),
                                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.FilledButton(
                                self._.get("add", "添加"),
                                icon=ft.Icons.ADD,
                                on_click=self.add_account_on_click,
                            ),
                        ],
                        spacing=8,
                    ),
                ],
                spacing=6,
            ),
            padding=ft.Padding.only(bottom=8),
        )

    def create_main_area(self):
        return ft.Container(content=self.cards_area, expand=True, bgcolor=ft.Colors.SURFACE, padding=ft.Padding.only(top=4))

    async def refresh_view(self):
        if self.cards_area is None or self.history_area is None:
            return
        if self.view_mode == "works":
            await self.refresh_works()
            try:
                self.history_area.update()
            except Exception:
                pass
            return
        if self.view_mode == "inbox":
            await self.refresh_new_work_inbox()
            try:
                self.history_area.update()
            except Exception:
                pass
            return
        self.cards_area.controls.clear()
        accounts = self._visible_accounts()
        if not accounts:
            self.cards_area.controls.append(
                ft.Container(
                    content=ft.Text(self._.get("empty", "还没有添加抖音主页。"), color=ft.Colors.ON_SURFACE_VARIANT),
                    padding=20,
                )
            )
        else:
            for account in accounts:
                self.cards_area.controls.append(self.create_account_card(account))
        try:
            self.cards_area.update()
        except Exception:
            pass
        if self.view_mode == "accounts":
            await self.restore_pending_account_scroll_position()

    def _filter_accounts(self, accounts: list[DouyinMonitorAccount]) -> list[DouyinMonitorAccount]:
        mode = str(self.account_filter or "all")
        if mode == "enabled":
            return [account for account in accounts if account.monitor_enabled]
        if mode == "new":
            return [account for account in accounts if account.last_new_count]
        if mode == "error":
            return [account for account in accounts if account.last_error or "异常" in str(account.status)]
        if mode == "stopped":
            return [account for account in accounts if not account.monitor_enabled]
        return accounts

    def _visible_accounts(self) -> list[DouyinMonitorAccount]:
        accounts = self._filter_accounts(list(self.manager.accounts))
        group_filter = str(self.account_group_filter or "all")
        if group_filter == "__ungrouped__":
            accounts = [account for account in accounts if not str(account.group_name or "").strip()]
        elif group_filter != "all":
            accounts = [account for account in accounts if str(account.group_name or "").strip() == group_filter]
        if self.account_search_query:
            query = self.account_search_query.lower()
            accounts = [
                account
                for account in accounts
                if query in (account.display_name or "").lower()
                or query in (account.douyin_nickname or "").lower()
                or query in (account.group_name or "").lower()
                or query in (account.homepage_url or "").lower()
            ]
        return accounts

    async def refresh_history(self):
        if self.history_area is None:
            return
        self.history_area.controls.clear()
        account = self.manager.find_account(self.selected_account_id) if self.selected_account_id else None
        if account is None and self.manager.accounts:
            account = self.manager.accounts[0]
            self.selected_account_id = account.account_id
        if account is None:
            self.history_area.controls.append(ft.Text(self._.get("history_empty", "无作品历史。"), size=12))
            return
        self.history_area.controls.append(
            ft.Text(
                f"{account.display_name or account.douyin_nickname or account.homepage_url}  ·  {len(account.items)} 个作品",
                weight=ft.FontWeight.BOLD,
            )
        )
        if not account.items:
            self.history_area.controls.append(ft.Text(self._.get("history_empty", "无作品历史。"), size=12))
            return
        sorted_items = self.manager.sort_items_newest_first(account.items)
        for item in sorted_items[:60]:
            try:
                self.history_area.controls.append(self.create_history_item(item))
            except Exception as exc:
                logger.exception(f"Render Douyin history item failed: item_id={getattr(item, 'item_id', '')}, error={exc}")
                self.history_area.controls.append(
                    ft.Text(f"作品渲染失败：{getattr(item, 'item_id', '-')}", size=11, color=ft.Colors.ERROR)
                )

    async def refresh_works(self):
        if self.history_area is None:
            return
        self.history_area.controls.clear()
        account = self.manager.find_account(self.selected_account_id) if self.selected_account_id else None
        if account is None:
            self.history_area.controls.append(ft.Text("未选择抖音用户", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
            return
        if not account.items:
            self.history_area.controls.append(ft.Text(self._.get("history_empty", "暂无作品历史。"), size=12))
            return

        filtered_items = self._filter_work_items(account.items, self.work_filter)
        visible_items = self.manager.sort_items_newest_first(filtered_items)[: self.visible_work_count]
        for item in visible_items:
            try:
                self.history_area.controls.append(self.create_history_item(item))
            except Exception as exc:
                logger.exception(f"Render Douyin work item failed: item_id={getattr(item, 'item_id', '')}, error={exc}")
                self.history_area.controls.append(
                    ft.Text(f"作品渲染失败：{getattr(item, 'item_id', '-')}", size=11, color=ft.Colors.ERROR)
                )

        if self.visible_work_count < len(filtered_items):
            self.history_area.controls.append(
                ft.OutlinedButton(
                    f"加载更多（{min(self.visible_work_count + self.work_page_size, len(filtered_items))}/{len(filtered_items)}）",
                    icon=ft.Icons.EXPAND_MORE,
                    on_click=lambda e: self.run_async(self.load_more_works()),
                )
            )

    def _new_work_entries(self) -> list[tuple[DouyinMonitorAccount, Any]]:
        entries: list[tuple[DouyinMonitorAccount, Any]] = []
        for account in self.manager.accounts:
            for item in getattr(account, "items", []):
                if getattr(item, "status", "") == "new":
                    entries.append((account, item))
        entries.sort(key=lambda entry: getattr(entry[1], "first_seen_time", "") or getattr(entry[1], "publish_time", ""), reverse=True)
        return entries

    async def refresh_new_work_inbox(self):
        if self.history_area is None:
            return
        self.history_area.controls.clear()
        entries = self._new_work_entries()
        if not entries:
            self.history_area.controls.append(
                ft.Container(
                    padding=18,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    content=ft.Column(
                        controls=[
                            ft.Text("暂无新作品", weight=ft.FontWeight.BOLD),
                            ft.Text("同步或检测监控账号后，新作品会集中显示在这里。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=6,
                    ),
                )
            )
            return
        for account, item in entries[: self.visible_work_count]:
            self.history_area.controls.append(self.create_inbox_item(account, item))
        if self.visible_work_count < len(entries):
            self.history_area.controls.append(
                ft.OutlinedButton(
                    f"加载更多（{min(self.visible_work_count + self.work_page_size, len(entries))}/{len(entries)}）",
                    icon=ft.Icons.EXPAND_MORE,
                    on_click=lambda e: self.run_async(self.load_more_works()),
                )
            )

    def create_inbox_item(self, account: DouyinMonitorAccount, item):
        return build_inbox_item_card(self, account, item)

    def _filter_work_items(self, items: list[Any], mode: str) -> list[Any]:
        mode = str(mode or "all")
        base = [item for item in items if getattr(item, "status", "") != "count_only"]
        if mode == "new":
            return [item for item in base if getattr(item, "status", "") == "new"]
        if mode == "pending":
            return [item for item in base if getattr(item, "status", "") not in {"downloaded", "download_failed"}]
        if mode == "downloaded":
            return [item for item in base if getattr(item, "status", "") == "downloaded"]
        if mode == "failed":
            return [item for item in base if getattr(item, "status", "") == "download_failed"]
        if mode == "video":
            return [item for item in base if not self._is_gallery_item(item)]
        if mode == "gallery":
            return [item for item in base if self._is_gallery_item(item)]
        return base

    def create_account_card(self, account: DouyinMonitorAccount):
        return build_account_card(self, account)

    def create_history_item(self, item):
        return build_history_item_card(self, item)

    def _work_status_chip(self, item) -> ft.Container:
        return build_work_status_chip(self, item)

    @staticmethod
    def _is_gallery_item(item) -> bool:
        return bool(getattr(item, "image_urls", None)) or str(getattr(item, "media_type", "") or "").lower() in {
            "image",
            "images",
            "gallery",
            "note",
        }

    async def _await_coro(self, coro):
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Douyin content UI task failed: {exc}")
            try:
                await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3500, show_close_icon=True)
            except Exception:
                pass

    def run_async(self, coro):
        self.page.run_task(self._await_coro, coro)

    async def set_loading(self, visible: bool):
        if self.loading_indicator:
            self.loading_indicator.visible = visible
            try:
                self.loading_indicator.update()
            except Exception:
                pass

    async def show_add_account_dialog(self, _e=None):
        url_field = ft.TextField(
            label="抖音主页链接",
            hint_text="https://www.douyin.com/user/...",
            autofocus=True,
            dense=True,
            width=520,
        )
        name_field = ft.TextField(label="备注名称", dense=True, width=520)

        async def close_dialog(_=None):
            dialog.open = False
            try:
                self.app.dialog_area.update()
            except Exception:
                pass

        async def submit(_=None):
            url = (url_field.value or "").strip()
            name = (name_field.value or "").strip()
            if not url:
                await self.app.snack_bar.show_snack_bar("请输入抖音主页链接", bgcolor=ft.Colors.ERROR)
                return
            try:
                account, message = await self._add_account_with_auto_name(url, name)
                self.selected_account_id = account.account_id
                self.account_search_query = ""
                await close_dialog()
                await self.refresh_view()
                self.safe_content_update()
                await self.app.snack_bar.show_snack_bar(message, bgcolor=ft.Colors.PRIMARY, duration=4500, show_close_icon=True)
            except Exception as exc:
                await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3500, show_close_icon=True)

        url_field.on_submit = submit
        name_field.on_submit = submit
        dialog = ft.AlertDialog(
            title=ft.Text("添加抖音监控用户", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column([url_field, name_field], tight=True, spacing=10, width=540),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.TextButton("添加", icon=ft.Icons.ADD, on_click=submit),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def show_batch_import_dialog(self):
        async def close_dialog(_=None):
            dialog = controls.dialog
            dialog.open = False
            self.app.dialog_area.update()

        async def submit(import_controls: BatchImportControls):
            rows = self._parse_batch_import_rows(import_controls.text_field.value or "", import_controls.default_group.value or "")
            if not rows:
                await self.app.snack_bar.show_snack_bar("未识别到可导入的抖音主页链接", bgcolor=ft.Colors.ERROR)
                return
            added = 0
            updated = 0
            failed = 0
            for row in rows:
                try:
                    before_ids = {account.account_id for account in self.manager.accounts}
                    account = await self.manager.add_account(row["url"], row["name"])
                    if account.account_id in before_ids:
                        updated += 1
                    else:
                        added += 1
                    await self.manager.update_account_settings(
                        account.account_id,
                        display_name=row["name"] or account.display_name,
                        group_name=row["group"],
                        auto_download_policy=import_controls.policy_dropdown.value or "none",
                        notify_enabled=bool(import_controls.notify_switch.value),
                    )
                    if import_controls.start_switch.value:
                        await self.manager.start_monitor(account.account_id)
                except Exception as exc:
                    failed += 1
                    logger.debug(f"batch import account failed: {row.get('url')}, error={exc}")
            await close_dialog()
            await self.render_current_view()
            await self.app.snack_bar.show_snack_bar(
                f"批量导入完成：新增 {added}，更新 {updated}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

        controls = build_batch_import_dialog(lambda c: self.run_async(submit(c)), close_dialog)
        dialog = controls.dialog
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    def _parse_batch_import_rows(self, text: str, default_group: str = "") -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        seen: set[str] = set()
        for raw_line in str(text or "").splitlines():
            line = raw_line.strip()
            if not line:
                continue
            url_match = re.search(r"https?://[^\s,，\t]+", line, re.IGNORECASE)
            if not url_match:
                continue
            url = url_match.group(0).strip()
            if url in seen:
                continue
            seen.add(url)
            rest = (line[: url_match.start()] + " " + line[url_match.end() :]).strip(" ,，\t")
            parts = [part.strip() for part in re.split(r"[,，\t]", rest) if part.strip()]
            name = parts[0] if parts else ""
            group = parts[1] if len(parts) > 1 else str(default_group or "").strip()
            rows.append({"url": url, "name": name, "group": group})
        return rows

    async def search_accounts_on_click(self, _e=None):
        query_field = ft.TextField(
            label="搜索昵称或备注",
            value=self.account_search_query,
            autofocus=True,
            dense=True,
            width=420,
        )

        async def close_dialog(_=None):
            dialog.open = False
            try:
                self.app.dialog_area.update()
            except Exception:
                pass

        async def submit(_=None):
            self.account_search_query = (query_field.value or "").strip()
            await close_dialog()
            await self.refresh_view()
            self.safe_content_update()

        async def clear(_=None):
            self.account_search_query = ""
            await close_dialog()
            await self.refresh_view()
            self.safe_content_update()

        query_field.on_submit = submit
        dialog = ft.AlertDialog(
            title=ft.Text("搜索监控用户", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column([query_field], tight=True, spacing=10, width=440),
            actions=[
                ft.TextButton("清除", icon=ft.Icons.CLEAR, on_click=clear),
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.TextButton("搜索", icon=ft.Icons.SEARCH, on_click=submit),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def show_edit_account_dialog(self, account_id: str):
        account = self.manager.find_account(account_id)
        if not account:
            await self.app.snack_bar.show_snack_bar("账号不存在", bgcolor=ft.Colors.ERROR)
            return
        name_field = ft.TextField(label="备注名称", value=account.display_name or "", width=520)
        group_field = ft.TextField(label="分组", value=account.group_name or "", hint_text="例如：重点、舞蹈、美食", width=520)
        notify_switch = ft.Switch(label="发现新作品时通知", value=bool(account.notify_enabled))
        interval_field = ft.TextField(label="单账号检测间隔（分钟，0=使用全局）", value=str(getattr(account, "monitor_interval_minutes", 0) or 0), width=250, keyboard_type=ft.KeyboardType.NUMBER)
        pause_failures_field = ft.TextField(label="连续失败自动暂停（0=关闭）", value=str(getattr(account, "auto_pause_failures", 0) or 0), width=250, keyboard_type=ft.KeyboardType.NUMBER)
        keep_recent_field = ft.TextField(label="仅保留最近 N 个作品（0=不限制）", value=str(getattr(account, "keep_recent_count", 0) or 0), width=250, keyboard_type=ft.KeyboardType.NUMBER)
        auto_sync_switch = ft.Switch(label="检测时自动同步作品资料", value=bool(getattr(account, "auto_sync_enabled", True)))
        notify_mode_dropdown = ft.Dropdown(
            label="新作品提醒方式",
            value=getattr(account, "notify_mode", "desktop") or "desktop",
            width=250,
            options=[
                ft.dropdown.Option("desktop", "桌面通知"),
                ft.dropdown.Option("task", "仅任务中心"),
                ft.dropdown.Option("silent", "静默记录"),
            ],
        )
        policy_dropdown = ft.Dropdown(
            label="新增作品自动下载",
            value=account.auto_download_policy or "none",
            width=300,
            options=[
                ft.dropdown.Option("none", "不自动下载"),
                ft.dropdown.Option("video", "只下载视频"),
                ft.dropdown.Option("gallery", "只下载图集"),
                ft.dropdown.Option("all", "自动下载全部"),
            ],
        )

        async def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        async def submit(_=None):
            try:
                monitor_interval = max(0.0, float((interval_field.value or "0").strip() or 0))
                auto_pause_failures = max(0, int((pause_failures_field.value or "0").strip() or 0))
                keep_recent_count = max(0, int((keep_recent_field.value or "0").strip() or 0))
            except ValueError:
                await self.app.snack_bar.show_snack_bar("监控策略请输入有效数字", bgcolor=ft.Colors.ERROR)
                return

            ok = await self.manager.update_account_settings(
                account_id,
                display_name=(name_field.value or "").strip(),
                group_name=(group_field.value or "").strip(),
                auto_download_policy=policy_dropdown.value or "none",
                monitor_interval_minutes=monitor_interval,
                auto_sync_enabled=bool(auto_sync_switch.value),
                auto_pause_failures=auto_pause_failures,
                keep_recent_count=keep_recent_count,
                notify_mode=notify_mode_dropdown.value or "desktop",
                notify_enabled=bool(notify_switch.value),
            )
            await close_dialog()
            await self.render_current_view()
            await self.app.snack_bar.show_snack_bar("账号设置已保存" if ok else "账号不存在", bgcolor=ft.Colors.PRIMARY if ok else ft.Colors.ERROR)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("编辑监控账号"),
            content=ft.Column(
                controls=[
                    name_field,
                    group_field,
                    ft.Row([interval_field, pause_failures_field], spacing=10, wrap=True),
                    ft.Row([keep_recent_field, notify_mode_dropdown], spacing=10, wrap=True),
                    auto_sync_switch,
                    ft.Row(
                        [
                            policy_dropdown,
                            ft.IconButton(
                                icon=ft.Icons.INFO_OUTLINE,
                                tooltip="自动下载只对后续新增作品生效；已有作品请在作品页手动下载。",
                                icon_color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=8,
                    ),
                    notify_switch,
                ],
                tight=True,
                spacing=10,
                width=540,
            ),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.FilledButton("保存", icon=ft.Icons.SAVE, on_click=submit),
            ],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def add_account_on_click(self, _e=None):
        url = self.url_input.value.strip() if self.url_input else ""
        name = self.name_input.value.strip() if self.name_input else ""
        if not url:
            await self.app.snack_bar.show_snack_bar(self._.get("url_required", "请输入抖音主页链接"), bgcolor=ft.Colors.ERROR)
            return
        try:
            account, message = await self._add_account_with_auto_name(url, name)
            self.selected_account_id = account.account_id
            if self.url_input:
                self.url_input.value = ""
            if self.name_input:
                self.name_input.value = ""
            await self.refresh_view()
            self.safe_content_update()
            await self.app.snack_bar.show_snack_bar(message, bgcolor=ft.Colors.PRIMARY, duration=4500, show_close_icon=True)
        except Exception as exc:
            await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3000, show_close_icon=True)

    async def _add_account_with_auto_name(self, url: str, name: str):
        manual_name = str(name or "").strip()
        account = await self.manager.add_account(url, manual_name)
        if manual_name:
            return account, "已添加抖音监控用户"

        result = await self.manager.hydrate_account_display_name(account.account_id)
        account = self.manager.find_account(account.account_id) or account
        display_name = account.display_name or account.douyin_nickname or "抖音用户"
        if result.get("success") and display_name != "抖音用户":
            return account, f"已添加抖音监控用户，自动填充昵称：{display_name}"
        return account, "已添加抖音监控用户，暂未获取到昵称，可稍后检测一次自动更新"

    async def refresh_on_click(self, _e=None):
        await self.refresh_view()
        self.safe_content_update()

    def _monitor_export_dir(self) -> str:
        return os.path.join(self.app.run_path, "downloads", "monitor_exports")

    async def open_monitor_export_dir(self):
        path = self._monitor_export_dir()
        os.makedirs(path, exist_ok=True)
        await self.open_path_or_url(path, success="已打开导出目录")

    async def export_monitor_csv(self):
        export_dir = self._monitor_export_dir()
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"douyin_monitor_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
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
            )
            for account in self.manager.accounts:
                items = [item for item in account.items if item.status != "count_only"] or [None]
                for item in items:
                    writer.writerow(
                        [
                            account.display_name,
                            account.douyin_nickname,
                            account.group_name,
                            account.homepage_url,
                            "监控中" if account.monitor_enabled else "未监控",
                            "开启" if account.notify_enabled else "关闭",
                            self._auto_download_policy_label(account.auto_download_policy),
                            account.last_check_time,
                            account.last_success_time,
                            account.status,
                            account.last_error,
                            getattr(item, "item_id", "") if item else "",
                            getattr(item, "title", "") if item else "",
                            "图集" if item and self._is_gallery_item(item) else ("视频" if item else ""),
                            getattr(item, "status", "") if item else "",
                            getattr(item, "publish_time", "") if item else "",
                            getattr(item, "first_seen_time", "") if item else "",
                            getattr(item, "share_url", "") if item else "",
                        ]
                    )
        await self.app.snack_bar.show_snack_bar(f"已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)

    async def export_monitor_accounts_csv(self):
        export_dir = self._monitor_export_dir()
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"douyin_monitor_accounts_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        accounts = list(self.manager.accounts)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
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
            )
            for account in accounts:
                items = [item for item in getattr(account, "items", []) if getattr(item, "status", "") != "count_only"]
                writer.writerow(
                    [
                        account.account_id,
                        account.display_name,
                        account.douyin_nickname,
                        account.group_name,
                        account.homepage_url,
                        "监控中" if account.monitor_enabled else "未监控",
                        account.status,
                        "开启" if account.notify_enabled else "关闭",
                        self._auto_download_policy_label(account.auto_download_policy),
                        account.monitor_interval_minutes or "全局",
                        account.auto_pause_failures,
                        account.keep_recent_count or "不限",
                        account.last_check_time,
                        account.last_success_time,
                        account.last_new_count,
                        account.total_new_count,
                        len(items),
                        account.aweme_count if account.aweme_count >= 0 else "",
                        account.error_count,
                        account.last_error,
                    ]
                )
        await self.app.snack_bar.show_snack_bar(f"监控用户已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)

    async def set_account_filter(self, mode: str):
        self.account_filter = str(mode or "all")
        await self.render_current_view()

    async def set_account_group_filter(self, group: str):
        self.account_group_filter = str(group or "all")
        await self.render_current_view()

    async def set_work_filter(self, mode: str):
        self.work_filter = str(mode or "all")
        self.visible_work_count = self.work_page_size
        await self.render_current_view()

    async def select_account(self, account_id: str):
        self.selected_account_id = account_id
        await self.refresh_history()
        if self.history_area:
            self.history_area.update()
        try:
            self.safe_content_update()
        except Exception:
            pass

    async def open_account_works(self, account_id: str):
        self.selected_account_id = account_id
        self.return_account_anchor_id = account_id
        self.view_mode = "works"
        self.work_select_mode = False
        self.selected_work_ids.clear()
        self.work_filter = "all"
        self.visible_work_count = self.work_page_size
        await self.render_current_view()

    async def open_new_work_inbox(self):
        self.view_mode = "inbox"
        self.work_select_mode = False
        self.selected_work_ids.clear()
        self.visible_work_count = self.work_page_size
        await self.render_current_view()

    async def back_to_accounts(self):
        anchor_id = self.return_account_anchor_id or self.selected_account_id
        self.pending_account_scroll_anchor_id = anchor_id
        self.account_scroll_anchor_hold_until = time.monotonic() + 3.0
        self.view_mode = "accounts"
        self.work_select_mode = False
        self.selected_work_ids.clear()
        await self.render_current_view()

    async def preview_inbox_item(self, account_id: str, item_id: str, is_gallery: bool):
        previous_account = self.selected_account_id
        previous_mode = self.view_mode
        self.selected_account_id = account_id
        try:
            if is_gallery:
                await self.preview_item_images(item_id)
            else:
                await self.browse_video(item_id)
        finally:
            self.selected_account_id = previous_account
            self.view_mode = previous_mode

    async def download_inbox_item(self, account_id: str, item_id: str):
        previous_account = self.selected_account_id
        previous_mode = self.view_mode
        self.selected_account_id = account_id
        try:
            await self.download_one(item_id)
        finally:
            self.selected_account_id = previous_account
            self.view_mode = previous_mode
            await self.render_current_view()

    async def download_new_inbox_items(self):
        entries = self._new_work_entries()
        if not entries:
            await self.app.snack_bar.show_snack_bar("暂无新作品可下载", bgcolor=ft.Colors.PRIMARY)
            return
        grouped: dict[str, list[str]] = {}
        for account, item in entries:
            grouped.setdefault(account.account_id, []).append(item.item_id)
        self.download_in_progress = True
        self.download_stop_requested = False
        await self.set_loading(True)
        try:
            success = 0
            failed = 0
            stopped = False
            for account_id, item_ids in grouped.items():
                part_success, part_failed, part_stopped = await self._download_items_until_stopped(account_id, item_ids)
                success += part_success
                failed += part_failed
                stopped = stopped or part_stopped
                if stopped:
                    break
            await self.app.snack_bar.show_snack_bar(
                f"{'下载已停止' if stopped else '新作品下载完成'}：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            self.download_in_progress = False
            self.download_stop_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    async def mark_item_seen(self, account_id: str, item_id: str):
        account = self.manager.find_account(account_id)
        item = next((candidate for candidate in getattr(account, "items", []) if candidate.item_id == item_id), None) if account else None
        if item is None:
            return
        if item.status == "new":
            item.status = ""
        await self.manager.persist()
        await self.render_current_view()

    async def mark_all_new_items_seen(self):
        changed = 0
        for account, item in self._new_work_entries():
            if item.status == "new":
                item.status = ""
                changed += 1
        if changed:
            await self.manager.persist()
        await self.render_current_view()
        await self.app.snack_bar.show_snack_bar(f"已标记 {changed} 个新作品为已处理", bgcolor=ft.Colors.PRIMARY)

    @staticmethod
    def _account_anchor_key(account_id: str) -> str:
        return f"douyin-account-card-{account_id}"

    def _account_anchor_offset(self, account_id: str) -> float | None:
        for index, account in enumerate(self._visible_accounts()):
            if account.account_id == account_id:
                return float(max(index, 0) * 238)
        return None

    async def restore_pending_account_scroll_position(self) -> None:
        anchor_id = self.pending_account_scroll_anchor_id
        if not anchor_id and time.monotonic() <= self.account_scroll_anchor_hold_until:
            anchor_id = self.return_account_anchor_id
        if not anchor_id:
            return
        restored = await self.restore_account_scroll_position(anchor_id)
        if restored and self.pending_account_scroll_anchor_id == anchor_id:
            self.pending_account_scroll_anchor_id = None

    async def restore_account_scroll_position(self, account_id: str | None) -> bool:
        if not account_id or not self.cards_area:
            return False
        if not any(account.account_id == account_id for account in self._visible_accounts()):
            return False
        try:
            await asyncio.sleep(0.08)
            result = self.cards_area.scroll_to(
                key=self._account_anchor_key(account_id),
                duration=0,
            )
            if inspect.isawaitable(result):
                await result
            return True
        except Exception as exc:
            logger.debug(f"restore account scroll position failed: {exc}")
            offset = self._account_anchor_offset(account_id)
            if offset is None:
                return False
            try:
                result = self.cards_area.scroll_to(offset=offset, duration=0)
                if inspect.isawaitable(result):
                    await result
                return True
            except Exception as fallback_exc:
                logger.debug(f"restore account scroll fallback failed: {fallback_exc}")
        return False

    async def load_more_works(self):
        self.visible_work_count += self.work_page_size
        await self.refresh_works()
        if self.history_area:
            self.history_area.update()

    async def toggle_account_select_mode(self):
        self.account_select_mode = not self.account_select_mode
        if not self.account_select_mode:
            self.selected_account_ids.clear()
        await self.render_current_view()

    async def toggle_account_selected(self, account_id: str, selected: bool | None = None):
        should_select = account_id not in self.selected_account_ids if selected is None else selected
        if should_select:
            self.selected_account_ids.add(account_id)
        else:
            self.selected_account_ids.discard(account_id)
        await self.render_current_view()

    async def select_all_accounts(self):
        account_ids = {account.account_id for account in self._visible_accounts()}
        if self.selected_account_ids >= account_ids and account_ids:
            self.selected_account_ids.difference_update(account_ids)
        else:
            self.selected_account_ids.update(account_ids)
        await self.render_current_view()

    async def invert_visible_accounts(self):
        for account in self._visible_accounts():
            if account.account_id in self.selected_account_ids:
                self.selected_account_ids.discard(account.account_id)
            else:
                self.selected_account_ids.add(account.account_id)
        await self.render_current_view()

    async def clear_selected_accounts(self):
        self.selected_account_ids.clear()
        await self.render_current_view()

    def _selected_accounts(self) -> list[DouyinMonitorAccount]:
        selected = set(self.selected_account_ids)
        return [account for account in self.manager.accounts if account.account_id in selected]

    async def show_batch_account_settings_dialog(self):
        accounts = self._selected_accounts()
        if not accounts:
            await self.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        group_field = ft.TextField(label="统一设置分组", hint_text="留空则不修改分组", width=420)
        policy_dropdown = ft.Dropdown(
            label="新增作品自动下载",
            value="__keep__",
            width=300,
            options=[
                ft.dropdown.Option("__keep__", "保持不变"),
                ft.dropdown.Option("none", "不自动下载"),
                ft.dropdown.Option("video", "只下载视频"),
                ft.dropdown.Option("gallery", "只下载图集"),
                ft.dropdown.Option("all", "自动下载全部"),
            ],
        )
        notify_dropdown = ft.Dropdown(
            label="新作品通知",
            value="__keep__",
            width=300,
            options=[
                ft.dropdown.Option("__keep__", "保持不变"),
                ft.dropdown.Option("on", "开启通知"),
                ft.dropdown.Option("off", "关闭通知"),
            ],
        )

        async def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        async def submit(_=None):
            group_value = str(group_field.value or "").strip()
            policy_value = str(policy_dropdown.value or "__keep__")
            notify_value = str(notify_dropdown.value or "__keep__")
            changed = 0
            for account in accounts:
                ok = await self.manager.update_account_settings(
                    account.account_id,
                    group_name=group_value if group_value else None,
                    auto_download_policy=policy_value if policy_value != "__keep__" else None,
                    notify_enabled=True if notify_value == "on" else (False if notify_value == "off" else None),
                )
                if ok:
                    changed += 1
            await close_dialog()
            await self.render_current_view()
            await self.app.snack_bar.show_snack_bar(f"已更新 {changed} 个账号设置", bgcolor=ft.Colors.PRIMARY)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"批量设置 {len(accounts)} 个账号"),
            content=ft.Column(
                controls=[
                    group_field,
                    ft.Row([policy_dropdown, notify_dropdown], spacing=10, wrap=True),
                    ft.IconButton(
                        icon=ft.Icons.INFO_OUTLINE,
                        tooltip="空分组表示不修改；需要清空分组时请在单个账号编辑里处理。",
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                tight=True,
                spacing=10,
                width=560,
            ),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.FilledButton("保存", icon=ft.Icons.SAVE, on_click=submit),
            ],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def _run_selected_account_job(self, title: str, category: str, job) -> tuple[int, int, int]:
        accounts = self._selected_accounts()
        if not accounts:
            await self.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        self.batch_job_running = True
        self.batch_cancel_requested = False
        await self.set_loading(True)
        task_center = getattr(self.app.services, "task_center", None)
        task_id = task_center.start(title, category, total=len(accounts)) if task_center else None
        success = 0
        failed = 0
        new_total = 0
        result_lines: list[str] = []
        last_refresh = 0.0
        cancelled = False
        try:
            for index, account in enumerate(accounts, start=1):
                if self.batch_cancel_requested:
                    cancelled = True
                    result_lines.append("[取消] 用户已取消批量任务")
                    break
                name = account.display_name or account.douyin_nickname or account.account_id
                try:
                    result = job(account)
                    if inspect.isawaitable(result):
                        result = await result
                    ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
                    if ok:
                        success += 1
                        reason = str(result.get("reason") or "成功") if isinstance(result, dict) else "成功"
                        result_lines.append(f"[成功] {name}：{reason}")
                        if isinstance(result, dict):
                            try:
                                new_total += int(result.get("new") or len(result.get("new_items") or []))
                            except (TypeError, ValueError):
                                pass
                    else:
                        failed += 1
                        reason = str(result.get("reason") or "失败") if isinstance(result, dict) else "失败"
                        result_lines.append(f"[失败] {name}：{reason}")
                except Exception as exc:
                    failed += 1
                    result_lines.append(f"[失败] {name}：{exc}")
                    logger.debug(f"{title} failed for account={account.account_id}: {exc}")
                if task_center and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"进度：{index}/{len(accounts)}，成功 {success}，失败 {failed}，新增 {new_total}",
                    )
                now = time.monotonic()
                if index == len(accounts) or now - last_refresh >= 0.6:
                    await self.refresh_view()
                    last_refresh = now
            if task_center and task_id:
                detail = f"已取消：成功 {success}，失败 {failed}，新增 {new_total}" if cancelled else f"完成：成功 {success}，失败 {failed}，新增 {new_total}"
                if cancelled and hasattr(task_center, "cancel"):
                    task_center.cancel(task_id, detail)
                else:
                    task_center.finish(task_id, success=(failed == 0 and not cancelled), detail=detail)
            self.batch_result_lines = result_lines[-200:]
            return success, failed, new_total
        finally:
            self.batch_job_running = False
            self.batch_cancel_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    async def cancel_batch_job(self):
        if not self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("当前没有批量任务", bgcolor=ft.Colors.ERROR)
            return
        self.batch_cancel_requested = True
        await self.render_current_view()
        await self.app.snack_bar.show_snack_bar("已请求取消，当前账号处理完成后停止", bgcolor=ft.Colors.PRIMARY)

    async def show_batch_result_dialog(self):
        if not self.batch_result_lines:
            await self.app.snack_bar.show_snack_bar("暂无批量操作明细", bgcolor=ft.Colors.PRIMARY)
            return

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("最近批量操作明细"),
            content=ft.Column(
                controls=[ft.Text("\n".join(self.batch_result_lines), selectable=True, size=12)],
                tight=True,
                width=760,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def start_selected_accounts(self):
        if not self.selected_account_ids:
            await self.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        await self.set_loading(True)
        try:
            total = 0
            lines = []
            for account_id in list(self.selected_account_ids):
                account = self.manager.find_account(account_id)
                name = (account.display_name or account.douyin_nickname or account_id) if account else account_id
                if await self.manager.start_monitor(account_id):
                    total += 1
                    lines.append(f"[成功] {name}：已开始监控")
                else:
                    lines.append(f"[失败] {name}：账号不存在")
            self.batch_result_lines = lines[-200:]
            await self.refresh_view()
            await self.app.snack_bar.show_snack_bar(f"已开始监控 {total} 个账号", bgcolor=ft.Colors.PRIMARY)
        finally:
            await self.set_loading(False)
            await self.render_current_view()

    async def stop_selected_accounts(self, confirmed: bool = False):
        if not self.selected_account_ids:
            await self.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            count = len(self.selected_account_ids)
            self.show_confirm_dialog(
                "确认批量停止",
                f"将停止监控 {count} 个账号，是否继续？",
                lambda: self.stop_selected_accounts(confirmed=True),
            )
            return
        await self.set_loading(True)
        try:
            total = 0
            lines = []
            for account_id in list(self.selected_account_ids):
                account = self.manager.find_account(account_id)
                name = (account.display_name or account.douyin_nickname or account_id) if account else account_id
                if await self.manager.stop_monitor(account_id):
                    total += 1
                    lines.append(f"[成功] {name}：已停止监控")
                else:
                    lines.append(f"[失败] {name}：账号不存在")
            self.batch_result_lines = lines[-200:]
            await self.refresh_view()
            await self.app.snack_bar.show_snack_bar(f"已停止监控 {total} 个账号", bgcolor=ft.Colors.PRIMARY)
        finally:
            await self.set_loading(False)
            await self.render_current_view()

    async def check_selected_accounts(self):
        success, failed, _new_total = await self._run_selected_account_job(
            "检测选中账号",
            "内容监控",
            lambda account: self.manager.check_account(account.account_id, notify=True),
        )
        if success or failed:
            await self.app.snack_bar.show_snack_bar(
                f"检测选中完成：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def sync_selected_accounts(self):
        success, failed, new_total = await self._run_selected_account_job(
            "同步选中账号作品",
            "作品监控",
            lambda account: self.manager.sync_account_works(account.account_id),
        )
        if success or failed:
            await self.app.snack_bar.show_snack_bar(
                f"同步选中完成：成功 {success}，失败 {failed}，新增 {new_total}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def delete_selected_accounts(self, confirmed: bool = False):
        accounts = self._selected_accounts()
        if not accounts:
            await self.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            names = [account.display_name or account.douyin_nickname or account.homepage_url or account.account_id for account in accounts[:5]]
            suffix = "..." if len(accounts) > 5 else ""
            self.show_confirm_dialog(
                "确认批量删除",
                f"将删除 {len(accounts)} 个账号及其监控记录：{', '.join(names)}{suffix}。是否继续？",
                lambda: self.delete_selected_accounts(confirmed=True),
            )
            return
        await self.set_loading(True)
        try:
            deleted = 0
            self.recent_deleted_accounts = [account.to_dict() for account in accounts]
            self.deleted_account_batches.append(self.recent_deleted_accounts)
            self.deleted_account_batches = self.deleted_account_batches[-10:]
            lines = []
            for account in accounts:
                name = account.display_name or account.douyin_nickname or account.account_id
                ok = await self.manager.delete_account(account.account_id)
                if ok:
                    deleted += 1
                    lines.append(f"[成功] {name}：已删除，可从恢复按钮找回")
                else:
                    lines.append(f"[失败] {name}：删除失败")
            self.batch_result_lines = lines[-200:]
            self.selected_account_ids.clear()
            if self.selected_account_id and not self.manager.find_account(self.selected_account_id):
                self.selected_account_id = None
            await self.render_current_view()
            await self.app.snack_bar.show_snack_bar(f"已删除 {deleted} 个账号", bgcolor=ft.Colors.PRIMARY)
        finally:
            await self.set_loading(False)

    async def toggle_work_select_mode(self):
        self.work_select_mode = not self.work_select_mode
        if not self.work_select_mode:
            self.selected_work_ids.clear()
        await self.refresh_works()
        if self.history_area:
            self.history_area.update()
        self.safe_content_update()

    async def toggle_work_selected(self, item_id: str, selected: bool | None = None):
        should_select = item_id not in self.selected_work_ids if selected is None else selected
        if should_select:
            self.selected_work_ids.add(item_id)
        else:
            self.selected_work_ids.discard(item_id)
        await self.render_current_view()

    async def clear_selected_works(self):
        self.selected_work_ids.clear()
        await self.render_current_view()

    async def select_all_visible_works(self):
        account = self.manager.find_account(self.selected_account_id) if self.selected_account_id else None
        if account is None:
            return
        visible_items = self.manager.sort_items_newest_first(self._filter_work_items(account.items, self.work_filter))[: self.visible_work_count]
        visible_ids = {item.item_id for item in visible_items}
        if self.selected_work_ids >= visible_ids and visible_ids:
            self.selected_work_ids.difference_update(visible_ids)
        else:
            self.selected_work_ids.update(visible_ids)
        await self.refresh_works()
        if self.history_area:
            self.history_area.update()

    async def stop_downloads(self):
        if not self.download_in_progress:
            return
        self.download_stop_requested = True
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is not None and hasattr(queue, "cancel_all"):
            queue.cancel_all()
        await self.render_current_view()
        await self.app.snack_bar.show_snack_bar("已请求停止下载，等待中的作品会立即跳过，正在下载的请求将尽快结束", bgcolor=ft.Colors.PRIMARY)

    async def _download_items_until_stopped(self, account_id: str, item_ids: list[str]) -> tuple[int, int, bool]:
        success = 0
        failed = 0
        stopped = False
        failed_reasons: list[str] = []
        failed_item_ids: list[str] = []
        unique_ids = list(dict.fromkeys(item_ids))
        total = len(unique_ids)
        task_center = getattr(self.app.services, "task_center", None)
        task_id = None
        if task_center is not None:
            account = self.manager.find_account(account_id)
            name = (account.display_name or account.douyin_nickname or account.account_id) if account else account_id
            task_id = task_center.start(
                f"批量下载：{name}",
                "内容监控下载",
                total=total,
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids},
            )
        queue: asyncio.Queue[str] = asyncio.Queue()
        for item_id in unique_ids:
            queue.put_nowait(item_id)
        refresh_lock = asyncio.Lock()
        last_refresh = 0.0

        async def maybe_refresh(done: int) -> None:
            nonlocal last_refresh
            now = time.monotonic()
            if done < total and now - last_refresh < 0.8:
                return
            async with refresh_lock:
                now = time.monotonic()
                if done < total and now - last_refresh < 0.8:
                    return
                try:
                    await self.render_current_view()
                    last_refresh = now
                except Exception:
                    pass

        async def worker() -> None:
            nonlocal success, failed, stopped
            while not self.download_stop_requested:
                try:
                    item_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    try:
                        result = await self.manager.download_item(account_id, item_id)
                    except asyncio.CancelledError:
                        stopped = True
                        return
                    except Exception as exc:
                        result = {"success": False, "reason": str(exc) or exc.__class__.__name__}
                    if result.get("success"):
                        success += 1
                    else:
                        failed += 1
                        failed_item_ids.append(item_id)
                        failed_reasons.append(f"{item_id}：{result.get('reason') or '下载失败'}")
                    done = success + failed
                    account = self.manager.find_account(account_id)
                    item = next((candidate for candidate in getattr(account, "items", []) if candidate.item_id == item_id), None) if account else None
                    title = (getattr(item, "title", "") or item_id)[:40]
                    self.download_progress_text = f"下载进度：{done}/{total}，当前 {title}，成功 {success}，失败 {failed}"
                    if task_center is not None and task_id:
                        retry_payload = {
                            "account_id": account_id,
                            "item_ids": failed_item_ids or unique_ids,
                            "all_item_ids": unique_ids,
                            "failed_item_ids": failed_item_ids,
                        }
                        task_center.progress(
                            task_id,
                            completed=done,
                            success_count=success,
                            failed_count=failed,
                            detail=self.download_progress_text,
                            retry_payload=retry_payload,
                        )
                    await maybe_refresh(done)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(self._download_parallel_limit(), max(1, total)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break
        if self.download_stop_requested:
            stopped = True
        if task_center is not None and task_id:
            retry_payload = {
                "account_id": account_id,
                "item_ids": failed_item_ids or unique_ids,
                "all_item_ids": unique_ids,
                "failed_item_ids": failed_item_ids,
            }
            if hasattr(task_center, "update_retry_payload"):
                task_center.update_retry_payload(task_id, retry_payload)
            if stopped and hasattr(task_center, "cancel"):
                task_center.cancel(task_id, "下载已停止")
            else:
                task_center.finish(
                    task_id,
                    success=(failed == 0 and not stopped),
                    detail=self.download_progress_text,
                )
        self.download_failure_reasons = failed_reasons[-100:]
        return success, failed, stopped

    async def show_download_failures_dialog(self):
        if not self.download_failure_reasons:
            await self.app.snack_bar.show_snack_bar("暂无下载失败详情", bgcolor=ft.Colors.PRIMARY)
            return

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("下载失败详情"),
            content=ft.Column(
                controls=[ft.Text("\n".join(self.download_failure_reasons), selectable=True, size=12)],
                tight=True,
                width=720,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    def _download_parallel_limit(self) -> int:
        settings = getattr(self.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        try:
            value = int(config.get("max_parallel_downloads", 2) or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(8, value))

    async def download_selected_works(self, confirmed: bool = False):
        account_id = self.selected_account_id
        if not account_id:
            await self.app.snack_bar.show_snack_bar("请先选择抖音用户", bgcolor=ft.Colors.ERROR)
            return
        if not self.selected_work_ids:
            await self.app.snack_bar.show_snack_bar("请先选择作品", bgcolor=ft.Colors.ERROR)
            return
        if self.download_in_progress:
            await self.app.snack_bar.show_snack_bar("已有下载任务正在进行", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            count = len(self.selected_work_ids)
            self.show_confirm_dialog(
                "确认批量下载",
                f"将下载选中的 {count} 个作品，是否继续？",
                lambda: self.download_selected_works(confirmed=True),
            )
            return
        self.download_in_progress = True
        self.download_stop_requested = False
        await self.set_loading(True)
        await self.render_current_view()
        try:
            success, failed, stopped = await self._download_items_until_stopped(account_id, list(self.selected_work_ids))
            await self.render_current_view()
            prefix = "选中作品下载已停止" if stopped else "选中作品下载完成"
            await self.app.snack_bar.show_snack_bar(
                f"{prefix}：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            self.download_in_progress = False
            self.download_stop_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    async def check_one(self, account_id: str):
        await self.set_loading(True)
        try:
            result = await self.manager.check_account(account_id, notify=True)
            await self.refresh_view()
            msg = result.get("reason") or self._.get("check_done", "检测完成")
            await self.app.snack_bar.show_snack_bar(msg, bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR, duration=3500, show_close_icon=True)
        finally:
            await self.set_loading(False)

    async def sync_works(self, account_id: str):
        await self.set_loading(True)
        try:
            result = await self.manager.sync_account_works(account_id)
            await self.refresh_view()
            msg = result.get("reason") or "同步完成"
            if result.get("success"):
                msg = f"{msg}：共 {result.get('total', 0)} 个，新增 {result.get('new', 0)} 个"
            await self.app.snack_bar.show_snack_bar(
                msg,
                bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR,
                duration=4500,
                show_close_icon=True,
            )
        finally:
            await self.set_loading(False)

    async def download_one(self, item_id: str):
        account_id = self.selected_account_id
        if not account_id:
            await self.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        await self.set_loading(True)
        try:
            try:
                result = await self.manager.download_item(account_id, item_id)
            except asyncio.CancelledError:
                result = {"success": False, "reason": "下载已取消"}
            except Exception as exc:
                logger.exception(f"download one failed: {exc}")
                result = {"success": False, "reason": str(exc) or exc.__class__.__name__}
            await self.refresh_view()
            await self.app.snack_bar.show_snack_bar(
                result.get("reason") or "下载完成",
                bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            await self.set_loading(False)

    async def open_item_download_location(self, item_id: str):
        account_id = self.selected_account_id
        if not account_id:
            await self.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        info = self.manager.local_item_path_info(account_id, item_id)
        if not info.get("success"):
            await self.app.snack_bar.show_snack_bar(info.get("reason") or "未找到下载文件", bgcolor=ft.Colors.ERROR)
            return
        path = info.get("folder") or info.get("path")
        await self.open_path_or_url(str(path or ""), success="已打开下载位置")

    async def browse_video(self, item_id: str):
        account_id = self.selected_account_id
        if not account_id:
            await self.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        await self.set_loading(True)
        try:
            result = await self.manager.resolve_item_preview(account_id, item_id)
            if not result.get("success"):
                await self.app.snack_bar.show_snack_bar(
                    result.get("reason") or "视频浏览失败",
                    bgcolor=ft.Colors.ERROR,
                    duration=5000,
                    show_close_icon=True,
                )
                return
            source_url = result.get("url") or ""
            if not source_url:
                await self.app.snack_bar.show_snack_bar("未获取到视频浏览地址", bgcolor=ft.Colors.ERROR)
                return
            await VideoPlayer(self.app).preview_video(
                source_url,
                is_file_path=bool(result.get("is_file_path")),
                room_url=result.get("share_url") or source_url,
                copy_source_url=result.get("copy_source_url") or source_url,
            )
        finally:
            await self.set_loading(False)

    async def preview_item_images(self, item_id: str, selected_index: int = 0):
        account_id = self.selected_account_id
        if not account_id:
            await self.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        await self.set_loading(True)
        try:
            result = await self.manager.resolve_item_image_preview(account_id, item_id)
            if not result.get("success"):
                await self.app.snack_bar.show_snack_bar(
                    result.get("reason") or "图片预览失败",
                    bgcolor=ft.Colors.ERROR,
                    duration=5000,
                    show_close_icon=True,
                )
                return
            urls = [str(url) for url in result.get("urls", []) if url]
            if not urls:
                await self.app.snack_bar.show_snack_bar("未获取到图片预览地址", bgcolor=ft.Colors.ERROR)
                return
            index = max(0, min(selected_index, len(urls) - 1))
            self.show_image_preview_dialog(
                title=str(result.get("title") or item_id),
                urls=urls,
                selected_index=index,
                item_id=item_id,
            )
        finally:
            await self.set_loading(False)

    def show_image_preview_dialog(self, title: str, urls: list[str], selected_index: int, item_id: str) -> None:
        self.image_preview.show(urls, [title for _ in urls], selected_index)

    async def show_work_detail(self, item_id: str):
        account = self.manager.find_account(self.selected_account_id) if self.selected_account_id else None
        if account is None:
            await self.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        item = next((work for work in account.items if work.item_id == item_id), None)
        if item is None:
            await self.app.snack_bar.show_snack_bar("作品不存在", bgcolor=ft.Colors.ERROR)
            return
        is_gallery = self._is_gallery_item(item)

        async def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        info = [
            f"标题：{item.title or '-'}",
            f"作品 ID：{item.item_id}",
            f"类型：{'图集' if is_gallery else '视频'}",
            f"状态：{item.status or '-'}",
            f"发布时间：{item.publish_time or '-'}",
            f"首次发现：{item.first_seen_time or '-'}",
            f"最近发现：{item.last_seen_time or '-'}",
            f"图片数量：{len(item.image_urls or [])}",
            f"作品链接：{item.share_url or '-'}",
        ]
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("作品详情"),
            content=ft.Column(
                controls=[ft.Text("\n".join(info), selectable=True, size=12)],
                tight=True,
                width=620,
            ),
            actions=[
                ft.TextButton("复制链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=item.share_url: self.run_async(self.copy_text(url))),
                ft.TextButton(
                    "预览",
                    icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE,
                    on_click=lambda e, work_id=item.item_id: self.run_async(self.preview_item_images(work_id) if is_gallery else self.browse_video(work_id)),
                ),
                ft.TextButton("下载", icon=ft.Icons.DOWNLOAD, on_click=lambda e, work_id=item.item_id: self.run_async(self.download_one(work_id))),
                ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog),
            ],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def show_monitor_history_dialog(self, account_id: str):
        account = self.manager.find_account(account_id)
        if account is None:
            await self.app.snack_bar.show_snack_bar("账号不存在", bgcolor=ft.Colors.ERROR)
            return
        history = list(getattr(account, "monitor_history", []) or [])[-30:]
        if history:
            lines = [
                f"{item.get('time', '-')} | {'成功' if item.get('success') else '失败'} | 新增 {item.get('new', 0)} | {item.get('detail', '')}"
                for item in reversed(history)
            ]
        else:
            lines = ["暂无监控历史。"]

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"监控历史：{account.display_name or account.douyin_nickname or account.account_id}"),
            content=ft.Column(
                controls=[ft.Text("\n".join(lines), selectable=True, size=12)],
                tight=True,
                width=720,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def download_all(self, account_id: str, confirmed: bool = False, filter_mode: str = "all"):
        self.selected_account_id = account_id
        account = self.manager.find_account(account_id)
        if not account:
            await self.app.snack_bar.show_snack_bar("账号不存在", bgcolor=ft.Colors.ERROR)
            return
        if self.download_in_progress:
            await self.app.snack_bar.show_snack_bar("已有下载任务正在进行", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            name = account.display_name or account.account_id
            items = self._filter_download_items(account, filter_mode)
            count = len(items)
            detail = f"将下载账号“{name}”的{self._download_filter_label(filter_mode)}"
            if count:
                detail += f"（当前已同步 {count} 个）"
            else:
                detail += "（当前没有匹配作品）"
            self.show_confirm_dialog(
                "确认下载",
                f"{detail}，是否继续？",
                lambda: self.download_all(account_id, confirmed=True, filter_mode=filter_mode),
            )
            return
        self.download_in_progress = True
        self.download_stop_requested = False
        await self.set_loading(True)
        await self.render_current_view()
        try:
            if not account.items:
                sync_result = await self.manager.sync_account_works(account_id)
                if not sync_result.get("success"):
                    await self.refresh_view()
                    await self.app.snack_bar.show_snack_bar(
                        sync_result.get("reason") or "同步作品失败",
                        bgcolor=ft.Colors.ERROR,
                        duration=6000,
                        show_close_icon=True,
                    )
                    return
            item_ids = [item.item_id for item in self._filter_download_items(account, filter_mode)]
            if not item_ids:
                await self.app.snack_bar.show_snack_bar("没有匹配的作品可下载", bgcolor=ft.Colors.ERROR)
                return
            success, failed, stopped = await self._download_items_until_stopped(account_id, item_ids)
            await self.refresh_view()
            prefix = "下载已停止" if stopped else "下载完成"
            await self.app.snack_bar.show_snack_bar(
                f"{prefix}：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            self.download_in_progress = False
            self.download_stop_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    def _filter_download_items(self, account, filter_mode: str):
        items = [item for item in self.manager.sort_items_newest_first(account.items) if item.status != "count_only"]
        mode = str(filter_mode or "all").lower()
        if mode == "new":
            return [item for item in items if item.status == "new"]
        if mode == "pending":
            return [item for item in items if item.status not in {"downloaded", "download_failed"}]
        if mode == "failed":
            return [item for item in items if item.status == "download_failed"]
        if mode == "downloaded":
            return [item for item in items if item.status == "downloaded"]
        if mode == "gallery":
            return [item for item in items if self._is_gallery_item(item)]
        if mode == "video":
            return [item for item in items if not self._is_gallery_item(item)]
        return items

    @staticmethod
    def _download_filter_label(filter_mode: str) -> str:
        mapping = {
            "new": "新作品",
            "pending": "未下载作品",
            "downloaded": "已下载作品",
            "failed": "下载失败作品",
            "gallery": "图集作品",
            "video": "视频作品",
        }
        return mapping.get(str(filter_mode or "all").lower(), "全部作品")

    async def toggle_monitor(self, account_id: str, currently_enabled: bool):
        if currently_enabled:
            await self.manager.stop_monitor(account_id)
            msg = self._.get("stop_success", "已停止监控")
        else:
            await self.manager.start_monitor(account_id)
            msg = self._.get("start_success", "已开始监控")
        await self.refresh_view()
        await self.app.snack_bar.show_snack_bar(msg, bgcolor=ft.Colors.PRIMARY)

    async def check_all_enabled_on_click(self):
        enabled_accounts = [account for account in self.manager.accounts if account.monitor_enabled]
        if not enabled_accounts:
            await self.app.snack_bar.show_snack_bar("没有启用监控的账号", bgcolor=ft.Colors.ERROR)
            return
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return
        self.batch_job_running = True
        self.batch_cancel_requested = False
        await self.set_loading(True)
        task_center = getattr(self.app.services, "task_center", None)
        task_id = task_center.start("检测全部监控账号", "内容监控", total=len(enabled_accounts)) if task_center else None
        success = 0
        failed = 0
        lines = []
        cancelled = False
        try:
            for index, account in enumerate(enabled_accounts, start=1):
                if self.batch_cancel_requested:
                    cancelled = True
                    lines.append("[取消] 用户已取消检测全部监控")
                    break
                result = await self.manager.check_account(account.account_id, notify=True)
                name = account.display_name or account.douyin_nickname or account.account_id
                if result.get("success"):
                    success += 1
                    lines.append(f"[成功] {name}：{result.get('reason') or '检测完成'}")
                else:
                    failed += 1
                    lines.append(f"[失败] {name}：{result.get('reason') or '检测失败'}")
                if task_center and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"检测进度：{index}/{len(enabled_accounts)}，成功 {success}，失败 {failed}",
                    )
                await self.refresh_view()
            if task_center and task_id:
                detail = f"检测已取消：成功 {success}，失败 {failed}" if cancelled else f"检测完成：成功 {success}，失败 {failed}"
                if cancelled and hasattr(task_center, "cancel"):
                    task_center.cancel(task_id, detail)
                else:
                    task_center.finish(task_id, success=(failed == 0 and not cancelled), detail=detail)
            self.batch_result_lines = lines[-200:]
            await self.app.snack_bar.show_snack_bar(
                f"{'检测已取消' if cancelled else '检测完成'}：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 and not cancelled else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            self.batch_job_running = False
            self.batch_cancel_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    async def sync_all_accounts_on_click(self):
        accounts = list(self.manager.accounts)
        if not accounts:
            await self.app.snack_bar.show_snack_bar("没有可同步的账号", bgcolor=ft.Colors.ERROR)
            return
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return
        self.batch_job_running = True
        self.batch_cancel_requested = False
        await self.set_loading(True)
        task_center = getattr(self.app.services, "task_center", None)
        task_id = task_center.start("同步全部账号作品", "作品监控", total=len(accounts)) if task_center else None
        success = 0
        failed = 0
        new_total = 0
        lines = []
        cancelled = False
        try:
            for index, account in enumerate(accounts, start=1):
                if self.batch_cancel_requested:
                    cancelled = True
                    lines.append("[取消] 用户已取消同步全部作品")
                    break
                result = await self.manager.sync_account_works(account.account_id)
                name = account.display_name or account.douyin_nickname or account.account_id
                if result.get("success"):
                    success += 1
                    lines.append(f"[成功] {name}：{result.get('reason') or '同步完成'}，新增 {result.get('new') or 0}")
                    try:
                        new_total += int(result.get("new") or 0)
                    except (TypeError, ValueError):
                        pass
                else:
                    failed += 1
                    lines.append(f"[失败] {name}：{result.get('reason') or '同步失败'}")
                if task_center and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"同步进度：{index}/{len(accounts)}，成功 {success}，失败 {failed}，新增 {new_total}",
                    )
                await self.refresh_view()
            if task_center and task_id:
                detail = f"同步已取消：成功 {success}，失败 {failed}，新增 {new_total}" if cancelled else f"同步完成：成功 {success}，失败 {failed}，新增 {new_total}"
                if cancelled and hasattr(task_center, "cancel"):
                    task_center.cancel(task_id, detail)
                else:
                    task_center.finish(task_id, success=(failed == 0 and not cancelled), detail=detail)
            self.batch_result_lines = lines[-200:]
            await self.app.snack_bar.show_snack_bar(
                f"{'同步已取消' if cancelled else '同步完成'}：成功 {success}，失败 {failed}，新增 {new_total}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 and not cancelled else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            self.batch_job_running = False
            self.batch_cancel_requested = False
            await self.set_loading(False)
            await self.render_current_view()

    async def batch_start_on_click(self, _e=None):
        await self.set_loading(True)
        try:
            result = await self.manager.start_all()
            await self.refresh_view()
            await self.app.snack_bar.show_snack_bar(
                self._.get("batch_start_success", "批量开始监控完成：{total} 个").format(total=result.get("total", 0)),
                bgcolor=ft.Colors.PRIMARY,
            )
        finally:
            await self.set_loading(False)

    async def batch_stop_on_click(self, _e=None):
        await self.set_loading(True)
        try:
            result = await self.manager.stop_all()
            await self.refresh_view()
            await self.app.snack_bar.show_snack_bar(
                self._.get("batch_stop_success", "批量停止监控完成：{total} 个").format(total=result.get("total", 0)),
                bgcolor=ft.Colors.PRIMARY,
            )
        finally:
            await self.set_loading(False)

    async def delete_account(self, account_id: str, confirmed: bool = False):
        if not confirmed:
            account = self.manager.find_account(account_id)
            name = account.display_name or account.douyin_nickname or account.homepage_url if account else account_id
            self.show_confirm_dialog(
                "确认删除账号",
                f"将删除账号 {name} 及其监控记录，是否继续？",
                lambda: self.delete_account(account_id, confirmed=True),
            )
            return
        account = self.manager.find_account(account_id)
        if account:
            self.recent_deleted_accounts = [account.to_dict()]
            self.deleted_account_batches.append(self.recent_deleted_accounts)
            self.deleted_account_batches = self.deleted_account_batches[-10:]
        await self.manager.delete_account(account_id)
        if self.selected_account_id == account_id:
            self.selected_account_id = None
        await self.refresh_view()
        await self.app.snack_bar.show_snack_bar(self._.get("delete_success", "已删除"), bgcolor=ft.Colors.PRIMARY)

    async def restore_recent_deleted_accounts(self):
        restore_data = self.recent_deleted_accounts or (self.deleted_account_batches[-1] if self.deleted_account_batches else [])
        if not restore_data:
            await self.app.snack_bar.show_snack_bar("没有可恢复的账号", bgcolor=ft.Colors.ERROR)
            return
        restored = await self.manager.restore_accounts(restore_data)
        if restored:
            self.recent_deleted_accounts = []
            if self.deleted_account_batches:
                self.deleted_account_batches.pop()
            await self.refresh_view()
            self.safe_content_update()
        await self.app.snack_bar.show_snack_bar(
            f"已恢复 {restored} 个账号" if restored else "没有账号被恢复，可能已存在",
            bgcolor=ft.Colors.PRIMARY if restored else ft.Colors.ERROR,
        )

    async def copy_text(self, text: str):
        await self.copy_to_clipboard(text, success=self._.get("copy_success", "已复制"), failed=self._.get("copy_failed", "复制失败"))

    async def open_url(self, url: str):
        await self.open_path_or_url(url, failed_prefix=self._.get("open_failed", "打开失败"))

    async def export_diagnostics_on_click(self, _e=None):
        try:
            path = export_diagnostic_bundle(self.app.services)
            await self.app.snack_bar.show_snack_bar(
                self._.get("export_success", "诊断包已导出：{path}").format(path=path),
                bgcolor=ft.Colors.PRIMARY,
                duration=5000,
                show_close_icon=True,
            )
        except Exception as exc:
            await self.app.snack_bar.show_snack_bar(f"{self._.get('export_failed', '导出失败')}：{exc}", bgcolor=ft.Colors.ERROR)

    async def open_log_dir_on_click(self, _e=None):
        log_dir = os.path.join(self.app.services.run_path, "logs")
        os.makedirs(log_dir, exist_ok=True)
        await self.open_path_or_url(log_dir, failed_prefix=self._.get("open_failed", "打开失败"))

    async def subscribe_update(self, *_args: Any):
        if getattr(self.app, "current_page_name", "") != self.page_name:
            return
        try:
            await self.refresh_view()
            self.safe_content_update()
            if self.view_mode == "accounts":
                await self.restore_pending_account_scroll_position()
        except Exception as exc:
            logger.debug(f"douyin monitor subscribe refresh failed: {exc}")
