from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

import flet as ft

from ...core.content_monitor.models import DouyinMonitorAccount
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.business import douyin_content_cards as content_cards
from ..components.common.safe_icons import icon
from . import douyin_content_state as content_state
from .douyin_content_bulk_components import build_work_bulk_action_rows
from .douyin_content_account_batch_controller import DouyinContentAccountBatchController
from .douyin_content_account_controller import DouyinContentAccountController
from .douyin_content_add_account_controller import DouyinContentAddAccountController
from .douyin_content_batch_settings_controller import DouyinContentBatchSettingsController
from .douyin_content_batch_import_controller import DouyinContentBatchImportController
from .douyin_content_download_controller import DouyinContentDownloadController
from .douyin_content_download_complete_controller import DouyinContentDownloadCompleteController
from .douyin_content_global_actions_controller import DouyinContentGlobalActionsController
from .douyin_content_insights_controller import DouyinContentInsightsController
from .douyin_content_export_controller import DouyinContentExportController
from .douyin_content_error_repair_controller import DouyinContentErrorRepairController
from .douyin_content_inbox_controller import DouyinContentInboxController
from .douyin_content_preview_controller import DouyinContentPreviewController
from .douyin_content_refresh_coordinator import DouyinContentRefreshCoordinator
from .douyin_content_presenter import account_next_step, account_status_meta, auto_download_policy_label
from .douyin_content_toolbar import build_title_area
from .douyin_content_work_controller import DouyinContentWorkController


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
        self.account_visible_count = content_state.DEFAULT_ACCOUNT_PAGE_SIZE
        self.account_page_size = content_state.DEFAULT_ACCOUNT_PAGE_SIZE
        self._pending_monitor_refresh = False
        self._last_pubsub_refresh_at = 0.0
        self.return_account_anchor_id: str | None = None
        self.pending_account_scroll_anchor_id: str | None = None
        self.account_scroll_anchor_hold_until = 0.0
        self.work_select_mode = False
        self.selected_work_ids: set[str] = set()
        self.work_filter = "all"
        self.visible_work_count = content_state.DEFAULT_WORK_PAGE_SIZE
        self.work_page_size = content_state.DEFAULT_WORK_PAGE_SIZE
        self.inbox_visible_count = content_state.DEFAULT_WORK_PAGE_SIZE
        self.download_in_progress = False
        self.download_stop_requested = False
        self.download_controller = DouyinContentDownloadController(self)
        self.download_complete_controller = DouyinContentDownloadCompleteController(self)
        self.add_account_controller = DouyinContentAddAccountController(self)
        self.account_controller = DouyinContentAccountController(self)
        self.account_batch_controller = DouyinContentAccountBatchController(self)
        self.batch_settings_controller = DouyinContentBatchSettingsController(self)
        self.batch_import_controller = DouyinContentBatchImportController(self)
        self.global_actions_controller = DouyinContentGlobalActionsController(self)
        self.insights_controller = DouyinContentInsightsController(self)
        self.export_controller = DouyinContentExportController(self)
        self.work_controller = DouyinContentWorkController(self)
        self.inbox_controller = DouyinContentInboxController(self)
        self.error_repair_controller = DouyinContentErrorRepairController(self)
        self.preview_controller = DouyinContentPreviewController(self)
        self.refresh_coordinator = DouyinContentRefreshCoordinator(self)
        self.download_progress_text = ""
        self.download_failure_reasons: list[str] = []
        self.batch_result_lines: list[str] = []
        self.batch_progress_text = ""
        self.batch_progress_total = 0
        self.batch_progress_completed = 0
        self.batch_progress_success = 0
        self.batch_progress_failed = 0
        self.batch_progress_new_total = 0
        self.batch_progress_cancelled = False
        self.batch_progress_title = ""
        self.batch_selection_text_control: ft.Text | None = None
        self.batch_progress_text_control: ft.Text | None = None
        self.batch_progress_bar_control: ft.Text | None = None
        self.batch_toolbar_buttons: dict[str, ft.Control] = {}
        self.account_checkbox_controls: dict[str, ft.Checkbox] = {}
        self.batch_job_running = False
        self.batch_cancel_requested = False
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
        return build_title_area(self)

    def _monitor_summary_chip(self) -> ft.Container:
        accounts = list(self.manager.accounts)
        enabled = len([account for account in accounts if account.monitor_enabled])
        new_count = self._pending_new_work_count(accounts)
        error_count = len([account for account in accounts if account.last_error or "异常" in str(account.status)])
        works = sum(len([item for item in getattr(account, "items", []) if not self._is_count_only_item(item)]) for account in accounts)
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

    def _pending_new_work_count(self, accounts: list[DouyinMonitorAccount] | None = None) -> int:
        target_accounts = accounts if accounts is not None else list(self.manager.accounts)
        return content_state.pending_new_work_count(target_accounts)

    @staticmethod
    def _pending_new_work_count_for_account(account: DouyinMonitorAccount) -> int:
        return content_state.pending_new_work_count_for_account(account)

    @staticmethod
    def _is_pending_new_work_item(item: Any) -> bool:
        return content_state.is_pending_new_work_item(item)

    @staticmethod
    def _is_count_only_item(item: Any) -> bool:
        return content_state.is_count_only_item(item)

    @staticmethod
    def _sync_account_last_new_count(account: DouyinMonitorAccount) -> int:
        return content_state.sync_account_last_new_count(account)

    def _account_filter_buttons(self) -> list[ft.Control]:
        new_count = self._pending_new_work_count()
        options = [
            ("all", "全部"),
            ("enabled", "监控中"),
            ("new", f"有新作品 {new_count}"),
            ("error", "异常"),
            ("stopped", "未监控"),
        ]
        return [
            ft.TextButton(
                label,
                icon=ft.Icons.CHECK if self.account_filter == key else None,
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

    def _register_account_checkbox(self, account_id: str, checkbox: ft.Checkbox) -> None:
        self.account_checkbox_controls[str(account_id)] = checkbox

    def _update_account_checkbox_values(self) -> None:
        for account_id, checkbox in list(self.account_checkbox_controls.items()):
            try:
                checkbox.value = account_id in self.selected_account_ids
                checkbox.disabled = bool(self.batch_job_running)
                checkbox.visible = bool(self.account_select_mode)
                checkbox.update()
            except Exception:
                pass

    def _batch_selection_summary(self) -> tuple[int, int, int]:
        visible_accounts = self._visible_accounts()
        visible_ids = {account.account_id for account in visible_accounts}
        return len(self.selected_account_ids & visible_ids), len(visible_accounts), len(self.selected_account_ids)

    def _update_batch_account_toolbar_fast(self) -> None:
        selected_visible, visible_total, selected_total = self._batch_selection_summary()
        running = bool(self.batch_job_running)
        if self.batch_selection_text_control is not None:
            try:
                self.batch_selection_text_control.value = f"批量处理：当前列表已选 {selected_visible}/{visible_total}，总已选 {selected_total}"
                self.batch_selection_text_control.update()
            except Exception:
                pass
        button_rules = {
            "select_all": running,
            "invert": running,
            "clear": running or not selected_total,
            "check": running or not selected_total,
            "sync": running or not selected_total,
            "settings": running or not selected_total,
            "start": running or not selected_total,
            "stop": running or not selected_total,
            "delete": running or not selected_total,
            "cancel": (not running) or self.batch_cancel_requested,
            "close": running,
        }
        for name, disabled in button_rules.items():
            control = self.batch_toolbar_buttons.get(name)
            if control is None:
                continue
            try:
                control.disabled = disabled
                control.update()
            except Exception:
                pass

    def _update_batch_progress_controls(self) -> None:
        visible = bool(self.batch_progress_text or self.batch_job_running)
        if self.batch_progress_text_control is not None:
            try:
                self.batch_progress_text_control.value = self._batch_progress_label()
                self.batch_progress_text_control.visible = visible
                self.batch_progress_text_control.color = ft.Colors.ERROR if self.batch_progress_cancelled else (ft.Colors.PRIMARY if self.batch_job_running else ft.Colors.ON_SURFACE_VARIANT)
                self.batch_progress_text_control.update()
            except Exception:
                pass
        if self.batch_progress_bar_control is not None:
            try:
                self.batch_progress_bar_control.value = self._batch_progress_value()
                self.batch_progress_bar_control.visible = visible
                self.batch_progress_bar_control.update()
            except Exception:
                pass
        self._update_batch_account_toolbar_fast()

    def _set_batch_progress_state(
        self,
        *,
        title: str | None = None,
        completed: int | None = None,
        total: int | None = None,
        success: int | None = None,
        failed: int | None = None,
        new_total: int | None = None,
        current: str = "",
        cancelled: bool | None = None,
        final: bool = False,
    ) -> None:
        if title is not None:
            self.batch_progress_title = title
        if completed is not None:
            self.batch_progress_completed = max(0, int(completed))
        if total is not None:
            self.batch_progress_total = max(0, int(total))
        if success is not None:
            self.batch_progress_success = max(0, int(success))
        if failed is not None:
            self.batch_progress_failed = max(0, int(failed))
        if new_total is not None:
            self.batch_progress_new_total = max(0, int(new_total))
        if cancelled is not None:
            self.batch_progress_cancelled = bool(cancelled)
        status = "已取消" if self.batch_progress_cancelled else ("已完成" if final else "处理中")
        current_text = f"，当前：{current}" if current and not final else ""
        new_text = f"，新增 {self.batch_progress_new_total}" if self.batch_progress_new_total else ""
        self.batch_progress_text = (
            f"{self.batch_progress_title or '批量任务'} {status}："
            f"{self.batch_progress_completed}/{self.batch_progress_total}，"
            f"成功 {self.batch_progress_success}，失败 {self.batch_progress_failed}{new_text}{current_text}"
        )

    def _account_batch_parallel_limit(self) -> int:
        return self.account_batch_controller.parallel_limit()

    def _batch_account_toolbar(self) -> ft.Container:
        visible_accounts = self._visible_accounts()
        visible_ids = {account.account_id for account in visible_accounts}
        selected_visible = len(self.selected_account_ids & visible_ids)
        selected_total = len(self.selected_account_ids)
        running = bool(self.batch_job_running)
        self.batch_selection_text_control = ft.Text(
            f"批量处理：当前列表已选 {selected_visible}/{len(visible_accounts)}，总已选 {selected_total}",
            size=12,
            color=ft.Colors.PRIMARY,
        )
        self.batch_progress_text_control = ft.Text(
            self._batch_progress_label(),
            size=12,
            color=ft.Colors.PRIMARY if running else ft.Colors.ON_SURFACE_VARIANT,
            selectable=True,
            visible=bool(self.batch_progress_text or running),
        )
        self.batch_progress_bar_control = ft.Text(
            self._batch_progress_percent_text(),
            size=12,
            color=ft.Colors.PRIMARY if running else ft.Colors.ON_SURFACE_VARIANT,
            visible=bool(self.batch_progress_text or running),
        )

        def button(name: str, control: ft.Control) -> ft.Control:
            self.batch_toolbar_buttons[name] = control
            return control

        self.batch_toolbar_buttons = {}
        toolbar = ft.Row(
            controls=[
                self.batch_selection_text_control,
                button("select_all", ft.IconButton(icon=ft.Icons.SELECT_ALL, tooltip="全选/取消全选当前列表", disabled=running, on_click=lambda e: self.run_async(self.select_all_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("invert", ft.IconButton(icon=ft.Icons.CHECKLIST, tooltip="反选当前列表", disabled=running, on_click=lambda e: self.run_async(self.invert_visible_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("clear", ft.IconButton(icon=ft.Icons.CLEAR, tooltip="清空选择", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.clear_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("check", ft.IconButton(icon=ft.Icons.REFRESH, tooltip="检测选中", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.check_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("sync", ft.IconButton(icon=ft.Icons.CLOUD_SYNC, tooltip="同步选中", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.sync_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("settings", ft.IconButton(icon=ft.Icons.SETTINGS, tooltip="批量设置", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.show_batch_account_settings_dialog()), icon_color=ft.Colors.PRIMARY)),
                button("start", ft.IconButton(icon=ft.Icons.PLAY_ARROW, tooltip="开始监控", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.start_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("stop", ft.IconButton(icon=ft.Icons.STOP, tooltip="停止监控", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.stop_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("delete", ft.IconButton(icon=ft.Icons.DELETE_OUTLINE, tooltip="删除选中", disabled=running or not selected_total, on_click=lambda e: self.run_async(self.delete_selected_accounts()), icon_color=ft.Colors.PRIMARY)),
                button("cancel", ft.IconButton(icon=ft.Icons.CANCEL, tooltip="取消当前批量任务", disabled=not running or self.batch_cancel_requested, on_click=lambda e: self.run_async(self.cancel_batch_job()), icon_color=ft.Colors.ERROR)),
                button("close", ft.IconButton(icon=ft.Icons.CLOSE, tooltip="退出批量选择", disabled=running, on_click=lambda e: self.run_async(self.toggle_account_select_mode()), icon_color=ft.Colors.PRIMARY)),
            ],
            spacing=6,
            wrap=True,
        )
        progress_row = ft.Row(
            controls=[
                ft.Icon(ft.Icons.HOURGLASS_TOP if running else ft.Icons.INFO_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                self.batch_progress_bar_control,
                ft.TextButton("查看明细", icon=ft.Icons.LIST_ALT, on_click=lambda e: self.run_async(self.show_batch_result_dialog())),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            visible=bool(self.batch_progress_text or running),
        )
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            content=ft.Column(
                controls=[toolbar, self.batch_progress_text_control, progress_row],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    def _batch_progress_label(self) -> str:
        if self.batch_progress_text:
            return self.batch_progress_text
        if self.batch_job_running:
            return "批量任务准备中..."
        return "最近批量任务已完成，可点“查看明细”确认每个账号结果。"

    def _batch_progress_value(self) -> float | None:
        if self.batch_progress_total <= 0:
            return None
        return max(0.0, min(1.0, self.batch_progress_completed / max(1, self.batch_progress_total)))

    def _batch_progress_percent_text(self) -> str:
        if self.batch_progress_total <= 0:
            return "进度：准备中"
        pct = int(round((self.batch_progress_completed / max(1, self.batch_progress_total)) * 100))
        return f"进度：{self.batch_progress_completed}/{self.batch_progress_total}（{pct}%）"

    def _batch_progress_panel(self) -> ft.Container:
        running = bool(self.batch_job_running)
        self.batch_progress_text_control = ft.Text(
            self._batch_progress_label(),
            size=12,
            color=ft.Colors.PRIMARY if running else ft.Colors.ON_SURFACE_VARIANT,
            selectable=True,
        )
        self.batch_progress_bar_control = ft.Text(
            self._batch_progress_percent_text(),
            size=12,
            color=ft.Colors.PRIMARY if running else ft.Colors.ON_SURFACE_VARIANT,
        )
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            content=ft.Column(
                controls=[
                    self.batch_progress_text_control,
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.HOURGLASS_TOP if running else ft.Icons.INFO_OUTLINE, size=16, color=ft.Colors.PRIMARY),
                            self.batch_progress_bar_control,
                            ft.TextButton("查看明细", icon=ft.Icons.LIST_ALT, on_click=lambda e: self.run_async(self.show_batch_result_dialog())),
                            ft.TextButton("停止任务", icon=ft.Icons.CANCEL, disabled=not running or self.batch_cancel_requested, on_click=lambda e: self.run_async(self.cancel_batch_job())),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=4,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
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

    def account_next_check_time(self, account: DouyinMonitorAccount) -> str:
        resolver = getattr(self.manager, "account_next_check_time", None)
        if callable(resolver):
            return str(resolver(account) or "-")
        return "-"

    def _work_summary_panel(self, account: DouyinMonitorAccount | None) -> ft.Control:
        items = list(getattr(account, "items", []) or []) if account is not None else []
        counts = content_state.download_status_counts(items)
        filtered_total = len(self._filter_work_items(items, self.work_filter)) if items else 0
        visible, _next_visible = content_state.display_window(filtered_total, self.visible_work_count, self.work_page_size)
        controls: list[ft.Control] = [
            ft.Icon(ft.Icons.INSIGHTS, size=16, color=ft.Colors.PRIMARY),
            ft.Text(f"当前筛选已显示 {visible}/{filtered_total}", size=12, weight=ft.FontWeight.BOLD),
            ft.Text(f"全部 {counts['total']}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"新作品 {counts['new']}", size=12, color=ft.Colors.PRIMARY if counts['new'] else ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"已下载 {counts['downloaded']}", size=12, color=ft.Colors.GREEN if counts['downloaded'] else ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"失败 {counts['failed']}", size=12, color=ft.Colors.ERROR if counts['failed'] else ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"图集 {counts['gallery']} / 视频 {counts['video']}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if account is not None and counts["failed"]:
            controls.append(
                ft.TextButton(
                    "重试失败",
                    icon=ft.Icons.REPLAY,
                    disabled=self.download_in_progress,
                    on_click=lambda e, account_id=account.account_id: self.run_async(self.download_all(account_id, filter_mode="failed")),
                )
            )
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=6),
            content=ft.Row(controls=controls, spacing=10, wrap=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        )

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
                        self._batch_result_icon_button(),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._work_summary_panel(account),
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
        return self.inbox_controller.create_title_area()

    def _batch_result_icon_button(self) -> ft.IconButton:
        return ft.IconButton(
            icon=ft.Icons.LIST_ALT,
            tooltip="查看最近批量结果",
            on_click=lambda e: self.run_async(self.show_batch_result_dialog()),
            icon_color=ft.Colors.PRIMARY,
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
        controls: list[ft.Control] = []
        if self.account_filter == "error":
            controls.append(self._error_repair_panel())
        controls.append(self.cards_area)
        content: ft.Control = self.cards_area if len(controls) == 1 else ft.Column(controls=controls, spacing=8, expand=True)
        return ft.Container(content=content, expand=True, bgcolor=ft.Colors.SURFACE, padding=ft.Padding.only(top=4))

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
        self.account_checkbox_controls.clear()
        accounts = self._visible_accounts()
        visible_count = max(1, min(len(accounts), int(self.account_visible_count or self.account_page_size)))
        visible_accounts = accounts[:visible_count]
        if not accounts:
            empty_text = self._accounts_empty_text()
            self.cards_area.controls.append(
                ft.Container(
                    content=ft.Text(empty_text, color=ft.Colors.ON_SURFACE_VARIANT),
                    padding=20,
                )
            )
        else:
            self.cards_area.controls.append(
                ft.Container(
                    padding=ft.Padding.symmetric(horizontal=4, vertical=2),
                    content=ft.Text(
                        f"当前显示 {len(visible_accounts)}/{len(accounts)} 个账号；大量账号会分批渲染，减少页面卡顿。",
                        size=12,
                        color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                )
            )
            for account in visible_accounts:
                self.cards_area.controls.append(self.create_account_card(account))
            if visible_count < len(accounts):
                self.cards_area.controls.append(
                    ft.Container(
                        padding=ft.Padding.only(top=4, bottom=12),
                        content=ft.Row(
                            controls=[
                                ft.OutlinedButton(
                                    f"加载更多账号（{min(visible_count + self.account_page_size, len(accounts))}/{len(accounts)}）",
                                    icon=ft.Icons.EXPAND_MORE,
                                    on_click=lambda e: self.run_async(self.load_more_accounts()),
                                ),
                                ft.Text("账号很多时建议先搜索或按分组筛选。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ],
                            wrap=True,
                            spacing=8,
                        ),
                    )
                )
        try:
            self.cards_area.update()
        except Exception:
            pass
        if self.view_mode == "accounts":
            await self.restore_pending_account_scroll_position()

    async def load_more_accounts(self):
        self.account_visible_count = int(self.account_visible_count or self.account_page_size) + self.account_page_size
        await self.refresh_view()
        self.safe_content_update()

    def _accounts_empty_text(self) -> str:
        if not self.manager.accounts:
            return self._.get("empty", "还没有添加抖音主页。")
        if self.account_filter == "new":
            return "当前没有未处理新作品。点击刷新或同步后，有新增作品会出现在“新作品箱”。"
        if self.account_filter == "enabled":
            return "当前筛选没有监控中的账号。"
        if self.account_filter == "error":
            return "当前筛选没有异常账号。"
        if self.account_filter == "stopped":
            return "当前筛选没有未监控账号。"
        if self.account_search_query or self.account_group_filter != "all":
            return "当前筛选条件下没有匹配账号。"
        return self._.get("empty", "还没有添加抖音主页。")

    def _error_accounts(self) -> list[DouyinMonitorAccount]:
        return self.error_repair_controller.accounts()

    def _error_bucket(self, account: DouyinMonitorAccount) -> str:
        return self.error_repair_controller.bucket(account)

    def _error_summary(self) -> dict[str, int]:
        return self.error_repair_controller.summary()

    def _error_repair_panel(self) -> ft.Control:
        return self.error_repair_controller.create_panel()

    def _inbox_summary_panel(self, entries: list[tuple[DouyinMonitorAccount, Any]]) -> ft.Control:
        return self.inbox_controller.summary_panel(entries)

    def _filter_accounts(self, accounts: list[DouyinMonitorAccount]) -> list[DouyinMonitorAccount]:
        return content_state.filter_accounts(accounts, self.account_filter)

    def _visible_accounts(self) -> list[DouyinMonitorAccount]:
        return content_state.visible_accounts(
            list(self.manager.accounts),
            mode=self.account_filter,
            group_filter=self.account_group_filter,
            search_query=self.account_search_query,
        )

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
        return content_state.new_work_entries(self.manager.accounts)

    async def refresh_new_work_inbox(self):
        await self.inbox_controller.refresh()

    def create_inbox_item(self, account: DouyinMonitorAccount, item):
        return content_cards.create_inbox_item(self, account, item)

    @staticmethod
    def _filter_work_items(items: list[Any], mode: str) -> list[Any]:
        return DouyinContentWorkController.filter_items(items, mode)

    def create_account_card(self, account: DouyinMonitorAccount):
        return self.account_controller.create_card(account)

    def create_history_item(self, item):
        return content_cards.create_history_item(self, item)

    def _work_status_chip(self, item) -> ft.Container:
        return content_cards.work_status_chip(self, item)

    @staticmethod
    def _is_gallery_item(item) -> bool:
        return content_state.is_gallery_item(item)

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
        await self.add_account_controller.show_dialog(_e)

    async def show_batch_import_dialog(self):
        await self.batch_import_controller.show_dialog()

    def _ensure_batch_import_picker(self, import_controls) -> None:
        self.batch_import_controller.ensure_file_picker(import_controls)

    def _parse_batch_import_rows(self, text: str, default_group: str = "") -> list[dict[str, str]]:
        return self.batch_import_controller.parse_rows(text, default_group=default_group)

    async def show_text_report_dialog(self, title: str, lines: list[str]) -> None:
        await self.batch_import_controller.show_text_report_dialog(title, lines)

    def _schedule_batch_name_hydration(self, account_ids: list[str]) -> None:
        self.batch_import_controller.schedule_name_hydration(account_ids)

    async def _hydrate_batch_account_names(self, account_ids: list[str]) -> None:
        await self.batch_import_controller.hydrate_account_names(account_ids)

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
            self.account_visible_count = self.account_page_size
            await close_dialog()
            await self.refresh_view()
            self.safe_content_update()

        async def clear(_=None):
            self.account_search_query = ""
            self.account_visible_count = self.account_page_size
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
        await self.account_controller.show_edit_dialog(account_id)

    async def add_account_on_click(self, _e=None):
        await self.add_account_controller.add_from_inline_inputs()

    async def _add_account_with_auto_name(self, url: str, name: str):
        return await self.add_account_controller.add_account_with_auto_name(url, name)

    async def refresh_on_click(self, _e=None):
        await self.refresh_view()
        self.safe_content_update()
        await self.app.snack_bar.show_snack_bar("已刷新本地界面；需要请求抖音请使用“快速检测更新”或“同步作品列表”。", bgcolor=ft.Colors.PRIMARY, duration=3000)

    def _monitor_export_dir(self) -> str:
        return self.export_controller.export_dir()

    async def open_monitor_export_dir(self):
        await self.export_controller.open_export_dir()

    async def export_monitor_csv(self):
        await self.export_controller.export_works_csv()

    async def export_monitor_accounts_csv(self):
        await self.export_controller.export_accounts_csv()

    async def set_account_filter(self, mode: str):
        self.account_filter = str(mode or "all")
        self.account_visible_count = self.account_page_size
        await self.render_current_view()

    async def set_account_group_filter(self, group: str):
        self.account_group_filter = str(group or "all")
        self.account_visible_count = self.account_page_size
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
        await self.inbox_controller.open()

    async def open_error_repair_center(self):
        await self.error_repair_controller.open()

    async def check_error_accounts_on_click(self):
        await self.error_repair_controller.check_accounts()

    async def sync_error_accounts_on_click(self):
        await self.error_repair_controller.sync_accounts()

    async def copy_error_summary(self):
        await self.error_repair_controller.copy_summary()

    async def back_to_accounts(self):
        anchor_id = self.return_account_anchor_id or self.selected_account_id
        self.pending_account_scroll_anchor_id = anchor_id
        self.account_scroll_anchor_hold_until = time.monotonic() + 3.0
        self.view_mode = "accounts"
        self.work_select_mode = False
        self.selected_work_ids.clear()
        await self.render_current_view()

    async def preview_inbox_item(self, account_id: str, item_id: str, is_gallery: bool):
        await self.inbox_controller.preview_item(account_id, item_id, is_gallery)

    async def download_inbox_item(self, account_id: str, item_id: str):
        await self.inbox_controller.download_item(account_id, item_id)

    async def download_new_inbox_items(self):
        await self.inbox_controller.download_all()

    async def mark_item_seen(self, account_id: str, item_id: str):
        await self.inbox_controller.mark_item_seen(account_id, item_id)

    async def mark_all_new_items_seen(self):
        await self.inbox_controller.mark_all_seen()

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
            scroll_to = getattr(self.cards_area, "scroll_to", None)
            if callable(scroll_to) and "key" in inspect.signature(scroll_to).parameters:
                result = scroll_to(
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
        if self.view_mode == "inbox":
            self.inbox_visible_count += self.work_page_size
            self.inbox_visible_count -= self.work_page_size
        await self.work_controller.load_more()

    async def toggle_account_select_mode(self):
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("批量任务运行中，结束或取消后再退出批量选择", bgcolor=ft.Colors.ERROR)
            return
        self.account_select_mode = not self.account_select_mode
        if not self.account_select_mode:
            self.selected_account_ids.clear()
        await self.render_current_view()

    async def toggle_account_selected(self, account_id: str, selected: bool | None = None):
        if self.batch_job_running:
            self._update_account_checkbox_values()
            await self.app.snack_bar.show_snack_bar("批量任务运行中，暂不能修改选择", bgcolor=ft.Colors.ERROR)
            return
        should_select = account_id not in self.selected_account_ids if selected is None else selected
        if should_select:
            self.selected_account_ids.add(account_id)
        else:
            self.selected_account_ids.discard(account_id)
        checkbox = self.account_checkbox_controls.get(account_id)
        if checkbox is not None:
            try:
                checkbox.value = account_id in self.selected_account_ids
                checkbox.update()
            except Exception:
                pass
        self._update_batch_account_toolbar_fast()

    async def select_all_accounts(self):
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("批量任务运行中，暂不能修改选择", bgcolor=ft.Colors.ERROR)
            return
        account_ids = {account.account_id for account in self._visible_accounts()}
        if self.selected_account_ids >= account_ids and account_ids:
            self.selected_account_ids.difference_update(account_ids)
        else:
            self.selected_account_ids.update(account_ids)
        self._update_account_checkbox_values()
        self._update_batch_account_toolbar_fast()

    async def invert_visible_accounts(self):
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("批量任务运行中，暂不能修改选择", bgcolor=ft.Colors.ERROR)
            return
        for account in self._visible_accounts():
            if account.account_id in self.selected_account_ids:
                self.selected_account_ids.discard(account.account_id)
            else:
                self.selected_account_ids.add(account.account_id)
        self._update_account_checkbox_values()
        self._update_batch_account_toolbar_fast()

    async def clear_selected_accounts(self):
        if self.batch_job_running:
            await self.app.snack_bar.show_snack_bar("批量任务运行中，暂不能修改选择", bgcolor=ft.Colors.ERROR)
            return
        self.selected_account_ids.clear()
        self._update_account_checkbox_values()
        self._update_batch_account_toolbar_fast()

    def _selected_accounts(self) -> list[DouyinMonitorAccount]:
        return self.account_batch_controller.selected_accounts()

    async def show_batch_account_settings_dialog(self):
        await self.batch_settings_controller.show_dialog()

    async def _run_selected_account_job(self, title: str, category: str, job) -> tuple[int, int, int]:
        return await self.account_batch_controller.run_selected_job(title, category, job)

    async def _run_account_batch(self, accounts: list[DouyinMonitorAccount], title: str, category: str, job) -> tuple[int, int, int]:
        return await self.account_batch_controller.run_batch(accounts, title, category, job)

    async def cancel_batch_job(self):
        await self.account_batch_controller.cancel_batch_job()

    async def show_batch_result_dialog(self):
        lines = self._latest_batch_result_lines()
        if not lines:
            await self.app.snack_bar.show_snack_bar("暂无批量操作明细", bgcolor=ft.Colors.PRIMARY)
            return
        self.batch_result_lines = lines[-200:]

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

    def _latest_batch_result_lines(self) -> list[str]:
        # task_center snapshot(limit=30) fallback is implemented in the account batch controller.
        return self.account_batch_controller.latest_batch_result_lines()

    @staticmethod
    def _is_batch_task_record(record: dict[str, Any]) -> bool:
        return DouyinContentAccountBatchController.is_batch_task_record(record)

    async def start_selected_accounts(self):
        await self.account_batch_controller.start_selected_accounts()

    async def stop_selected_accounts(self, confirmed: bool = False):
        await self.account_batch_controller.stop_selected_accounts(confirmed=confirmed)

    async def check_selected_accounts(self):
        await self.account_batch_controller.check_selected_accounts()

    async def sync_selected_accounts(self):
        await self.account_batch_controller.sync_selected_accounts()

    async def delete_selected_accounts(self, confirmed: bool = False):
        await self.account_batch_controller.delete_selected_accounts(confirmed=confirmed)

    async def toggle_work_select_mode(self):
        await self.work_controller.toggle_select_mode()

    async def toggle_work_selected(self, item_id: str, selected: bool | None = None):
        await self.work_controller.toggle_selected(item_id, selected=selected)

    async def clear_selected_works(self):
        await self.work_controller.clear_selected()

    async def select_all_visible_works(self):
        await self.work_controller.select_all_visible()

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
        return await self.download_controller.run_items_until_stopped(account_id, item_ids)

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
        return self.download_controller.parallel_limit()

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
            if result.get("success") and result.get("path"):
                self.show_download_complete_dialog(str(result.get("path") or ""), str(result.get("reason") or "下载完成"), result.get("files") or [])
        finally:
            await self.set_loading(False)

    def show_download_complete_dialog(self, path: str, reason: str = "下载完成", files: list[str] | None = None) -> None:
        self.download_complete_controller.show_dialog(path, reason, files)

    async def open_download_location(self, path: str) -> None:
        await self.preview_controller.open_download_location(path)

    @staticmethod
    def _download_location(path: str) -> str:
        return DouyinContentDownloadController.download_location(path)

    async def open_item_download_location(self, item_id: str):
        await self.preview_controller.open_item_download_location(item_id)

    async def open_inbox_item_download_location(self, account_id: str, item_id: str):
        await self.preview_controller.open_item_download_location(item_id, account_id=account_id)

    async def browse_video(self, item_id: str):
        await self.preview_controller.browse_video(item_id)

    async def preview_item_images(self, item_id: str, selected_index: int = 0):
        await self.preview_controller.preview_item_images(item_id, selected_index=selected_index)

    def show_image_preview_dialog(self, title: str, urls: list[str], selected_index: int, item_id: str) -> None:
        self.preview_controller.show_image_preview_dialog(title, urls, selected_index)

    @staticmethod
    def _format_size(size: int | float | str) -> str:
        return DouyinContentPreviewController.format_size(size)

    async def show_work_detail(self, item_id: str):
        await self.preview_controller.show_work_detail(item_id)

    async def show_monitor_history_dialog(self, account_id: str):
        await self.account_controller.show_monitor_history_dialog(account_id)

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
        return self.download_controller.filter_items(account, filter_mode)

    @staticmethod
    def _download_filter_label(filter_mode: str) -> str:
        return DouyinContentDownloadController.filter_label(filter_mode)

    async def toggle_monitor(self, account_id: str, currently_enabled: bool):
        await self.account_controller.toggle_monitor(account_id, currently_enabled)

    @staticmethod
    def _batch_failure_category(reason: str) -> str:
        return DouyinContentAccountBatchController.batch_failure_category(reason)

    @classmethod
    def _batch_failure_advice(cls, reason: str) -> str:
        return DouyinContentAccountBatchController.batch_failure_advice(reason)

    @classmethod
    def _risk_failure_count(cls, results: list[dict[str, Any]]) -> int:
        return len([item for item in results if not item.get("success") and cls._batch_failure_category(str(item.get("reason") or "")) == "risk_control"])


    async def show_content_health_dashboard(self):
        await self.insights_controller.show_health_dashboard()

    async def show_content_group_statistics(self):
        await self.insights_controller.show_group_statistics()

    async def show_content_material_collection(self):
        await self.insights_controller.show_material_collection()

    async def show_content_digest(self, days: int = 1):
        await self.insights_controller.show_digest(days=days)

    async def export_content_material_links(self):
        await self.insights_controller.export_default_material_links()

    async def check_all_enabled_on_click(self):
        await self.global_actions_controller.check_all_enabled()

    async def sync_all_accounts_on_click(self, confirmed: bool = False):
        await self.global_actions_controller.sync_all_accounts(confirmed=confirmed)

    async def batch_start_on_click(self, _e=None):
        await self.global_actions_controller.start_all()

    async def batch_stop_on_click(self, _e=None):
        await self.global_actions_controller.stop_all()

    async def delete_account(self, account_id: str, confirmed: bool = False):
        await self.account_controller.delete_account(account_id, confirmed=confirmed)

    async def restore_recent_deleted_accounts(self):
        await self.account_controller.restore_recent_deleted_accounts()

    async def copy_text(self, text: str):
        await self.copy_to_clipboard(text, success=self._.get("copy_success", "已复制"), failed=self._.get("copy_failed", "复制失败"))

    async def open_url(self, url: str):
        await self.open_path_or_url(url, failed_prefix=self._.get("open_failed", "打开失败"))

    async def export_diagnostics_on_click(self, _e=None):
        await self.export_controller.export_diagnostics()

    async def open_log_dir_on_click(self, _e=None):
        await self.export_controller.open_log_dir()

    async def subscribe_update(self, *_args: Any):
        # Backward-compatible static contract: refresh coordination still defers when
        # if self.batch_job_running or self.download_in_progress, and it still uses
        # now - self._last_pubsub_refresh_at < 0.8 with self._pending_monitor_refresh = True.
        if getattr(self.app, "current_page_name", "") != self.page_name:
            return
        event = _args[-1] if _args and isinstance(_args[-1], dict) else {}
        try:
            await self.refresh_coordinator.handle_pubsub(event)
        except Exception as exc:
            logger.debug(f"douyin monitor subscribe refresh failed: {exc}")
