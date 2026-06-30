from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover
    ft = None  # type: ignore[assignment]


class DouyinContentBatchSettingsController:
    """Batch account settings dialog and persistence adapter.

    The page owns selected-account state and rendering. This controller owns the
    partial-update rules for batch settings so the Flet page no longer embeds
    form state, payload generation and persistence fallback logic.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def selected_accounts(self) -> list[Any]:
        selected = getattr(self.owner, "_selected_accounts", None)
        if callable(selected):
            return list(selected())
        selected_ids = set(getattr(self.owner, "selected_account_ids", set()) or set())
        return [account for account in getattr(self.owner.manager, "accounts", []) if getattr(account, "account_id", "") in selected_ids]

    @staticmethod
    def build_update_payload(*, update_group: bool, group_name: str, update_policy: bool, policy: str, update_notify: bool, notify: str) -> dict[str, Any]:
        return {
            "group_name": str(group_name or "").strip() if update_group else None,
            "auto_download_policy": str(policy or "all") if update_policy else None,
            "notify_enabled": (True if str(notify or "on") == "on" else False) if update_notify else None,
        }

    @staticmethod
    def selected_update_count(payload: dict[str, Any]) -> int:
        return sum(1 for value in payload.values() if value is not None)

    async def apply_settings(self, accounts: list[Any], payload: dict[str, Any]) -> dict[str, int]:
        if not accounts:
            return {"updated": 0, "changed": 0}
        updater = getattr(self.owner.manager, "update_account_settings_batch", None)
        if callable(updater):
            result = await updater([account.account_id for account in accounts], **payload)
            if isinstance(result, dict):
                updated = int(result.get("updated") or 0)
                changed = int(result.get("changed") or updated)
                return {"updated": updated, "changed": changed}
            return {"updated": 0, "changed": 0}

        updated = 0
        changed = 0
        for account in accounts:
            ok = await self.owner.manager.update_account_settings(account.account_id, **payload)
            if ok:
                updated += 1
                changed += 1
        return {"updated": updated, "changed": changed}

    async def show_dialog(self) -> None:
        if ft is None:  # pragma: no cover
            raise RuntimeError("Flet is required to show the batch settings dialog")
        owner = self.owner
        accounts = self.selected_accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return

        update_group_checkbox = ft.Checkbox(label="修改分组", value=False)
        update_policy_checkbox = ft.Checkbox(label="修改自动下载策略", value=False)
        update_notify_checkbox = ft.Checkbox(label="修改通知策略", value=False)
        group_field = ft.TextField(label="统一设置分组", hint_text="勾选“修改分组”后生效；留空可设为未分组", width=420, disabled=True)
        policy_dropdown = ft.Dropdown(
            label="新增作品自动下载",
            value="all",
            width=300,
            disabled=True,
            options=[
                ft.dropdown.Option("none", "不自动下载"),
                ft.dropdown.Option("video", "只下载视频"),
                ft.dropdown.Option("gallery", "只下载图集"),
                ft.dropdown.Option("all", "自动下载全部"),
            ],
        )
        notify_dropdown = ft.Dropdown(
            label="新作品通知",
            value="on",
            width=300,
            disabled=True,
            options=[ft.dropdown.Option("on", "开启通知"), ft.dropdown.Option("off", "关闭通知")],
        )
        status_text = ft.Text("请先勾选要修改的项目，未勾选项目会保持不变。", size=12, color=ft.Colors.ON_SURFACE_VARIANT)

        def update_enabled_controls(_=None):
            group_field.disabled = not bool(update_group_checkbox.value)
            policy_dropdown.disabled = not bool(update_policy_checkbox.value)
            notify_dropdown.disabled = not bool(update_notify_checkbox.value)
            selected_count = sum(1 for item in [update_group_checkbox, update_policy_checkbox, update_notify_checkbox] if item.value)
            status_text.value = (
                f"已选择 {selected_count} 项要修改。未勾选的项目保持不变。"
                if selected_count
                else "请先勾选要修改的项目，未勾选项目会保持不变。"
            )
            try:
                owner.app.dialog_area.update()
            except Exception:
                pass

        update_group_checkbox.on_change = update_enabled_controls
        update_policy_checkbox.on_change = update_enabled_controls
        update_notify_checkbox.on_change = update_enabled_controls

        async def close_dialog(_=None):
            dialog.open = False
            owner.app.dialog_area.update()

        submitting = False

        async def submit(_=None):
            nonlocal submitting
            if submitting:
                return
            payload = self.build_update_payload(
                update_group=bool(update_group_checkbox.value),
                group_name=str(group_field.value or ""),
                update_policy=bool(update_policy_checkbox.value),
                policy=str(policy_dropdown.value or "all"),
                update_notify=bool(update_notify_checkbox.value),
                notify=str(notify_dropdown.value or "on"),
            )
            if self.selected_update_count(payload) <= 0:
                await owner.app.snack_bar.show_snack_bar("没有选择要修改的设置", bgcolor=ft.Colors.ERROR)
                return

            submitting = True
            save_button.disabled = True
            cancel_button.disabled = True
            for control in [update_group_checkbox, update_policy_checkbox, update_notify_checkbox, group_field, policy_dropdown, notify_dropdown]:
                control.disabled = True
            status_text.value = f"正在批量保存 {len(accounts)} 个账号，请勿重复点击..."
            try:
                owner.app.dialog_area.update()
            except Exception:
                pass
            try:
                result = await self.apply_settings(accounts, payload)
                await close_dialog()
                await owner.render_current_view()
                await owner.app.snack_bar.show_snack_bar(
                    f"批量设置已保存：处理 {result['updated']} 个账号，实际变更 {result['changed']} 个",
                    bgcolor=ft.Colors.PRIMARY,
                    duration=5000,
                    show_close_icon=True,
                )
            except Exception as exc:
                submitting = False
                save_button.disabled = False
                cancel_button.disabled = False
                for control in [update_group_checkbox, update_policy_checkbox, update_notify_checkbox]:
                    control.disabled = False
                update_enabled_controls()
                status_text.value = f"保存失败：{exc}"
                try:
                    owner.app.dialog_area.update()
                except Exception:
                    pass
                await owner.app.snack_bar.show_snack_bar(f"批量设置保存失败：{exc}", bgcolor=ft.Colors.ERROR)

        cancel_button = ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=close_dialog)
        save_button = ft.FilledButton("保存选中修改项", icon=ft.Icons.SAVE, on_click=submit)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"批量设置 {len(accounts)} 个账号"),
            content=ft.Column(
                controls=[
                    ft.Text("只会修改已勾选的项目，未勾选项目保持不变，避免误改账号配置。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row([update_group_checkbox, group_field], spacing=8, wrap=True),
                    ft.Row([update_policy_checkbox, policy_dropdown], spacing=8, wrap=True),
                    ft.Row([update_notify_checkbox, notify_dropdown], spacing=8, wrap=True),
                    ft.Row(
                        [ft.Icon(ft.Icons.INFO_OUTLINE, color=ft.Colors.ON_SURFACE_VARIANT, size=18), status_text],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                tight=True,
                spacing=10,
                width=620,
            ),
            actions=[cancel_button, save_button],
        )
        dialog.open = True
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()
