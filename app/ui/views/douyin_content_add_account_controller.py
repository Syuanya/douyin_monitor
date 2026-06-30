from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"
        ON_SURFACE_VARIANT = "on_surface_variant"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()


class DouyinContentAddAccountController:
    """Owns add-account input flows for the Douyin content monitor page."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    async def add_account_with_auto_name(self, url: str, name: str):
        owner = self.owner
        manual_name = str(name or "").strip()
        account = await owner.manager.add_account(url, manual_name)
        if manual_name:
            return account, "已添加抖音监控用户"

        result = await owner.manager.hydrate_account_display_name(account.account_id, force=True)
        account = owner.manager.find_account(account.account_id) or account
        display_name = account.display_name or account.douyin_nickname or "抖音用户"
        if result.get("success") and display_name != "抖音用户":
            return account, f"已添加抖音监控用户，自动填充昵称：{display_name}"
        return account, "已添加抖音监控用户，暂未获取到昵称，可稍后检测一次自动更新"

    async def add_from_inline_inputs(self) -> None:
        owner = self.owner
        url = owner.url_input.value.strip() if owner.url_input else ""
        name = owner.name_input.value.strip() if owner.name_input else ""
        if not url:
            await owner.app.snack_bar.show_snack_bar(owner._.get("url_required", "请输入抖音主页链接"), bgcolor=ft.Colors.ERROR)
            return
        try:
            account, message = await self.add_account_with_auto_name(url, name)
            owner.selected_account_id = account.account_id
            if owner.url_input:
                owner.url_input.value = ""
            if owner.name_input:
                owner.name_input.value = ""
            await owner.refresh_view()
            owner.safe_content_update()
            await owner.app.snack_bar.show_snack_bar(message, bgcolor=ft.Colors.PRIMARY, duration=4500, show_close_icon=True)
        except Exception as exc:
            await owner.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3000, show_close_icon=True)

    async def show_dialog(self, _e=None) -> None:
        owner = self.owner
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
                owner.app.dialog_area.update()
            except Exception:
                pass

        async def submit(_=None):
            url = (url_field.value or "").strip()
            name = (name_field.value or "").strip()
            if not url:
                await owner.app.snack_bar.show_snack_bar("请输入抖音主页链接", bgcolor=ft.Colors.ERROR)
                return
            try:
                account, message = await self.add_account_with_auto_name(url, name)
                owner.selected_account_id = account.account_id
                owner.account_search_query = ""
                await close_dialog()
                await owner.refresh_view()
                owner.safe_content_update()
                await owner.app.snack_bar.show_snack_bar(message, bgcolor=ft.Colors.PRIMARY, duration=4500, show_close_icon=True)
            except Exception as exc:
                await owner.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3500, show_close_icon=True)

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
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()
