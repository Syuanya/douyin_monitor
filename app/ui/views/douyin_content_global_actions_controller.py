from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()


class DouyinContentGlobalActionsController:
    """Owns page-wide account actions for the Douyin content monitor page."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def enabled_accounts(self) -> list[Any]:
        return [account for account in self.owner.manager.accounts if account.monitor_enabled]

    def all_accounts(self) -> list[Any]:
        return list(self.owner.manager.accounts)

    async def check_all_enabled(self) -> tuple[int, int, int]:
        owner = self.owner
        accounts = self.enabled_accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("没有启用监控的账号", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        success, failed, new_total = await owner.account_batch_controller.run_batch(
            accounts,
            "检测全部监控账号",
            "内容监控",
            lambda account: owner.manager.check_account(account.account_id, notify=True),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"检测完成：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        return success, failed, new_total

    async def sync_all_accounts(self, *, confirmed: bool = False) -> tuple[int, int, int]:
        owner = self.owner
        accounts = self.all_accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("没有可同步的账号", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        if not confirmed:
            owner.show_confirm_dialog(
                "确认同步全部作品",
                f"将请求 {len(accounts)} 个账号的作品明细。该操作比检测更新更重，账号多或网络异常时可能触发风控。建议优先使用“检测更新”。是否继续？",
                lambda: owner.sync_all_accounts_on_click(confirmed=True),
            )
            return 0, 0, 0
        success, failed, new_total = await owner.account_batch_controller.run_batch(
            accounts,
            "同步全部账号作品",
            "作品监控",
            lambda account: owner.manager.sync_account_works(account.account_id),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"同步完成：成功 {success}，失败 {failed}，新增 {new_total}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        return success, failed, new_total

    async def start_all(self) -> int:
        owner = self.owner
        await owner.set_loading(True)
        try:
            result = await owner.manager.start_all()
            total = int(result.get("total", 0)) if isinstance(result, dict) else 0
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                await owner.refresh_view()
            await owner.app.snack_bar.show_snack_bar(
                owner._.get("batch_start_success", "批量开始监控完成：{total} 个").format(total=total),
                bgcolor=ft.Colors.PRIMARY,
            )
            return total
        finally:
            await owner.set_loading(False)

    async def stop_all(self) -> int:
        owner = self.owner
        await owner.set_loading(True)
        try:
            result = await owner.manager.stop_all()
            total = int(result.get("total", 0)) if isinstance(result, dict) else 0
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                await owner.refresh_view()
            await owner.app.snack_bar.show_snack_bar(
                owner._.get("batch_stop_success", "批量停止监控完成：{total} 个").format(total=total),
                bgcolor=ft.Colors.PRIMARY,
            )
            return total
        finally:
            await owner.set_loading(False)
