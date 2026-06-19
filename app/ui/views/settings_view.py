from __future__ import annotations

import os
import zipfile
import json
import asyncio
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
import inspect

import httpx

import flet as ft

from ...core.media.file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename
from ...core.media.cookie_utils import cookie_looks_usable, parse_cookie_pool, sanitize_cookie_header
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.common.safe_icons import icon


class SettingsPage(PageBase):
    DOWNLOAD_STRATEGIES = {
        "conservative": {"label": "保守模式", "max_parallel_downloads": 1, "video_parse_concurrency": 2, "media_download_retry_count": 2},
        "standard": {"label": "标准模式", "max_parallel_downloads": 2, "video_parse_concurrency": 4, "media_download_retry_count": 1},
        "fast": {"label": "快速模式", "max_parallel_downloads": 4, "video_parse_concurrency": 6, "media_download_retry_count": 1},
        "custom": {"label": "自定义", "max_parallel_downloads": None, "video_parse_concurrency": None, "media_download_retry_count": None},
    }

    def __init__(self, app):
        super().__init__(app)
        self.page_name = "settings"
        self.language_dropdown: ft.Dropdown | None = None
        self.download_path_field: ft.TextField | None = None
        self.selected_download_path: str = ""
        self.filename_template_field: ft.TextField | None = None
        self.filename_preview_text: ft.Text | None = None
        self.backup_dropdown: ft.Dropdown | None = None
        self.config_import_field: ft.TextField | None = None
        self.config_import_picker = None
        self.download_strategy_dropdown: ft.Dropdown | None = None
        self.max_parallel_downloads_field: ft.TextField | None = None
        self.parse_concurrency_field: ft.TextField | None = None
        self.media_retry_count_field: ft.TextField | None = None
        self.douyin_cookie_field: ft.TextField | None = None
        self.tiktok_cookie_field: ft.TextField | None = None
        self.proxy_enabled_switch: ft.Switch | None = None
        self.proxy_address_field: ft.TextField | None = None
        self.monitor_interval_field: ft.TextField | None = None
        self.settings_status_text: ft.Text | None = None
        self.cookie_test_status_text: ft.Text | None = None
        self.account_notify_switches: dict[str, ft.Switch] = {}
        self.cookie_tester = None
        self.load_language()

    def load_language(self) -> None:
        language = getattr(self.app.language_manager, "language", {}) or {}
        self._ = {}
        for key in ("settings_page", "base"):
            self._.update(language.get(key, {}))

    async def load(self) -> None:
        try:
            await self._load_full()
        except Exception as exc:
            logger.exception(f"Settings page load failed: {exc}")
            await self._load_fallback(str(exc))

    async def _load_full(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        settings = self.app.services.settings_config
        user_config = settings.user_config
        language_options = settings.language_option or {"Chinese": "zh_CN", "English": "en"}
        self.language_dropdown = ft.Dropdown(
            label=self._.get("program_language", "语言 / Language"),
            value=user_config.get("language") or next(iter(language_options.keys())),
            options=[ft.dropdown.Option(key) for key in language_options.keys()],
            width=260,
        )
        self.download_path_field = ft.TextField(
            label=self._.get("video_save_path", "视频保存路径"),
            value=str(user_config.get("douyin_content_download_path") or ""),
            hint_text=os.path.join(self.app.run_path, "downloads", "douyin_content"),
            expand=True,
            on_change=self.update_download_path_state,
        )
        self.selected_download_path = str(user_config.get("douyin_content_download_path") or "").strip()
        self.filename_template_field = ft.TextField(
            label=self._.get("filename_template", "文件命名模板"),
            value=str(user_config.get("douyin_content_filename_template") or DEFAULT_FILENAME_TEMPLATE),
            hint_text=DEFAULT_FILENAME_TEMPLATE,
            expand=True,
            on_change=self.update_filename_preview,
        )
        self.filename_preview_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        backups = self.app.services.config_manager.list_config_backups("user_settings", limit=20)
        self.backup_dropdown = ft.Dropdown(
            label="配置备份",
            hint_text="选择要恢复的配置备份",
            options=[ft.dropdown.Option(item["path"], f"{item['mtime']}  {item['name']}") for item in backups],
            expand=True,
        )
        self.config_import_field = ft.TextField(
            label="导入配置包路径",
            hint_text=os.path.join(self.app.run_path, "downloads", "config_exports", "douyin_monitor_config_xxx.zip"),
            expand=True,
        )
        self.config_import_picker = None
        self.download_strategy_dropdown = ft.Dropdown(
            label="下载策略",
            value=str(user_config.get("download_strategy_preset") or "standard"),
            width=180,
            options=[
                ft.dropdown.Option(key, value["label"])
                for key, value in self.DOWNLOAD_STRATEGIES.items()
            ],
        )
        if self.download_strategy_dropdown.value not in self.DOWNLOAD_STRATEGIES:
            self.download_strategy_dropdown.value = "standard"
        self.max_parallel_downloads_field = ft.TextField(
            label="下载并发数",
            value=str(user_config.get("max_parallel_downloads", settings.default_config.get("max_parallel_downloads", 2))),
            width=160,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.parse_concurrency_field = ft.TextField(
            label=self._.get("parse_concurrency", "解析并发数"),
            value=str(user_config.get("video_parse_concurrency", settings.default_config.get("video_parse_concurrency", 4))),
            width=180,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.media_retry_count_field = ft.TextField(
            label="下载失败重试次数",
            value=str(user_config.get("media_download_retry_count", settings.default_config.get("media_download_retry_count", 1))),
            width=180,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        cookies_config = getattr(settings, "cookies_config", {}) or {}
        self.douyin_cookie_field = ft.TextField(
            label=self._.get("douyin_cookie", "抖音 Cookie（可每行一个）"),
            value=self._format_cookie_pool_for_field(cookies_config, "douyin"),
            hint_text="可填一个 Cookie；多个 Cookie 请每行一个，系统会轮换并对异常 Cookie 冷却。",
            password=True,
            multiline=True,
            min_lines=4,
            max_lines=8,
        )
        self.tiktok_cookie_field = ft.TextField(
            label=self._.get("tiktok_cookie", "TikTok Cookie"),
            value=str(cookies_config.get("tiktok_cookie") or ""),
            password=True,
            multiline=True,
            min_lines=3,
            max_lines=5,
        )
        self.proxy_enabled_switch = ft.Switch(
            label=self._.get("enable_proxy", "开启代理"),
            value=bool(user_config.get("enable_proxy", False)),
        )
        self.proxy_address_field = ft.TextField(
            label=self._.get("proxy_address", "代理地址"),
            value=str(user_config.get("proxy_address") or ""),
            hint_text="http://127.0.0.1:7890",
            expand=True,
        )
        self.monitor_interval_field = ft.TextField(
            label=self._.get("monitor_interval", "监控间隔（分钟）"),
            value=str(user_config.get("douyin_content_monitor_interval_minutes", 10)),
            width=220,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.settings_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_test_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.account_notify_switches = {}
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                ft.Row(
                    [
                        ft.Text(self._.get("settings", "设置"), theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            tooltip=self._.get("settings_desc", "语言、视频保存路径、文件命名和存储位置。"),
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=4,
                ),
                ft.Divider(height=18),
                self._section(
                    "基础",
                    [
                        self.language_dropdown,
                    ],
                ),
                self._section(
                    "存储",
                    [
                        ft.Row(
                            [
                                self.download_path_field,
                                ft.OutlinedButton(
                                    self._.get("choose_storage_dir", "选择存储目录"),
                                    icon=ft.Icons.FOLDER_OPEN,
                                    on_click=lambda e: self.run_async(self.choose_storage_dir()),
                                ),
                                ft.FilledButton(
                                    self._.get("apply_storage_dir", "应用路径"),
                                    icon=ft.Icons.CHECK,
                                    on_click=lambda e: self.run_async(self.apply_storage_dir()),
                                ),
                            ],
                            spacing=10,
                        ),
                    ],
                ),
                self._section(
                    "文件命名",
                    [
                        ft.Row(
                            [
                                self.filename_template_field,
                                ft.IconButton(
                                    icon=ft.Icons.INFO_OUTLINE,
                                    tooltip=self._.get("available_filename_tokens", "可用占位符：{platform} {author} {item_id} {title} {date}"),
                                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Row(
                            [
                                ft.IconButton(icon=ft.Icons.PERSON, tooltip="插入作者占位符", on_click=lambda e: self.insert_filename_token("{author}")),
                                ft.IconButton(icon=icon("NUMBERS", "TAG"), tooltip="插入作品 ID 占位符", on_click=lambda e: self.insert_filename_token("{item_id}")),
                                ft.IconButton(icon=icon("TITLE", "SUBJECT"), tooltip="插入标题占位符", on_click=lambda e: self.insert_filename_token("{title}")),
                                ft.IconButton(icon=icon("CALENDAR_MONTH", "DATE_RANGE"), tooltip="插入日期占位符", on_click=lambda e: self.insert_filename_token("{date}")),
                                ft.IconButton(icon=ft.Icons.PUBLIC, tooltip="插入平台占位符", on_click=lambda e: self.insert_filename_token("{platform}")),
                            ],
                            spacing=4,
                            wrap=True,
                        ),
                        self.filename_preview_text,
                    ],
                ),
                self._section(
                    self._.get("parse_settings", "解析配置"),
                    [
                        ft.Row(
                            [
                                self.download_strategy_dropdown,
                                ft.OutlinedButton(
                                    "应用策略",
                                    icon=ft.Icons.TUNE,
                                    on_click=self.apply_download_strategy,
                                ),
                                self.max_parallel_downloads_field,
                                self.parse_concurrency_field,
                                self.media_retry_count_field,
                                ft.IconButton(
                                    icon=ft.Icons.INFO_OUTLINE,
                                    tooltip=self._.get("parse_concurrency_tip", "保守模式适合弱网和长期运行；标准模式适合日常；快速模式适合短时间批量下载。"),
                                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                                ),
                            ],
                            spacing=8,
                        ),
                        self._cookie_health_controls(cookies_config),
                        ft.Row(
                            [
                                ft.OutlinedButton(self._.get("show_hide_cookie", "显示/隐藏 Cookie"), icon=ft.Icons.VISIBILITY, on_click=self.toggle_cookie_visibility),
                                ft.OutlinedButton(self._.get("test_douyin_cookie", "测试抖音 Cookie"), icon=ft.Icons.VERIFIED, on_click=lambda e: self.run_async(self.test_cookie("douyin"))),
                                ft.OutlinedButton(self._.get("test_tiktok_cookie", "测试 TikTok Cookie"), icon=ft.Icons.VERIFIED_USER, on_click=lambda e: self.run_async(self.test_cookie("tiktok"))),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        self.cookie_test_status_text,
                        self.douyin_cookie_field,
                        self.tiktok_cookie_field,
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            tooltip=self._.get("cookie_sync_tip", "Cookie 会保存到本地配置，并同步给内置解析器。"),
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                ),
                self._section(
                    self._.get("monitor_settings", "监控设置"),
                    [
                        self.monitor_interval_field,
                        self.proxy_enabled_switch,
                        self.proxy_address_field,
                        *self._account_notify_controls(),
                    ],
                ),
                self._section(
                    "配置备份",
                    [
                        ft.Row(
                            [
                                self.backup_dropdown,
                                ft.IconButton(
                                    icon=ft.Icons.RESTORE,
                                    tooltip="恢复选中的配置备份",
                                    on_click=lambda e: self.run_async(self.restore_selected_backup()),
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.REFRESH,
                                    tooltip="刷新配置备份列表",
                                    on_click=lambda e: self.run_async(self.load()),
                                ),
                                ft.IconButton(
                                    icon=icon("ARCHIVE", "DOWNLOAD"),
                                    tooltip="导出完整配置包",
                                    on_click=lambda e: self.run_async(self.export_config_package()),
                                ),
                                ft.IconButton(
                                    icon=icon("BACKUP", "ARCHIVE"),
                                    tooltip="导出完整备份（含账号、监控数据、Cookie）",
                                    on_click=lambda e: self.run_async(self.export_full_backup()),
                                ),
                            ],
                            spacing=8,
                        ),
                        ft.Row(
                            [
                                self.config_import_field,
                                ft.IconButton(
                                    icon=ft.Icons.FOLDER_OPEN,
                                    tooltip="选择 ZIP 配置包",
                                    on_click=self.pick_config_package,
                                ),
                                ft.IconButton(
                                    icon=ft.Icons.UPLOAD_FILE,
                                    tooltip="从 ZIP 配置包导入设置",
                                    on_click=lambda e: self.run_async(self.import_config_package()),
                                ),
                                ft.IconButton(
                                    icon=icon("RESTORE_PAGE", "RESTORE"),
                                    tooltip="恢复完整备份",
                                    on_click=lambda e: self.run_async(self.import_full_backup()),
                                ),
                            ],
                            spacing=8,
                        ),
                    ],
                ),
                ft.Row(
                    [
                        ft.IconButton(
                            icon=ft.Icons.SAVE,
                            tooltip=self._.get("save_settings", "保存设置"),
                            on_click=lambda e: self.run_async(self.save_settings()),
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.RESTART_ALT,
                            tooltip=self._.get("restore_default_naming", "恢复默认命名"),
                            on_click=self.reset_filename_template,
                            icon_color=ft.Colors.PRIMARY,
                        ),
                        self.settings_status_text,
                    ],
                    spacing=10,
                ),
            ]
        )
        self.update_filename_preview()
        self.content_area.update()

    async def _load_fallback(self, reason: str) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        settings = self.app.services.settings_config
        user_config = dict(getattr(settings, "user_config", {}) or {})
        cookies_config = dict(getattr(settings, "cookies_config", {}) or {})
        self.download_path_field = ft.TextField(
            label="视频保存路径",
            value=str(user_config.get("douyin_content_download_path") or ""),
            hint_text=os.path.join(self.app.run_path, "downloads", "douyin_content"),
            on_change=self.update_download_path_state,
        )
        self.selected_download_path = str(user_config.get("douyin_content_download_path") or "").strip()
        self.douyin_cookie_field = ft.TextField(
            label="抖音 Cookie（可每行一个）",
            value=self._format_cookie_pool_for_field(cookies_config, "douyin"),
            hint_text="多个 Cookie 请每行一个。",
            password=True,
            multiline=True,
            min_lines=4,
            max_lines=8,
        )
        self.tiktok_cookie_field = ft.TextField(
            label="TikTok Cookie",
            value=str(cookies_config.get("tiktok_cookie") or ""),
            password=True,
            multiline=True,
            min_lines=3,
            max_lines=5,
        )
        self.parse_concurrency_field = ft.TextField(
            label="解析并发数",
            value=str(user_config.get("video_parse_concurrency", 4)),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.max_parallel_downloads_field = ft.TextField(
            label="下载并发数",
            value=str(user_config.get("max_parallel_downloads", 2)),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.media_retry_count_field = ft.TextField(
            label="下载失败重试次数",
            value=str(user_config.get("media_download_retry_count", 1)),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.proxy_enabled_switch = ft.Switch(label="开启代理", value=bool(user_config.get("enable_proxy", False)))
        self.proxy_address_field = ft.TextField(label="代理地址", value=str(user_config.get("proxy_address") or ""))
        self.monitor_interval_field = ft.TextField(
            label="监控间隔（分钟）",
            value=str(user_config.get("douyin_content_monitor_interval_minutes", 10)),
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.settings_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_test_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.language_dropdown = None
        self.filename_template_field = None
        self.download_strategy_dropdown = None
        self.account_notify_switches = {}
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                ft.Row(
                    [
                        ft.Text("设置", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.Container(
                            content=ft.Text("已进入兼容模式", size=12, color=ft.Colors.WHITE),
                            bgcolor=ft.Colors.ORANGE,
                            border_radius=8,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(
                    content=ft.Text(f"完整设置页加载失败：{reason}", selectable=True, color=ft.Colors.ERROR),
                    border=ft.Border.all(1, ft.Colors.ERROR),
                    border_radius=8,
                    padding=12,
                ),
                self._section("基础配置", [self.download_path_field, self.douyin_cookie_field, self.tiktok_cookie_field]),
                self._section(
                    "运行配置",
                    [
                        ft.Row(
                            [self.parse_concurrency_field, self.max_parallel_downloads_field, self.media_retry_count_field],
                            spacing=8,
                            wrap=True,
                        ),
                        self.monitor_interval_field,
                        self.proxy_enabled_switch,
                        self.proxy_address_field,
                    ],
                ),
                ft.Row(
                    [
                        ft.FilledButton("保存设置", icon=ft.Icons.SAVE, on_click=lambda e: self.run_async(self.save_settings())),
                        ft.OutlinedButton("重新加载完整设置页", icon=ft.Icons.REFRESH, on_click=lambda e: self.run_async(self.load())),
                        self.settings_status_text,
                    ],
                    spacing=10,
                    wrap=True,
                ),
            ]
        )
        self.content_area.update()

    def _ensure_config_import_picker(self) -> None:
        if self.config_import_picker is not None:
            try:
                if self.config_import_picker not in self.page.overlay:
                    self.page.overlay.append(self.config_import_picker)
                    self.page.update()
            except Exception as exc:
                logger.debug(f"remount config import picker failed: {exc}")
            return
        if not hasattr(ft, "FilePicker"):
            return

        def on_result(event) -> None:
            try:
                files = list(getattr(event, "files", None) or [])
                path = str(getattr(files[0], "path", "") or "") if files else ""
                if path and self.config_import_field:
                    self.config_import_field.value = path
                    self.config_import_field.update()
            except Exception as exc:
                logger.debug(f"config import picker failed: {exc}")

        try:
            self.config_import_picker = ft.FilePicker(on_result=on_result)
            if self.config_import_picker not in self.page.overlay:
                self.page.overlay.append(self.config_import_picker)
                self.page.update()
        except Exception as exc:
            logger.debug(f"create config import picker failed: {exc}")
            self.config_import_picker = None

    def pick_config_package(self, _=None) -> None:
        self._ensure_config_import_picker()
        if self.config_import_picker is None:
            self.run_async(self.app.snack_bar.show_snack_bar("当前环境不支持文件选择器，请手动粘贴 ZIP 路径", bgcolor=ft.Colors.ERROR))
            return
        try:
            self.config_import_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["zip"],
                dialog_title="选择 Douyin Monitor 配置包",
            )
        except Exception as exc:
            logger.debug(f"open config import picker failed: {exc}")
            self.run_async(self.app.snack_bar.show_snack_bar("打开文件选择器失败，请手动粘贴 ZIP 路径", bgcolor=ft.Colors.ERROR))

    async def choose_storage_dir(self) -> None:
        await self.app.snack_bar.show_snack_bar("正在打开目录选择器...", bgcolor=ft.Colors.PRIMARY)
        selected = await self._choose_storage_dir_native()
        if selected:
            await self._apply_selected_storage_dir(selected)
            return
        await self.app.snack_bar.show_snack_bar(
            self._.get("storage_picker_failed", "打开目录选择器失败，请手动粘贴存储路径"),
            bgcolor=ft.Colors.ERROR,
        )

    async def _apply_selected_storage_dir(self, path: str) -> None:
        selected = str(path or "").strip()
        if not selected:
            return
        self.selected_download_path = selected
        if self.download_path_field:
            self.download_path_field.value = selected
            self.download_path_field.update()
        self.update_filename_preview()
        await self._persist_download_path(selected)
        await self.app.snack_bar.show_snack_bar(
            self._.get("storage_dir_saved", "存储目录已保存"),
            bgcolor=ft.Colors.PRIMARY,
        )

    async def apply_storage_dir(self) -> None:
        path = str((self.download_path_field.value if self.download_path_field else "") or "").strip()
        if not path:
            path = os.path.join(self.app.run_path, "downloads", "douyin_content")
        self.selected_download_path = path
        await self._persist_download_path(path)
        await self.app.snack_bar.show_snack_bar(
            self._.get("storage_dir_saved", "存储目录已保存"),
            bgcolor=ft.Colors.PRIMARY,
        )

    async def _persist_download_path(self, path: str) -> None:
        download_path = str(path or "").strip()
        if download_path:
            os.makedirs(download_path, exist_ok=True)
        settings = self.app.services.settings_config
        user_config = dict(settings.user_config)
        user_config["douyin_content_download_path"] = download_path
        await self.app.services.config_manager.save_user_config(user_config)
        saved_user_config = self.app.services.config_manager.load_user_config() or {}
        saved_download_path = str(saved_user_config.get("douyin_content_download_path") or "").strip()
        if saved_download_path != download_path:
            raise RuntimeError(f"保存路径失败：期望 {download_path or '<默认路径>'}，实际 {saved_download_path or '<默认路径>'}")
        settings.adopt_user_config(saved_user_config)
        self.selected_download_path = saved_download_path
        if self.download_path_field is not None:
            self.download_path_field.value = saved_download_path
            try:
                self.download_path_field.update()
            except Exception:
                pass
        self.update_filename_preview()

    def update_download_path_state(self, _=None) -> None:
        self.selected_download_path = str((self.download_path_field.value if self.download_path_field else "") or "").strip()
        self.update_filename_preview()

    async def _choose_storage_dir_native(self) -> str:
        return await asyncio.to_thread(self._choose_storage_dir_native_sync)

    def _choose_storage_dir_native_sync(self) -> str:
        if sys.platform.startswith("win"):
            return self._choose_storage_dir_windows_sync()
        try:
            import tkinter as tk
            from tkinter import filedialog

            current = self._storage_dir()
            initial = current if os.path.isdir(current) else os.path.dirname(current)
            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            try:
                path = filedialog.askdirectory(
                    title="选择视频存储目录",
                    initialdir=initial if initial and os.path.isdir(initial) else None,
                )
            finally:
                root.destroy()
            return str(path or "").strip()
        except Exception as exc:
            logger.debug(f"native storage directory picker failed: {exc}")
            return ""

    def _choose_storage_dir_windows_sync(self) -> str:
        try:
            current = self._storage_dir()
            initial = current if os.path.isdir(current) else os.path.dirname(current)
            script = r"""
Add-Type -AssemblyName System.Windows.Forms
$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = '选择视频存储目录'
$dialog.ShowNewFolderButton = $true
if ($args.Count -gt 0 -and $args[0] -and (Test-Path -LiteralPath $args[0])) {
    $dialog.SelectedPath = $args[0]
}
$result = $dialog.ShowDialog()
if ($result -eq [System.Windows.Forms.DialogResult]::OK) {
    [Console]::Out.WriteLine($dialog.SelectedPath)
}
"""
            kwargs: dict[str, Any] = {
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "ignore",
            }
            if hasattr(subprocess, "CREATE_NO_WINDOW"):
                kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", script, initial],
                **kwargs,
            )
            if completed.returncode != 0:
                logger.debug(f"windows folder picker failed: {completed.stderr.strip()}")
                return ""
            return str(completed.stdout or "").strip().splitlines()[-1].strip() if completed.stdout.strip() else ""
        except Exception as exc:
            logger.debug(f"windows storage directory picker failed: {exc}")
            return ""

    def _cookie_health_controls(self, cookies_config: dict[str, Any]) -> ft.Row:
        douyin_pool = parse_cookie_pool(cookies_config.get("douyin_cookie_pool") or cookies_config.get("douyin_cookie") or "")
        douyin_label = f"抖音 Cookie 池（{len(douyin_pool)} 个）" if len(douyin_pool) > 1 else "抖音 Cookie"
        return ft.Row(
            controls=[
                self._cookie_chip(douyin_label, douyin_pool[0] if douyin_pool else ""),
                self._cookie_chip("TikTok Cookie", str(cookies_config.get("tiktok_cookie") or "")),
            ],
            wrap=True,
            spacing=8,
        )

    def _format_cookie_pool_for_field(self, cookies_config: dict[str, Any], platform: str) -> str:
        if platform != "douyin":
            return str(cookies_config.get(f"{platform}_cookie") or "")
        pool = parse_cookie_pool(cookies_config.get("douyin_cookie_pool") or [])
        primary = str(cookies_config.get("douyin_cookie") or "")
        for cookie in parse_cookie_pool(primary):
            if cookie not in pool:
                pool.insert(0, cookie)
        return "\n".join(pool) if pool else primary

    def _cookie_chip(self, label: str, cookie: str) -> ft.Container:
        text = cookie.strip()
        if not text:
            status = "未配置"
            color = ft.Colors.ON_SURFACE_VARIANT
        elif self._looks_like_cookie(text):
            status = "已配置"
            color = ft.Colors.GREEN
        else:
            status = "可能不完整"
            color = ft.Colors.ORANGE
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.COOKIE, size=14, color=ft.Colors.WHITE),
                    ft.Text(f"{label}：{status}", size=11, color=ft.Colors.WHITE),
                ],
                spacing=4,
                tight=True,
            ),
            bgcolor=color,
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        )

    @staticmethod
    def _looks_like_cookie(cookie: str) -> bool:
        return cookie_looks_usable(cookie)

    def _section(self, title: str, controls: list[ft.Control]) -> ft.Container:
        return ft.Container(
            content=ft.Column(
                [ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM), *controls],
                spacing=10,
            ),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=14,
        )

    def _account_notify_controls(self) -> list[ft.Control]:
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        accounts = list(getattr(monitor, "accounts", []) or [])
        if not accounts:
            return [ft.Text(self._.get("no_accounts_for_notify", "暂无账号通知设置"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)]
        controls: list[ft.Control] = [ft.Text(self._.get("account_notify", "单账号通知开关"), theme_style=ft.TextThemeStyle.TITLE_SMALL)]
        for account in accounts:
            label = account.display_name or account.douyin_nickname or account.homepage_url or account.account_id
            switch = ft.Switch(label=label, value=bool(getattr(account, "notify_enabled", True)))
            self.account_notify_switches[account.account_id] = switch
            controls.append(switch)
        return controls

    def reset_filename_template(self, _=None) -> None:
        if self.filename_template_field is not None:
            self.filename_template_field.value = DEFAULT_FILENAME_TEMPLATE
            self.update_filename_preview()
            self.filename_template_field.update()

    def insert_filename_token(self, token: str) -> None:
        if self.filename_template_field is None:
            return
        current = str(self.filename_template_field.value or "")
        joiner = "" if not current or current.endswith(("_", "-", " ")) else "_"
        self.filename_template_field.value = f"{current}{joiner}{token}"
        self.update_filename_preview()
        try:
            self.filename_template_field.update()
        except Exception:
            pass

    def apply_download_strategy(self, _=None) -> None:
        preset = str((self.download_strategy_dropdown.value if self.download_strategy_dropdown else "") or "standard")
        strategy = self.DOWNLOAD_STRATEGIES.get(preset, self.DOWNLOAD_STRATEGIES["standard"])
        field_map = {
            "max_parallel_downloads": self.max_parallel_downloads_field,
            "video_parse_concurrency": self.parse_concurrency_field,
            "media_download_retry_count": self.media_retry_count_field,
        }
        for key, field in field_map.items():
            value = strategy.get(key)
            if value is None or field is None:
                continue
            field.value = str(value)
            try:
                field.update()
            except Exception:
                pass

    def update_filename_preview(self, _=None) -> None:
        if self.filename_preview_text is None:
            return
        template = str((self.filename_template_field.value if self.filename_template_field else "") or DEFAULT_FILENAME_TEMPLATE)
        filename = format_media_filename(
            template,
            {
                "platform": "douyin",
                "author": "示例作者",
                "item_id": "7123456789012345678",
                "title": "示例作品标题",
                "date": "20260616",
            },
            fallback="preview",
        )
        folder = self._storage_dir()
        self.filename_preview_text.value = f"命名预览：{os.path.join(folder, filename)}.mp4"
        try:
            self.filename_preview_text.update()
        except Exception:
            pass

    async def restore_selected_backup(self) -> None:
        path = str((self.backup_dropdown.value if self.backup_dropdown else "") or "")
        if not path:
            await self.app.snack_bar.show_snack_bar("请选择要恢复的配置备份", bgcolor=ft.Colors.ERROR)
            return
        ok = await self.app.services.config_manager.restore_config_backup(path, "user_settings")
        if not ok:
            await self.app.snack_bar.show_snack_bar("恢复失败：备份文件无效", bgcolor=ft.Colors.ERROR)
            return
        settings = self.app.services.settings_config
        settings.adopt_user_config(self.app.services.config_manager.load_user_config() or {})
        await self.app.snack_bar.show_snack_bar("配置备份已恢复，请检查设置后保存或重启应用", bgcolor=ft.Colors.PRIMARY)
        await self.load()

    async def export_config_package(self) -> None:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "config_exports")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        include_names = {"user_settings.json", "language.json", "default_settings.json"}
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in include_names:
                    zf.write(file, arcname=file.name)
        await self.app.snack_bar.show_snack_bar(f"配置包已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)

    async def export_full_backup(self) -> None:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "backups")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        include_names = {
            "user_settings.json",
            "language.json",
            "default_settings.json",
            "cookies.json",
            "douyin_content_monitor.json",
            "accounts.json",
            "recordings.json",
            "web_auth.json",
        }
        manifest = {
            "type": "douyin_monitor_full_backup",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "files": [],
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in include_names and file.exists():
                    zf.write(file, arcname=f"config/{file.name}")
                    manifest["files"].append(f"config/{file.name}")
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        await self.app.snack_bar.show_snack_bar(
            f"完整备份已导出：{path}。注意：备份内可能包含 Cookie，请妥善保存。",
            bgcolor=ft.Colors.PRIMARY,
            duration=8000,
            show_close_icon=True,
        )

    async def import_config_package(self) -> None:
        path = Path(str((self.config_import_field.value if self.config_import_field else "") or "").strip())
        if not path.exists() or path.suffix.lower() != ".zip":
            await self.app.snack_bar.show_snack_bar("请选择有效的 ZIP 配置包路径", bgcolor=ft.Colors.ERROR)
            return

        allowed = {"user_settings.json", "language.json", "default_settings.json"}
        parsed: dict[str, dict[str, Any]] = {}
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    clean_name = Path(name).name
                    if clean_name not in allowed:
                        continue
                    with zf.open(name) as file:
                        value = json.loads(file.read().decode("utf-8"))
                    if isinstance(value, dict):
                        parsed[clean_name] = value
        except Exception as exc:
            logger.debug(f"import config package failed: {exc}")
            await self.app.snack_bar.show_snack_bar("导入失败：配置包无法读取", bgcolor=ft.Colors.ERROR)
            return

        if not parsed:
            await self.app.snack_bar.show_snack_bar("导入失败：配置包中没有可用配置", bgcolor=ft.Colors.ERROR)
            return

        manager = self.app.services.config_manager
        settings = self.app.services.settings_config
        if "user_settings.json" in parsed:
            await manager.save_user_config(parsed["user_settings.json"])
            settings.adopt_user_config(parsed["user_settings.json"])
        config_dir = Path(self.app.run_path, "config")
        for name in ("language.json", "default_settings.json"):
            if name in parsed:
                await manager._save_config(str(config_dir / name), parsed[name], success_message=f"{name} imported.", error_message=f"Import {name} failed")
        if "language.json" in parsed:
            settings.language_option = parsed["language.json"]
            self.app.language_manager.load()
            self.app.language_manager.notify_observers()
        if "default_settings.json" in parsed:
            settings.default_config = parsed["default_settings.json"]
        if hasattr(self.app, "refresh_nav"):
            self.app.refresh_nav()
        await self.app.snack_bar.show_snack_bar("配置包已导入，已刷新可即时生效的配置；下载线程等运行中设置建议重启后完全生效", bgcolor=ft.Colors.PRIMARY, duration=7000, show_close_icon=True)
        await self.load()

    async def import_full_backup(self) -> None:
        path = Path(str((self.config_import_field.value if self.config_import_field else "") or "").strip())
        if not path.exists() or path.suffix.lower() != ".zip":
            await self.app.snack_bar.show_snack_bar("请选择有效的完整备份 ZIP 路径", bgcolor=ft.Colors.ERROR)
            return

        allowed = {
            "user_settings.json",
            "language.json",
            "default_settings.json",
            "cookies.json",
            "douyin_content_monitor.json",
            "accounts.json",
            "recordings.json",
            "web_auth.json",
        }
        parsed: dict[str, dict[str, Any]] = {}
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    parts = Path(name).parts
                    if len(parts) != 2 or parts[0] != "config" or parts[1] not in allowed:
                        continue
                    with zf.open(name) as file:
                        value = json.loads(file.read().decode("utf-8"))
                    if isinstance(value, dict):
                        parsed[parts[1]] = value
        except Exception as exc:
            logger.debug(f"import full backup failed: {exc}")
            await self.app.snack_bar.show_snack_bar("恢复失败：备份包无法读取", bgcolor=ft.Colors.ERROR)
            return

        if not parsed:
            await self.app.snack_bar.show_snack_bar("恢复失败：备份包内没有可恢复配置", bgcolor=ft.Colors.ERROR)
            return

        manager = self.app.services.config_manager
        config_dir = Path(self.app.run_path, "config")
        for name, value in parsed.items():
            await manager._save_config(str(config_dir / name), value, success_message=f"{name} restored.", error_message=f"Restore {name} failed")

        settings = self.app.services.settings_config
        if "user_settings.json" in parsed:
            settings.adopt_user_config(parsed["user_settings.json"])
        if "cookies.json" in parsed:
            settings.adopt_cookies_config(parsed["cookies.json"])
        if "accounts.json" in parsed:
            settings.adopt_accounts_config(parsed["accounts.json"])
        if "language.json" in parsed:
            settings.language_option = parsed["language.json"]
            self.app.language_manager.load()
            self.app.language_manager.notify_observers()
        if "default_settings.json" in parsed:
            settings.default_config = parsed["default_settings.json"]
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        if monitor is not None and "douyin_content_monitor.json" in parsed:
            try:
                monitor._load_accounts()
            except Exception as exc:
                logger.debug(f"reload monitor accounts after full restore failed: {exc}")
        if hasattr(self.app, "refresh_nav"):
            self.app.refresh_nav()
        await self.app.snack_bar.show_snack_bar("完整备份已恢复，建议重启应用确保所有运行中服务重新加载。", bgcolor=ft.Colors.PRIMARY, duration=8000, show_close_icon=True)
        await self.load()

    def _storage_dir(self) -> str:
        value = (self.download_path_field.value if self.download_path_field else "") or self.selected_download_path or ""
        value = value.strip()
        if value:
            return value
        return os.path.join(self.app.run_path, "downloads", "douyin_content")

    async def open_storage_dir(self) -> None:
        path = self._storage_dir()
        os.makedirs(path, exist_ok=True)
        await self.open_path_or_url(
            path,
            success=self._.get("storage_opened", "存储目录已打开"),
            failed_prefix=self._.get("storage_open_failed", "打开存储目录失败"),
        )

    def toggle_cookie_visibility(self, _=None) -> None:
        fields = [self.douyin_cookie_field, self.tiktok_cookie_field]
        visible = any(bool(field and field.password) for field in fields)
        for field in fields:
            if field is not None:
                field.password = not visible
                try:
                    field.update()
                except Exception:
                    pass

    def _set_inline_status(self, target: str, message: str, color: Any | None = None) -> None:
        control = self.cookie_test_status_text if target == "cookie" else self.settings_status_text
        if control is None:
            return
        control.value = str(message or "")
        control.color = color or ft.Colors.ON_SURFACE_VARIANT
        try:
            control.update()
        except Exception as exc:
            logger.debug(f"update settings inline status failed: {exc}")

    async def _show_feedback(
        self,
        target: str,
        message: str,
        *,
        success: bool = True,
        duration: int = 3500,
        show_close_icon: bool = True,
    ) -> None:
        color = ft.Colors.PRIMARY if success else ft.Colors.ERROR
        self._set_inline_status(target, message, color)
        try:
            await self.app.snack_bar.show_snack_bar(
                message,
                bgcolor=color,
                duration=duration,
                show_close_icon=show_close_icon,
            )
        except Exception as exc:
            logger.debug(f"settings feedback snackbar failed: {exc}")

    async def test_cookie(self, platform: str) -> None:
        field = self.douyin_cookie_field if platform == "douyin" else self.tiktok_cookie_field
        raw_cookie = (field.value if field else "") or ""
        cookie_pool = parse_cookie_pool(raw_cookie) if platform == "douyin" else []
        cookie = cookie_pool[0] if cookie_pool else sanitize_cookie_header(raw_cookie)
        label = "抖音" if platform == "douyin" else "TikTok"
        self._set_inline_status("cookie", f"正在测试 {label} Cookie...", ft.Colors.PRIMARY)
        if not cookie:
            await self._show_feedback("cookie", f"{label} Cookie 为空，请先粘贴后再测试", success=False)
            return
        if not self._looks_like_cookie(cookie):
            await self._show_feedback("cookie", f"{label} Cookie 格式可能不完整：缺少有效键值或长度过短", success=False)
            return
        tester = self.cookie_tester or self._default_cookie_test
        try:
            result = tester(platform, cookie)
            if inspect.isawaitable(result):
                result = await result
            success = bool(result.get("success")) if isinstance(result, dict) else bool(result)
            reason = str(result.get("reason") if isinstance(result, dict) else ("Cookie 可用" if success else "Cookie 不可用"))
        except Exception as exc:
            success = False
            reason = f"{label} Cookie 检测异常：{exc}"
        if platform == "douyin" and len(cookie_pool) > 1:
            reason = f"{reason}；已识别 Cookie 池 {len(cookie_pool)} 个，当前测试第 1 个"
        await self._show_feedback("cookie", reason, success=success, duration=5000)

    async def _default_cookie_test(self, platform: str, cookie: str) -> dict[str, Any]:
        if not cookie:
            return {"success": False, "reason": "Cookie 为空"}
        url = "https://www.douyin.com/" if platform == "douyin" else "https://www.tiktok.com/"
        cookie = sanitize_cookie_header(cookie)
        headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie}
        proxy = (self.proxy_address_field.value or "").strip() if self.proxy_enabled_switch and self.proxy_enabled_switch.value else None
        try:
            async with httpx.AsyncClient(headers=headers, proxy=proxy, timeout=8, follow_redirects=True) as client:
                response = await client.get(url)
            return {"success": response.status_code < 400, "reason": f"{platform} Cookie 检测：HTTP {response.status_code}"}
        except Exception as exc:
            return {"success": False, "reason": f"{platform} Cookie 检测失败：{exc}"}

    async def save_settings(self) -> None:
        self._set_inline_status("settings", "正在保存设置...", ft.Colors.PRIMARY)
        settings = self.app.services.settings_config
        user_config = dict(settings.user_config)
        language = (self.language_dropdown.value if self.language_dropdown else "") or user_config.get("language") or "Chinese"
        download_path = (self.download_path_field.value if self.download_path_field else "") or self.selected_download_path or ""
        download_path = str(download_path).strip()
        filename_template = (
            (self.filename_template_field.value if self.filename_template_field else "")
            or user_config.get("douyin_content_filename_template")
            or DEFAULT_FILENAME_TEMPLATE
        )
        try:
            parse_concurrency = int((self.parse_concurrency_field.value if self.parse_concurrency_field else "") or 4)
        except (TypeError, ValueError):
            parse_concurrency = 4
        parse_concurrency = max(1, min(16, parse_concurrency))
        try:
            max_parallel_downloads = int((self.max_parallel_downloads_field.value if self.max_parallel_downloads_field else "") or 2)
        except (TypeError, ValueError):
            max_parallel_downloads = 2
        max_parallel_downloads = max(1, min(16, max_parallel_downloads))
        try:
            media_retry_count = int((self.media_retry_count_field.value if self.media_retry_count_field else "") or 1)
        except (TypeError, ValueError):
            media_retry_count = 1
        media_retry_count = max(0, min(5, media_retry_count))
        download_strategy = str((self.download_strategy_dropdown.value if self.download_strategy_dropdown else "") or user_config.get("download_strategy_preset") or "standard")
        if download_strategy not in self.DOWNLOAD_STRATEGIES:
            download_strategy = "standard"
        user_config["language"] = str(language)
        user_config["douyin_content_download_path"] = download_path
        user_config["douyin_content_filename_template"] = str(filename_template).strip() or DEFAULT_FILENAME_TEMPLATE
        user_config["download_strategy_preset"] = download_strategy
        user_config["max_parallel_downloads"] = max_parallel_downloads
        user_config["media_queue_auto_tune"] = False
        user_config["video_parse_concurrency"] = parse_concurrency
        user_config["media_download_retry_count"] = media_retry_count
        user_config["enable_proxy"] = bool(self.proxy_enabled_switch.value if self.proxy_enabled_switch else False)
        user_config["proxy_address"] = str((self.proxy_address_field.value if self.proxy_address_field else "") or "").strip()
        try:
            monitor_interval = float((self.monitor_interval_field.value if self.monitor_interval_field else "") or 10)
        except (TypeError, ValueError):
            monitor_interval = 10.0
        user_config["douyin_content_monitor_interval_minutes"] = max(1.0, monitor_interval)
        settings.adopt_user_config(user_config)
        settings.language_code = settings.language_option.get(str(language), settings.language_code)
        await self.app.services.config_manager.save_user_config(user_config)
        saved_user_config = self.app.services.config_manager.load_user_config() or {}
        saved_download_path = str(saved_user_config.get("douyin_content_download_path") or "").strip()
        if saved_download_path != download_path:
            raise RuntimeError(f"保存路径失败：期望 {download_path or '<默认路径>'}，实际 {saved_download_path or '<默认路径>'}")
        settings.adopt_user_config(saved_user_config)
        self.selected_download_path = saved_download_path
        if self.download_path_field is not None:
            self.download_path_field.value = saved_download_path
            try:
                self.download_path_field.update()
            except Exception:
                pass
        cookies_config = dict(getattr(settings, "cookies_config", {}) or {})
        raw_douyin_cookie = (self.douyin_cookie_field.value if self.douyin_cookie_field else "") or ""
        raw_tiktok_cookie = (self.tiktok_cookie_field.value if self.tiktok_cookie_field else "") or ""
        douyin_cookie_pool = parse_cookie_pool(raw_douyin_cookie)
        douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else ""
        tiktok_cookie = sanitize_cookie_header(raw_tiktok_cookie)
        cookie_cleaned = bool(
            raw_douyin_cookie.strip() != "\n".join(douyin_cookie_pool)
            or raw_tiktok_cookie.strip() != tiktok_cookie
        )
        cookies_config["douyin_cookie"] = douyin_cookie
        cookies_config["douyin_cookie_pool"] = douyin_cookie_pool
        cookies_config["tiktok_cookie"] = tiktok_cookie
        settings.adopt_cookies_config(cookies_config)
        if hasattr(self.app.services.config_manager, "save_cookies_config"):
            await self.app.services.config_manager.save_cookies_config(cookies_config)
        if hasattr(self.app.services.video_parser, "parse_concurrency"):
            self.app.services.video_parser.parse_concurrency = parse_concurrency
        cookie_sync_warnings: list[str] = []
        if hasattr(self.app.services.video_parser, "update_cookie"):
            for platform, cookie_value in (("douyin", douyin_cookie), ("tiktok", tiktok_cookie)):
                try:
                    self.app.services.video_parser.update_cookie(platform, cookie_value)
                except Exception as exc:
                    cookie_sync_warnings.append(f"{platform}: {exc}")
                    logger.debug(f"sync {platform} cookie to parser failed: {exc}")
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        if monitor is not None:
            changed = False
            by_id = {getattr(account, "account_id", ""): account for account in getattr(monitor, "accounts", []) or []}
            for account_id, switch in self.account_notify_switches.items():
                account = by_id.get(account_id)
                if account is not None and getattr(account, "notify_enabled", True) != bool(switch.value):
                    account.notify_enabled = bool(switch.value)
                    changed = True
            if changed and hasattr(monitor, "persist"):
                await monitor.persist(force=True)
        self.app.language_manager.load()
        self.app.language_manager.notify_observers()
        if hasattr(self.app, "refresh_nav"):
            self.app.refresh_nav()
        message = self._.get("settings_saved", "设置已保存")
        if cookie_cleaned:
            message += "，已自动清理 Cookie 中无效片段"
        if cookie_sync_warnings:
            message += "；Cookie 已保存，但同步到内置解析器时有警告，重启应用后会重新加载"
        await self._show_feedback("settings", message, success=True, duration=6000)

    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Settings UI task failed: {exc}")
            await self._show_feedback("settings", str(exc), success=False, duration=6000)

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
