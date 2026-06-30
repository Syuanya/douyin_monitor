from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"
        ON_SURFACE_VARIANT = "on_surface_variant"
        OUTLINE_VARIANT = "outline_variant"
        ERROR_CONTAINER = "error_container"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()

from ...core.content_monitor.models import DouyinMonitorAccount
from . import douyin_content_state as content_state


class DouyinContentInboxController:
    """New-work inbox adapter for the Douyin content monitor page.

    The page owns rendering containers and common actions. This controller owns
    the inbox entry selection, summary, page-window refresh and mark/download
    workflows, keeping the new-work semantics in one place.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def entries(self) -> list[tuple[DouyinMonitorAccount, Any]]:
        return content_state.new_work_entries(self.owner.manager.accounts)

    def create_title_area(self) -> ft.Control:
        owner = self.owner
        items = self.entries()
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.ARROW_BACK,
                            tooltip="返回账号列表",
                            on_click=lambda e: owner.run_async(owner.back_to_accounts()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.Text("新作品收件箱", theme_style=ft.TextThemeStyle.TITLE_MEDIUM, expand=True),
                        ft.Text(f"{len(items)} 个新作品", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        owner.loading_indicator,
                        owner._batch_result_icon_button(),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self.summary_panel(items),
                ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.CLOUD_SYNC,
                            tooltip="同步作品列表：请求作品明细、封面和下载信息",
                            on_click=lambda e: owner.run_async(owner.sync_all_accounts_on_click()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DOWNLOAD,
                            tooltip="下载全部新作品",
                            disabled=owner.download_in_progress or not items,
                            on_click=lambda e: owner.run_async(owner.download_new_inbox_items()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DONE_ALL,
                            tooltip="标记全部新作品为已处理",
                            disabled=not items,
                            on_click=lambda e: owner.run_async(owner.mark_all_new_items_seen()),
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

    def summary_panel(self, entries: list[tuple[DouyinMonitorAccount, Any]]) -> ft.Control:
        owner = self.owner
        total = len(entries)
        downloaded = len([item for _account, item in entries if getattr(item, "status", "") == content_state.DOWNLOADED_STATUS])
        failed = len([item for _account, item in entries if getattr(item, "status", "") == content_state.DOWNLOAD_FAILED_STATUS])
        count_only = len([item for _account, item in entries if content_state.is_count_only_item(item)])
        pending = max(0, total - downloaded - failed)
        visible, _next_visible = content_state.display_window(total, owner.inbox_visible_count, owner.work_page_size)
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=10,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.INBOX, color=ft.Colors.PRIMARY),
                    ft.Text(f"待处理 {pending}", weight=ft.FontWeight.BOLD),
                    ft.Text(f"已显示 {visible}/{total}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"已下载 {downloaded}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"失败 {failed}", size=12, color=ft.Colors.ERROR if failed else ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"数量变化提示 {count_only}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text("优先处理失败项和数量变化提示；下载后可批量标记已处理。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=10,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    async def open(self) -> None:
        owner = self.owner
        owner.view_mode = "inbox"
        owner.work_select_mode = False
        owner.selected_work_ids.clear()
        owner.inbox_visible_count = owner.work_page_size
        await owner.render_current_view()

    async def refresh(self) -> None:
        owner = self.owner
        if owner.history_area is None:
            return
        owner.history_area.controls.clear()
        entries = self.entries()
        if not entries:
            owner.history_area.controls.append(
                ft.Container(
                    padding=18,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    content=ft.Column(
                        controls=[
                            ft.Text("暂无未处理新作品", weight=ft.FontWeight.BOLD),
                            ft.Text("同步或检测监控账号后，新增作品和数量变化提示会集中显示在这里。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=6,
                    ),
                )
            )
            return
        for account, item in entries[: owner.inbox_visible_count]:
            owner.history_area.controls.append(owner.create_inbox_item(account, item))
        if owner.inbox_visible_count < len(entries):
            owner.history_area.controls.append(
                ft.OutlinedButton(
                    f"加载更多（{min(owner.inbox_visible_count + owner.work_page_size, len(entries))}/{len(entries)}）",
                    icon=ft.Icons.EXPAND_MORE,
                    on_click=lambda e: owner.run_async(owner.load_more_works()),
                )
            )

    async def preview_item(self, account_id: str, item_id: str, is_gallery: bool) -> None:
        owner = self.owner
        previous_account = owner.selected_account_id
        previous_mode = owner.view_mode
        owner.selected_account_id = account_id
        try:
            if is_gallery:
                await owner.preview_item_images(item_id)
            else:
                await owner.browse_video(item_id)
        finally:
            owner.selected_account_id = previous_account
            owner.view_mode = previous_mode

    async def download_item(self, account_id: str, item_id: str) -> None:
        owner = self.owner
        previous_account = owner.selected_account_id
        previous_mode = owner.view_mode
        owner.selected_account_id = account_id
        try:
            await owner.download_one(item_id)
        finally:
            owner.selected_account_id = previous_account
            owner.view_mode = previous_mode
            await owner.render_current_view()

    async def download_all(self) -> None:
        owner = self.owner
        entries = self.entries()
        if not entries:
            await owner.app.snack_bar.show_snack_bar("暂无新作品可下载", bgcolor=ft.Colors.PRIMARY)
            return
        grouped: dict[str, list[str]] = {}
        for account, item in entries:
            grouped.setdefault(account.account_id, []).append(item.item_id)
        owner.download_in_progress = True
        owner.download_stop_requested = False
        await owner.set_loading(True)
        try:
            success = 0
            failed = 0
            stopped = False
            for account_id, item_ids in grouped.items():
                part_success, part_failed, part_stopped = await owner._download_items_until_stopped(account_id, item_ids)
                success += part_success
                failed += part_failed
                stopped = stopped or part_stopped
                if stopped:
                    break
            await owner.app.snack_bar.show_snack_bar(
                f"{'下载已停止' if stopped else '新作品下载完成'}：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            owner.download_in_progress = False
            owner.download_stop_requested = False
            await owner.set_loading(False)
            await owner.render_current_view()

    async def mark_item_seen(self, account_id: str, item_id: str) -> None:
        owner = self.owner
        if hasattr(owner.manager, "mark_items_seen_batch"):
            await owner.manager.mark_items_seen_batch([(account_id, item_id)])
        else:
            account = owner.manager.find_account(account_id)
            item = next((candidate for candidate in getattr(account, "items", []) if candidate.item_id == item_id), None) if account else None
            if item is None:
                return
            if content_state.is_count_only_item(item):
                account.items = [candidate for candidate in getattr(account, "items", []) if candidate.item_id != item_id]
            elif item.status in {"new", content_state.DOWNLOAD_FAILED_STATUS}:
                item.status = "active"
            content_state.sync_account_last_new_count(account)
            await owner.manager.persist(force=True)
        await owner.render_current_view()
        await owner.app.snack_bar.show_snack_bar("已标记为已处理", bgcolor=ft.Colors.PRIMARY)

    async def mark_all_seen(self) -> None:
        owner = self.owner
        pairs = [(account.account_id, item.item_id) for account, item in list(self.entries())]
        if hasattr(owner.manager, "mark_items_seen_batch"):
            result = await owner.manager.mark_items_seen_batch(pairs)
            changed = int(result.get("changed", 0) or 0)
        else:
            changed = 0
            touched_accounts: set[str] = set()
            for account, item in list(self.entries()):
                if content_state.is_count_only_item(item):
                    account.items = [candidate for candidate in getattr(account, "items", []) if candidate.item_id != item.item_id]
                    changed += 1
                    touched_accounts.add(account.account_id)
                elif item.status in {"new", content_state.DOWNLOAD_FAILED_STATUS}:
                    item.status = "active"
                    changed += 1
                    touched_accounts.add(account.account_id)
            if touched_accounts:
                for account in owner.manager.accounts:
                    if account.account_id in touched_accounts:
                        content_state.sync_account_last_new_count(account)
                await owner.manager.persist(force=True)
        await owner.render_current_view()
        await owner.app.snack_bar.show_snack_bar(f"已标记 {changed} 个新作品为已处理", bgcolor=ft.Colors.PRIMARY)
