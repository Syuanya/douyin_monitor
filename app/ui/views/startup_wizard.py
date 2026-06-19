from __future__ import annotations

import os

import flet as ft

from ...core.media.cookie_utils import sanitize_cookie_header


class StartupWizard:
    def __init__(self, app):
        self.app = app
        self.account_url_field = ft.TextField(label="抖音主页链接", hint_text="https://www.douyin.com/user/...")
        self.account_name_field = ft.TextField(label="备注名称", hint_text="可选")
        self.douyin_cookie_field = ft.TextField(label="抖音 Cookie", password=True, multiline=True, min_lines=3, max_lines=5)
        self.parse_test_field = ft.TextField(label="测试解析链接", hint_text="粘贴一个抖音分享链接用于测试，可选")
        run_path = getattr(app, "run_path", os.getcwd())
        self.download_path_field = ft.TextField(
            label="下载目录",
            value=os.path.join(run_path, "downloads", "douyin_content"),
        )
        self.dialog: ft.AlertDialog | None = None

    async def maybe_show(self) -> bool:
        settings = self.app.services.settings_config
        if bool(settings.user_config.get("onboarding_completed", False)):
            return False
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("首次启动向导"),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text("基础配置", weight=ft.FontWeight.BOLD),
                            ft.IconButton(
                                icon=ft.Icons.INFO_OUTLINE,
                                tooltip="完成基础配置后再开始监控。首次扫描只建立基线，不会把历史作品全部当作新作品通知。",
                            ),
                        ],
                        spacing=4,
                    ),
                    self.account_url_field,
                    self.account_name_field,
                    self.douyin_cookie_field,
                    self.parse_test_field,
                    ft.OutlinedButton("测试解析", icon=ft.Icons.TRAVEL_EXPLORE, on_click=lambda e: self.app.page.run_task(self.test_parse)),
                    self.download_path_field,
                    ft.IconButton(
                        icon=ft.Icons.INFO_OUTLINE,
                        tooltip="建议先填写 Cookie，再测试解析或添加账号。下载目录可后续在设置页修改。",
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                ],
                width=560,
                spacing=10,
                tight=True,
            ),
            actions=[
                ft.TextButton("稍后再说", on_click=lambda e: self.app.page.run_task(self.skip)),
                ft.FilledButton("完成配置", icon=ft.Icons.CHECK, on_click=lambda e: self.app.page.run_task(self.finish)),
            ],
        )
        self.dialog.open = True
        self.app.dialog_area.content = self.dialog
        self.app.dialog_area.update()
        return True

    async def test_parse(self, _=None) -> None:
        text = (self.parse_test_field.value or "").strip()
        if not text:
            await self.app.snack_bar.show_snack_bar("请先填写测试解析链接", bgcolor=ft.Colors.ERROR)
            return
        try:
            result = await self.app.services.video_parser.parse_text(text)
            if getattr(result, "success_count", 0):
                await self.app.snack_bar.show_snack_bar("解析测试成功", bgcolor=ft.Colors.PRIMARY)
            else:
                await self.app.snack_bar.show_snack_bar("解析测试未成功，请检查 Cookie 或链接", bgcolor=ft.Colors.ERROR)
        except Exception as exc:
            await self.app.snack_bar.show_snack_bar(f"解析测试失败：{exc}", bgcolor=ft.Colors.ERROR)

    async def skip(self, _=None) -> None:
        settings = self.app.services.settings_config
        user_config = dict(settings.user_config)
        user_config["onboarding_completed"] = True
        settings.adopt_user_config(user_config)
        await self.app.services.config_manager.save_user_config(user_config)
        self._close()

    async def finish(self, _=None) -> None:
        settings = self.app.services.settings_config
        user_config = dict(settings.user_config)
        user_config["onboarding_completed"] = True
        user_config["douyin_content_download_path"] = (self.download_path_field.value or "").strip()
        settings.adopt_user_config(user_config)
        await self.app.services.config_manager.save_user_config(user_config)

        cookies_config = dict(getattr(settings, "cookies_config", {}) or {})
        douyin_cookie = sanitize_cookie_header(self.douyin_cookie_field.value or "")
        cookies_config["douyin_cookie"] = douyin_cookie
        settings.adopt_cookies_config(cookies_config)
        await self.app.services.config_manager.save_cookies_config(cookies_config)
        if hasattr(self.app.services.video_parser, "update_cookie"):
            self.app.services.video_parser.update_cookie("douyin", douyin_cookie)

        account_url = (self.account_url_field.value or "").strip()
        if account_url:
            await self.app.services.douyin_content_monitor.add_account(account_url, (self.account_name_field.value or "").strip())
        self._close()
        await self.app.snack_bar.show_snack_bar("首次配置已保存", bgcolor=ft.Colors.PRIMARY)

    def _close(self) -> None:
        if self.dialog is not None:
            self.dialog.open = False
        self.app.dialog_area.update()
