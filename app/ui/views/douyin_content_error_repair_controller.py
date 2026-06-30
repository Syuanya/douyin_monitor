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
from .douyin_content_account_batch_controller import DouyinContentAccountBatchController


class DouyinContentErrorRepairController:
    """Error-repair adapter for the Douyin content monitor page."""

    LABEL_MAP = {
        "cookie": "Cookie/登录态",
        "risk_control": "风控/限流",
        "profile": "主页不可访问",
        "cancelled": "已取消",
        "other": "其他异常",
    }

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def accounts(self) -> list[DouyinMonitorAccount]:
        return [account for account in self.owner.manager.accounts if account.last_error or "异常" in str(account.status)]

    @staticmethod
    def bucket(account: DouyinMonitorAccount) -> str:
        text = f"{getattr(account, 'status', '')} {getattr(account, 'last_error', '')}"
        return DouyinContentAccountBatchController.batch_failure_category(text)

    def summary(self) -> dict[str, int]:
        summary = {"cookie": 0, "risk_control": 0, "profile": 0, "cancelled": 0, "other": 0}
        for account in self.accounts():
            bucket = self.bucket(account)
            summary[bucket] = summary.get(bucket, 0) + 1
        return summary

    def create_panel(self) -> ft.Control:
        owner = self.owner
        accounts = self.accounts()
        summary = self.summary()
        chips = [
            ft.Container(
                content=ft.Text(f"{self.LABEL_MAP.get(key, key)} {count}", size=12),
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=14,
                padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            )
            for key, count in summary.items()
            if count
        ]
        if not chips:
            chips = [ft.Text("当前没有异常账号。", size=12, color=ft.Colors.ON_SURFACE_VARIANT)]
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.ERROR_CONTAINER),
            border_radius=8,
            padding=10,
            bgcolor=ft.Colors.ERROR_CONTAINER,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.HEALTH_AND_SAFETY, color=ft.Colors.ERROR),
                            ft.Text("异常修复中心", weight=ft.FontWeight.BOLD),
                            ft.Text(f"{len(accounts)} 个账号需要处理", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Row(controls=chips, spacing=6, wrap=True),
                    ft.Text("建议先检查 Cookie 和网络；多账号同时失败时，降低并发后再重试。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row(
                        controls=[
                            ft.TextButton("重新检测异常账号", icon=ft.Icons.REFRESH, disabled=not accounts or owner.batch_job_running, on_click=lambda e: owner.run_async(owner.check_error_accounts_on_click())),
                            ft.TextButton("同步异常账号", icon=ft.Icons.CLOUD_SYNC, disabled=not accounts or owner.batch_job_running, on_click=lambda e: owner.run_async(owner.sync_error_accounts_on_click())),
                            ft.TextButton("复制异常摘要", icon=ft.Icons.CONTENT_COPY, disabled=not accounts, on_click=lambda e: owner.run_async(owner.copy_error_summary())),
                        ],
                        spacing=6,
                        wrap=True,
                    ),
                ],
                spacing=6,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    async def open(self) -> None:
        owner = self.owner
        owner.view_mode = "accounts"
        owner.account_filter = "error"
        owner.account_visible_count = owner.account_page_size
        await owner.render_current_view()

    async def check_accounts(self) -> None:
        owner = self.owner
        success, failed, _ = await owner._run_account_batch(
            self.accounts(),
            "重新检测异常账号",
            "异常修复",
            lambda account: owner.manager.check_account(account.account_id, notify=True),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"异常账号检测完成：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def sync_accounts(self) -> None:
        owner = self.owner
        success, failed, new_total = await owner._run_account_batch(
            self.accounts(),
            "同步异常账号作品",
            "异常修复",
            lambda account: owner.manager.sync_account_works(account.account_id),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"异常账号同步完成：成功 {success}，失败 {failed}，新增 {new_total}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def copy_summary(self) -> None:
        owner = self.owner
        accounts = self.accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("当前没有异常账号", bgcolor=ft.Colors.PRIMARY)
            return
        lines = ["异常账号摘要："]
        for account in accounts[:300]:
            bucket = self.bucket(account)
            lines.append(f"[{bucket}] {account.display_name or account.douyin_nickname or account.account_id} | {account.homepage_url} | {account.status} | {account.last_error}")
        await owner.copy_text("\n".join(lines))
