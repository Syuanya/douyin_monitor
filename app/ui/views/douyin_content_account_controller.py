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

class DouyinContentAccountController:
    """Account-card and account-level dialog/action adapter."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def create_card(self, account: Any):
        from ..components.business import douyin_content_cards as content_cards

        return content_cards.create_account_card(self.owner, account)

    async def show_edit_dialog(self, account_id: str) -> None:
        owner = self.owner
        account = owner.manager.find_account(account_id)
        if not account:
            await owner.app.snack_bar.show_snack_bar("账号不存在", bgcolor=ft.Colors.ERROR)
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
            owner.app.dialog_area.update()

        async def submit(_=None):
            try:
                monitor_interval = max(0.0, float((interval_field.value or "0").strip() or 0))
                auto_pause_failures = max(0, int((pause_failures_field.value or "0").strip() or 0))
                keep_recent_count = max(0, int((keep_recent_field.value or "0").strip() or 0))
            except ValueError:
                await owner.app.snack_bar.show_snack_bar("监控策略请输入有效数字", bgcolor=ft.Colors.ERROR)
                return

            ok = await owner.manager.update_account_settings(
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
            await owner.render_current_view()
            await owner.app.snack_bar.show_snack_bar("账号设置已保存" if ok else "账号不存在", bgcolor=ft.Colors.PRIMARY if ok else ft.Colors.ERROR)

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
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()

    async def show_monitor_history_dialog(self, account_id: str) -> None:
        owner = self.owner
        account = owner.manager.find_account(account_id)
        if account is None:
            await owner.app.snack_bar.show_snack_bar("账号不存在", bgcolor=ft.Colors.ERROR)
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
            owner.app.dialog_area.update()

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
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()

    async def toggle_monitor(self, account_id: str, currently_enabled: bool) -> None:
        owner = self.owner
        if currently_enabled:
            await owner.manager.stop_monitor(account_id)
            msg = owner._.get("stop_success", "已停止监控")
        else:
            await owner.manager.start_monitor(account_id)
            msg = owner._.get("start_success", "已开始监控")
        await owner.refresh_view()
        await owner.app.snack_bar.show_snack_bar(msg, bgcolor=ft.Colors.PRIMARY)

    async def delete_account(self, account_id: str, confirmed: bool = False) -> None:
        owner = self.owner
        if not confirmed:
            account = owner.manager.find_account(account_id)
            name = account.display_name or account.douyin_nickname or account.homepage_url if account else account_id
            owner.show_confirm_dialog(
                "确认删除账号",
                f"将删除账号 {name} 及其监控记录，是否继续？",
                lambda: owner.delete_account(account_id, confirmed=True),
            )
            return
        account = owner.manager.find_account(account_id)
        if account:
            owner.recent_deleted_accounts = [account.to_dict()]
            owner.deleted_account_batches.append(owner.recent_deleted_accounts)
            owner.deleted_account_batches = owner.deleted_account_batches[-10:]
        await owner.manager.delete_account(account_id)
        if owner.selected_account_id == account_id:
            owner.selected_account_id = None
        await owner.refresh_view()
        await owner.app.snack_bar.show_snack_bar(owner._.get("delete_success", "已删除"), bgcolor=ft.Colors.PRIMARY)

    async def restore_recent_deleted_accounts(self) -> None:
        owner = self.owner
        restore_data = owner.recent_deleted_accounts or (owner.deleted_account_batches[-1] if owner.deleted_account_batches else [])
        if not restore_data:
            await owner.app.snack_bar.show_snack_bar("没有可恢复的账号", bgcolor=ft.Colors.ERROR)
            return
        restored = await owner.manager.restore_accounts(restore_data)
        if restored:
            owner.recent_deleted_accounts = []
            if owner.deleted_account_batches:
                owner.deleted_account_batches.pop()
            await owner.refresh_view()
            owner.safe_content_update()
        await owner.app.snack_bar.show_snack_bar(
            f"已恢复 {restored} 个账号" if restored else "没有账号被恢复，可能已存在",
            bgcolor=ft.Colors.PRIMARY if restored else ft.Colors.ERROR,
        )
