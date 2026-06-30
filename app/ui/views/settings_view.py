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
import time

import httpx

import flet as ft

from ...core.media.file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename
from ...core.media.cookie_utils import cookie_looks_usable, parse_cookie_pool, sanitize_cookie_header
from ...core.ui_services.settings_workflow import SettingsWorkflow
from ...core.ui_services.settings_backup_service import SettingsBackupService
from ...core.ui_services.settings_storage_service import SettingsStorageService
from ...core.ui_services.settings_cookie_service import SettingsCookieService
from ...core.ui_services.settings_proxy_service import SettingsProxyService
from ...core.ui_services.settings_preset_service import SettingsPresetService
from ...core.ui_services.settings_service import SettingsService
from ...core.ui_services.performance_observability_service import PerformanceObservabilityService
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.common.safe_icons import icon


class SettingsPage(PageBase):
    DOWNLOAD_STRATEGIES = SettingsWorkflow.DOWNLOAD_STRATEGIES
    # Windows/Flet WebView2 stability guard: do not let TextField use expand=True
    # inside scrollable settings sections. A flex TextField can stretch vertically
    # and render as a large grey block in this build. Use bounded widths instead.
    WIDE_FIELD_WIDTH = 760
    SINGLE_LINE_FIELD_HEIGHT = 56
    ACCOUNT_NOTIFY_PAGE_SIZE = 20
    ACCOUNT_NOTIFY_LIST_HEIGHT = 360

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
        self.monitor_batch_concurrency_field: ft.TextField | None = None
        self.batch_parse_size_field: ft.TextField | None = None
        self.batch_download_concurrency_field: ft.TextField | None = None
        self.download_chunk_size_field: ft.TextField | None = None
        self.gallery_image_concurrency_field: ft.TextField | None = None
        self.gallery_image_save_format_dropdown: ft.Dropdown | None = None
        self.cookie_cooldown_field: ft.TextField | None = None
        self.incremental_pages_field: ft.TextField | None = None
        self.segmented_parts_field: ft.TextField | None = None
        self.segmented_min_size_field: ft.TextField | None = None
        self.monitor_fast_switch: ft.Control | None = None
        self.development_bypass_switch: ft.Control | None = None
        self.global_rate_limiter_switch: ft.Control | None = None
        self.cookie_cooldown_enabled_switch: ft.Control | None = None
        self.risk_backoff_switch: ft.Control | None = None
        self.cookie_health_persistence_switch: ft.Control | None = None
        self.pipeline_download_switch: ft.Control | None = None
        self.segmented_download_switch: ft.Control | None = None
        self.auto_update_enabled_switch: ft.Control | None = None
        self.auto_update_startup_switch: ft.Control | None = None
        self.auto_update_silent_switch: ft.Control | None = None
        self.auto_update_manifest_url_field: ft.TextField | None = None
        self.auto_update_channel_dropdown: ft.Dropdown | None = None
        self.auto_update_install_kind_dropdown: ft.Dropdown | None = None
        self.auto_update_status_text: ft.Text | None = None
        self.douyin_cookie_field: ft.TextField | None = None
        self.tiktok_cookie_field: ft.TextField | None = None
        self.proxy_enabled_switch: ft.Control | None = None
        self.proxy_address_field: ft.TextField | None = None
        self.monitor_interval_field: ft.TextField | None = None
        self.settings_status_text: ft.Text | None = None
        self.settings_search_field: ft.TextField | None = None
        self.storage_status_text: ft.Text | None = None
        self.performance_observability_text: ft.Text | None = None
        self.runtime_preset_status_text: ft.Text | None = None
        self.cookie_test_status_text: ft.Text | None = None
        self.cookie_inventory_status_text: ft.Text | None = None
        self.proxy_status_text: ft.Text | None = None
        self.save_button: ft.Control | None = None
        self._settings_sections: list[tuple[ft.Control, str]] = []
        self._last_form_signature: str = ""
        self._dirty: bool = False
        self._saving: bool = False
        self._pending_confirmation: tuple[str, float] | None = None
        self._toggle_values: dict[str, bool] = {}
        self._toggle_controls: dict[str, ft.Control] = {}
        self._toggle_labels: dict[str, str] = {}
        self.account_notify_switches: dict[str, ft.Control] = {}
        self.account_notify_values: dict[str, bool] = {}
        self.account_notify_expanded: bool = False
        self.account_notify_page: int = 0
        self.account_notify_search_field: ft.TextField | None = None
        self.account_notify_page_text: ft.Text | None = None
        self._account_notify_accounts_cache: list[Any] = []
        self.account_notify_list_container: ft.Container | None = None
        self.account_notify_toggle_icon: ft.Icon | None = None
        self.account_notify_toggle_text: ft.Text | None = None
        self.account_notify_summary_text: ft.Text | None = None
        self.cookie_tester = None
        self.workflow = SettingsWorkflow(app)
        self.settings_service = SettingsService(app)
        self.backup_service = SettingsBackupService(app)
        self.storage_service = SettingsStorageService(app)
        self.cookie_service = SettingsCookieService(app)
        self.proxy_service = SettingsProxyService(app)
        self.preset_service = SettingsPresetService()
        self.performance_observability = PerformanceObservabilityService(app)
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
        self._toggle_values = {}
        self._toggle_controls = {}
        self._toggle_labels = {}
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
            width=self.WIDE_FIELD_WIDTH,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
            on_change=self.update_download_path_state,
        )
        self.selected_download_path = str(user_config.get("douyin_content_download_path") or "").strip()
        self.filename_template_field = ft.TextField(
            label=self._.get("filename_template", "文件命名模板"),
            value=str(user_config.get("douyin_content_filename_template") or DEFAULT_FILENAME_TEMPLATE),
            hint_text=DEFAULT_FILENAME_TEMPLATE,
            width=self.WIDE_FIELD_WIDTH,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
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
            width=self.WIDE_FIELD_WIDTH,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
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
        self.monitor_batch_concurrency_field = ft.TextField(label="监控并发", value=str(user_config.get("monitor_batch_concurrency", settings.default_config.get("monitor_batch_concurrency", 2))), width=140, keyboard_type=ft.KeyboardType.NUMBER)
        self.batch_parse_size_field = ft.TextField(label="解析批大小", value=str(user_config.get("batch_parse_size", settings.default_config.get("batch_parse_size", 20))), width=140, keyboard_type=ft.KeyboardType.NUMBER)
        self.batch_download_concurrency_field = ft.TextField(label="批量下载并发", value=str(user_config.get("batch_download_concurrency", settings.default_config.get("batch_download_concurrency", 3))), width=150, keyboard_type=ft.KeyboardType.NUMBER)
        self.download_chunk_size_field = ft.TextField(label="下载块 KB", value=str(user_config.get("download_chunk_size_kb", settings.default_config.get("download_chunk_size_kb", 512))), width=140, keyboard_type=ft.KeyboardType.NUMBER)
        self.gallery_image_concurrency_field = ft.TextField(label="图集图片并发", value=str(user_config.get("gallery_image_concurrency", settings.default_config.get("gallery_image_concurrency", 4))), width=150, keyboard_type=ft.KeyboardType.NUMBER)
        self.gallery_image_save_format_dropdown = ft.Dropdown(
            label="图集保存格式",
            value=str(user_config.get("gallery_image_save_format") or settings.default_config.get("gallery_image_save_format", "original")),
            width=180,
            options=[
                ft.dropdown.Option("original", "保留原格式"),
                ft.dropdown.Option("png", "统一转 PNG"),
            ],
        )
        if self.gallery_image_save_format_dropdown.value not in {"original", "png"}:
            self.gallery_image_save_format_dropdown.value = "original"
        self.cookie_cooldown_field = ft.TextField(label="Cookie 冷却秒", value=str(user_config.get("douyin_cookie_cooldown_seconds", settings.default_config.get("douyin_cookie_cooldown_seconds", 600))), width=150, keyboard_type=ft.KeyboardType.NUMBER)
        self.incremental_pages_field = ft.TextField(label="增量页数", value=str(user_config.get("douyin_monitor_incremental_pages", settings.default_config.get("douyin_monitor_incremental_pages", 3))), width=130, keyboard_type=ft.KeyboardType.NUMBER)
        self.segmented_parts_field = ft.TextField(label="分片数", value=str(user_config.get("segmented_download_parts", settings.default_config.get("segmented_download_parts", 4))), width=110, keyboard_type=ft.KeyboardType.NUMBER)
        self.segmented_min_size_field = ft.TextField(label="分片阈值 MB", value=str(user_config.get("segmented_download_min_size_mb", settings.default_config.get("segmented_download_min_size_mb", 50))), width=140, keyboard_type=ft.KeyboardType.NUMBER)
        self.monitor_fast_switch = self._make_toggle_button("monitor_fast_check_enabled", "监控快速增量检测", bool(user_config.get("monitor_fast_check_enabled", True)))
        self.development_bypass_switch = self._make_toggle_button(
            "development_bypass_risk_controls_enabled",
            "开发模式：跳过冷却/限速/退避",
            bool(user_config.get("development_bypass_risk_controls_enabled", False)),
            tooltip="调试阶段可开启；开启后后端会跳过 Cookie 冷却、全局限速和风控退避。正式长期运行建议关闭。",
        )
        self.global_rate_limiter_switch = self._make_toggle_button("global_request_limiter_enabled", "全局请求限速", bool(user_config.get("global_request_limiter_enabled", True)))
        self.cookie_cooldown_enabled_switch = self._make_toggle_button("cookie_cooldown_enabled", "Cookie 失败冷却", bool(user_config.get("cookie_cooldown_enabled", True)))
        self.risk_backoff_switch = self._make_toggle_button("risk_backoff_enabled", "风控退避", bool(user_config.get("risk_backoff_enabled", True)))
        self.cookie_health_persistence_switch = self._make_toggle_button("cookie_health_persistence_enabled", "Cookie 健康度持久化", bool(user_config.get("cookie_health_persistence_enabled", True)))
        self.pipeline_download_switch = self._make_toggle_button("batch_parse_download_pipeline_enabled", "批量解析后立即下载", bool(user_config.get("batch_parse_download_pipeline_enabled", False)))
        self.segmented_download_switch = self._make_toggle_button("segmented_download_enabled", "大视频分片下载", bool(user_config.get("segmented_download_enabled", False)))
        self.auto_update_enabled_switch = self._make_toggle_button("auto_update_enabled", "自动更新检查", bool(user_config.get("auto_update_enabled", False)))
        self.auto_update_startup_switch = self._make_toggle_button("auto_update_check_on_startup", "启动时检查更新", bool(user_config.get("auto_update_check_on_startup", False)))
        self.auto_update_silent_switch = self._make_toggle_button("auto_update_silent_install", "安装器静默更新", bool(user_config.get("auto_update_silent_install", False)))
        self.auto_update_manifest_url_field = ft.TextField(label="更新清单 URL", value=str(user_config.get("auto_update_manifest_url") or ""), hint_text="https://example.com/update_manifest.json", width=self.WIDE_FIELD_WIDTH, height=self.SINGLE_LINE_FIELD_HEIGHT)
        self.auto_update_channel_dropdown = ft.Dropdown(label="更新通道", value=str(user_config.get("auto_update_channel") or "stable"), width=150, options=[ft.dropdown.Option("stable", "稳定版"), ft.dropdown.Option("beta", "Beta"), ft.dropdown.Option("dev", "Dev")])
        self.auto_update_install_kind_dropdown = ft.Dropdown(label="更新包类型", value=str(user_config.get("auto_update_install_kind") or "installer"), width=160, options=[ft.dropdown.Option("installer", "安装包"), ft.dropdown.Option("portable", "便携包")])
        self.auto_update_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
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
        self.proxy_enabled_switch = self._make_toggle_button(
            "enable_proxy",
            self._.get("enable_proxy", "开启代理"),
            bool(user_config.get("enable_proxy", False)),
        )
        self.proxy_address_field = ft.TextField(
            label=self._.get("proxy_address", "代理地址"),
            value=str(user_config.get("proxy_address") or ""),
            hint_text="http://127.0.0.1:7890",
            width=self.WIDE_FIELD_WIDTH,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
        )
        self.monitor_interval_field = ft.TextField(
            label=self._.get("monitor_interval", "监控间隔（分钟）"),
            value=str(user_config.get("douyin_content_monitor_interval_minutes", 10)),
            width=220,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        self.settings_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.settings_search_field = ft.TextField(
            label="搜索设置",
            hint_text="Cookie / 代理 / 下载 / 并发 / 更新 / 备份",
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            on_change=self.filter_settings_sections,
        )
        self.storage_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.performance_observability_text = ft.Text(self.performance_observability.compact_text(), size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.runtime_preset_status_text = ft.Text("选择运行模式后只会修改表单，点击保存后才会生效。", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_test_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_inventory_status_text = ft.Text(
            self.cookie_service.summarize_pair(
                self._format_cookie_pool_for_field(cookies_config, "douyin"),
                str(cookies_config.get("tiktok_cookie") or ""),
            ),
            size=12,
            selectable=True,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self.proxy_status_text = ft.Text(
            SettingsProxyService.validate(str(user_config.get("proxy_address") or ""), enabled=bool(user_config.get("enable_proxy", False))).summary(),
            size=12,
            selectable=True,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self.account_notify_switches = {}
        self.account_notify_values = {}
        self.account_notify_page = 0
        self.account_notify_search_field = None
        self.account_notify_page_text = None
        self._account_notify_accounts_cache = []
        self.account_notify_list_container = None
        self.account_notify_toggle_icon = None
        self.account_notify_toggle_text = None
        self.account_notify_summary_text = None
        self._settings_sections = []
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
                self.settings_search_field,
                self._section(
                    "基础",
                    [
                        self.language_dropdown,
                    ],
                ),
                self._section(
                    "存储",
                    [
                        self.download_path_field,
                        ft.Row(
                            [
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
                                ft.OutlinedButton(
                                    "检查目录",
                                    icon=ft.Icons.FACT_CHECK,
                                    on_click=lambda e: self.run_async(self.inspect_storage_dir()),
                                ),
                                ft.OutlinedButton(
                                    "打开目录",
                                    icon=ft.Icons.FOLDER,
                                    on_click=lambda e: self.run_async(self.open_current_storage_dir()),
                                ),
                                ft.OutlinedButton(
                                    "扫描残留",
                                    icon=ft.Icons.POLICY,
                                    on_click=lambda e: self.run_async(self.scan_storage_residue()),
                                ),
                                ft.OutlinedButton(
                                    "清理临时文件",
                                    icon=ft.Icons.DELETE_SWEEP,
                                    on_click=lambda e: self.run_async(self.cleanup_storage_residue()),
                                ),
                            ],
                            spacing=10,
                            wrap=True,
                        ),
                        self.storage_status_text,
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
                                ft.OutlinedButton("分析 Cookie 池", icon=icon("INVENTORY_2", "LIST_ALT"), on_click=lambda e: self.analyze_cookie_pool()),
                                ft.OutlinedButton(self._.get("test_douyin_cookie", "测试抖音 Cookie"), icon=ft.Icons.VERIFIED, on_click=lambda e: self.run_async(self.test_cookie("douyin"))),
                                ft.OutlinedButton("测试全部抖音 Cookie", icon=icon("PLAYLIST_ADD_CHECK", "CHECKLIST"), on_click=lambda e: self.run_async(self.test_cookie_pool("douyin"))),
                                ft.OutlinedButton(self._.get("test_tiktok_cookie", "测试 TikTok Cookie"), icon=ft.Icons.VERIFIED_USER, on_click=lambda e: self.run_async(self.test_cookie("tiktok"))),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        self.cookie_test_status_text,
                        self.cookie_inventory_status_text,
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
                    "运行模式预设",
                    [
                        ft.Text("一键套用推荐参数，只修改当前表单；确认无误后点击保存才会写入配置。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Row([
                            ft.OutlinedButton("稳定长期运行", icon=icon("SHIELD", "SECURITY"), on_click=lambda e: self.run_async(self.apply_runtime_preset("stable"))),
                            ft.OutlinedButton("标准日常使用", icon=icon("BALANCE", "TUNE"), on_click=lambda e: self.run_async(self.apply_runtime_preset("standard"))),
                            ft.OutlinedButton("高速批量处理", icon=icon("SPEED", "FLASH_ON"), on_click=lambda e: self.run_async(self.apply_runtime_preset("fast"))),
                            ft.OutlinedButton("开发诊断模式", icon=icon("BUG_REPORT", "BUILD"), on_click=lambda e: self.run_async(self.apply_runtime_preset("diagnostic"))),
                        ], spacing=8, wrap=True),
                        self.runtime_preset_status_text,
                    ],
                ),
                self._section(
                    "性能与批量",
                    [
                        ft.Text("根据账号数量、Cookie 质量和网络环境调整；过高并发会增加风控概率。开发阶段可临时跳过冷却、限速和退避。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Row([self.monitor_batch_concurrency_field, self.batch_parse_size_field, self.batch_download_concurrency_field, self.gallery_image_concurrency_field, self.gallery_image_save_format_dropdown], spacing=8, wrap=True),
                        ft.Row([self.download_chunk_size_field, self.cookie_cooldown_field, self.incremental_pages_field], spacing=8, wrap=True),
                        ft.Container(
                            content=ft.Column([
                                ft.Row([self.development_bypass_switch], spacing=8, wrap=True),
                                ft.Row([self.monitor_fast_switch, self.global_rate_limiter_switch, self.cookie_cooldown_enabled_switch, self.risk_backoff_switch, self.cookie_health_persistence_switch], spacing=8, wrap=True),
                                ft.Text("开发模式开启后会覆盖下方冷却/限速/退避开关；正式运行建议关闭开发模式，并按需开启限速和冷却。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ], spacing=4),
                            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                            border_radius=8,
                            padding=10,
                        ),
                        ft.Row([self.pipeline_download_switch, self.segmented_download_switch, self.segmented_parts_field, self.segmented_min_size_field], spacing=8, wrap=True),
                        ft.Row([
                            ft.OutlinedButton("刷新性能状态", icon=ft.Icons.QUERY_STATS, on_click=lambda e: self.refresh_performance_observability()),
                            ft.OutlinedButton("清理 Cookie 健康记录", icon=ft.Icons.CLEANING_SERVICES, on_click=lambda e: self.run_async(self.clear_cookie_health_records())),
                        ], spacing=8, wrap=True),
                        self.performance_observability_text,
                    ],
                ),
                self._section(
                    "安装包与自动更新",
                    [
                        ft.Text("正式发布建议使用 Windows 安装包；自动更新通过远程 update_manifest.json 检查版本。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Row([self.auto_update_enabled_switch, self.auto_update_startup_switch, self.auto_update_silent_switch], spacing=8, wrap=True),
                        ft.Row([self.auto_update_channel_dropdown, self.auto_update_install_kind_dropdown], spacing=8, wrap=True),
                        self.auto_update_manifest_url_field,
                        ft.Row([
                            ft.OutlinedButton("检查更新", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=lambda e: self.run_async(self.check_auto_update())),
                        ], spacing=8, wrap=True),
                        self.auto_update_status_text,
                    ],
                ),
                self._section(
                    self._.get("monitor_settings", "监控设置"),
                    [
                        self.monitor_interval_field,
                                    self.proxy_address_field,
                        ft.Row([
                            ft.OutlinedButton("校验代理格式", icon=icon("RULE", "FACT_CHECK"), on_click=lambda e: self.validate_proxy_settings()),
                            ft.OutlinedButton("测试代理", icon=icon("NETWORK_CHECK", "WIFI"), on_click=lambda e: self.run_async(self.test_proxy_settings())),
                        ], spacing=8, wrap=True),
                        self.proxy_status_text,
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
                                ft.IconButton(
                                    icon=ft.Icons.SECURITY,
                                    tooltip="导出脱敏备份（不含 Cookie 和登录凭证，适合上传 GitHub 前自查）",
                                    on_click=lambda e: self.run_async(self.export_sanitized_backup()),
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
                self._settings_action_row(),
            ]
        )
        self.update_filename_preview()
        self._begin_edit_tracking()
        self.content_area.update()

    async def _load_fallback(self, reason: str) -> None:
        """Load a minimal recovery settings page.

        兼容模式只保留最关键的可恢复配置，避免完整设置页失败后再次渲染
        大量 Switch、账号列表和高级参数导致二次空白或灰色块。
        """
        self.content_area.scroll = ft.ScrollMode.AUTO
        self._toggle_values = {}
        self._toggle_controls = {}
        self._toggle_labels = {}
        settings = self.app.services.settings_config
        user_config = dict(getattr(settings, "user_config", {}) or {})
        cookies_config = dict(getattr(settings, "cookies_config", {}) or {})
        self._reset_optional_controls_for_fallback()
        self.download_path_field = ft.TextField(
            label="视频保存路径",
            value=str(user_config.get("douyin_content_download_path") or ""),
            hint_text=os.path.join(self.app.run_path, "downloads", "douyin_content"),
            width=self.WIDE_FIELD_WIDTH,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
            on_change=self.update_download_path_state,
        )
        self.selected_download_path = str(user_config.get("douyin_content_download_path") or "").strip()
        self.douyin_cookie_field = ft.TextField(
            label="抖音 Cookie（可每行一个）",
            value=self._format_cookie_pool_for_field(cookies_config, "douyin"),
            hint_text="多个 Cookie 请每行一个。兼容模式只保存基础 Cookie 配置。",
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
        self.proxy_enabled_switch = self._make_toggle_button("enable_proxy", "开启代理", bool(user_config.get("enable_proxy", False)))
        self.proxy_address_field = ft.TextField(label="代理地址", value=str(user_config.get("proxy_address") or ""), width=self.WIDE_FIELD_WIDTH, height=self.SINGLE_LINE_FIELD_HEIGHT)
        self.settings_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.storage_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_test_status_text = ft.Text("", size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.cookie_inventory_status_text = ft.Text(self.cookie_service.summarize_pair(self._format_cookie_pool_for_field(cookies_config, "douyin"), str(cookies_config.get("tiktok_cookie") or "")), size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self.proxy_status_text = ft.Text(SettingsProxyService.validate(str(user_config.get("proxy_address") or ""), enabled=bool(user_config.get("enable_proxy", False))).summary(), size=12, selectable=True, color=ft.Colors.ON_SURFACE_VARIANT)
        self._settings_sections = []
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                ft.Row(
                    [
                        ft.Text("设置", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.Container(
                            content=ft.Text("兼容模式", size=12, color=ft.Colors.WHITE),
                            bgcolor=ft.Colors.ORANGE,
                            border_radius=8,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                        ),
                    ],
                    spacing=8,
                ),
                ft.Container(
                    content=ft.Text(
                        f"完整设置页加载失败：{reason}\n已切换到最小可用设置页，只保留存储路径、Cookie 和代理配置。",
                        selectable=True,
                        color=ft.Colors.ERROR,
                    ),
                    border=ft.Border.all(1, ft.Colors.ERROR),
                    border_radius=8,
                    padding=12,
                ),
                self._section(
                    "基础恢复配置",
                    [
                        self.download_path_field,
                        ft.Row(
                            [
                                ft.OutlinedButton("选择存储目录", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: self.run_async(self.choose_storage_dir())),
                                ft.FilledButton("应用路径", icon=ft.Icons.CHECK, on_click=lambda e: self.run_async(self.apply_storage_dir())),
                                ft.OutlinedButton("检查目录", icon=ft.Icons.FACT_CHECK, on_click=lambda e: self.run_async(self.inspect_storage_dir())),
                                ft.OutlinedButton("打开目录", icon=ft.Icons.FOLDER, on_click=lambda e: self.run_async(self.open_current_storage_dir())),
                                ft.OutlinedButton("扫描残留", icon=ft.Icons.POLICY, on_click=lambda e: self.run_async(self.scan_storage_residue())),
                                ft.OutlinedButton("清理临时文件", icon=ft.Icons.DELETE_SWEEP, on_click=lambda e: self.run_async(self.cleanup_storage_residue())),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        self.storage_status_text,
                        ft.Row(
                            [
                                ft.OutlinedButton("显示/隐藏 Cookie", icon=ft.Icons.VISIBILITY, on_click=self.toggle_cookie_visibility),
                                ft.OutlinedButton("分析 Cookie 池", icon=icon("INVENTORY_2", "LIST_ALT"), on_click=lambda e: self.analyze_cookie_pool()),
                                ft.OutlinedButton("测试抖音 Cookie", icon=ft.Icons.VERIFIED, on_click=lambda e: self.run_async(self.test_cookie("douyin"))),
                            ],
                            spacing=8,
                            wrap=True,
                        ),
                        self.cookie_test_status_text,
                        self.cookie_inventory_status_text,
                        self.douyin_cookie_field,
                        self.tiktok_cookie_field,
                    ],
                ),
                self._section("代理", [self.proxy_enabled_switch, self.proxy_address_field, ft.Row([ft.OutlinedButton("校验代理格式", icon=icon("RULE", "FACT_CHECK"), on_click=lambda e: self.validate_proxy_settings()), ft.OutlinedButton("测试代理", icon=icon("NETWORK_CHECK", "WIFI"), on_click=lambda e: self.run_async(self.test_proxy_settings()))], spacing=8, wrap=True), self.proxy_status_text]),
                self._settings_action_row(include_reload=True),
            ]
        )
        self._begin_edit_tracking()
        self.content_area.update()


    def _make_toggle_button(self, key: str, label: str, value: bool, tooltip: str | None = None) -> ft.Control:
        """Create a bounded toggle button instead of the native switch widget.

        当前 Windows/Flet 组合中，大量原生开关同时渲染容易增加灰块/卡顿概率。
        设置页统一使用轻量按钮保存布尔状态，业务层仍按 bool 配置读取。
        """
        self._toggle_values[key] = bool(value)
        self._toggle_labels[key] = label
        button = ft.OutlinedButton(
            self._toggle_text(label, bool(value)),
            icon=self._toggle_icon(bool(value)),
            tooltip=tooltip,
            on_click=lambda e, toggle_key=key: self._toggle_button_value(toggle_key),
        )
        self._toggle_controls[key] = button
        return button

    @staticmethod
    def _toggle_icon(value: bool) -> str:
        return ft.Icons.CHECK_CIRCLE if value else ft.Icons.PAUSE_CIRCLE

    @staticmethod
    def _toggle_text(label: str, value: bool) -> str:
        return f"{label}：{'已开启' if value else '已关闭'}"

    def _toggle_value(self, key: str, default: bool = False) -> bool:
        return bool(self._toggle_values.get(key, default))

    def _toggle_button_value(self, key: str) -> None:
        self._set_toggle_value(key, not self._toggle_value(key), update=True)
        self._update_dirty_state()
        if key == "enable_proxy":
            self.validate_proxy_settings()
        if key == "development_bypass_risk_controls_enabled" and self._toggle_value(key):
            self._set_inline_status("settings", "开发模式只适合调试；保存时会再次确认。", ft.Colors.ORANGE)

    def _set_toggle_value(self, key: str, value: Any, *, update: bool = False) -> None:
        bool_value = bool(value)
        self._toggle_values[key] = bool_value
        control = self._toggle_controls.get(key)
        label = self._toggle_labels.get(key, key)
        if control is not None:
            try:
                control.text = self._toggle_text(label, bool_value)
                control.icon = self._toggle_icon(bool_value)
            except Exception:
                pass
            if update:
                self._safe_update(control)



    async def apply_runtime_preset(self, preset_key: str) -> None:
        result = self.preset_service.apply(self._collect_settings_form_values(), preset_key)
        if result.preset.key == "diagnostic":
            if not await self._confirm_or_arm("apply_diagnostic_preset", "开发诊断模式会把表单切换为跳过冷却、限速和风控退避的配置；保存后不适合长期运行。"):
                return
        self._apply_preset_values_to_controls(result.values)
        self._update_dirty_state()
        if self.runtime_preset_status_text is not None:
            self.runtime_preset_status_text.value = result.summary() + "\n" + result.preset.description
            self.runtime_preset_status_text.color = ft.Colors.PRIMARY
            self._safe_update(self.runtime_preset_status_text)
        await self._show_feedback("settings", result.summary(), success=True, duration=6000)

    def _apply_preset_values_to_controls(self, values: dict[str, Any]) -> None:
        def set_field(field: ft.TextField | None, key: str) -> None:
            if field is not None and key in values:
                field.value = str(values.get(key))
                self._safe_update(field)

        def set_dropdown(dropdown: ft.Dropdown | None, key: str) -> None:
            if dropdown is not None and key in values:
                dropdown.value = str(values.get(key))
                self._safe_update(dropdown)

        def set_toggle(key: str) -> None:
            if key in values:
                self._set_toggle_value(key, values.get(key), update=True)

        set_dropdown(self.download_strategy_dropdown, "download_strategy_preset")
        set_field(self.max_parallel_downloads_field, "max_parallel_downloads")
        set_field(self.parse_concurrency_field, "video_parse_concurrency")
        set_field(self.media_retry_count_field, "media_download_retry_count")
        set_field(self.monitor_batch_concurrency_field, "monitor_batch_concurrency")
        set_field(self.batch_parse_size_field, "batch_parse_size")
        set_field(self.batch_download_concurrency_field, "batch_download_concurrency")
        set_field(self.download_chunk_size_field, "download_chunk_size_kb")
        set_field(self.gallery_image_concurrency_field, "gallery_image_concurrency")
        set_field(self.cookie_cooldown_field, "douyin_cookie_cooldown_seconds")
        set_field(self.incremental_pages_field, "douyin_monitor_incremental_pages")
        set_field(self.segmented_parts_field, "segmented_download_parts")
        set_field(self.segmented_min_size_field, "segmented_download_min_size_mb")
        set_toggle("monitor_fast_check_enabled")
        set_toggle("development_bypass_risk_controls_enabled")
        set_toggle("global_request_limiter_enabled")
        set_toggle("cookie_cooldown_enabled")
        set_toggle("risk_backoff_enabled")
        set_toggle("cookie_health_persistence_enabled")
        set_toggle("batch_parse_download_pipeline_enabled")
        set_toggle("segmented_download_enabled")
        self.refresh_performance_observability()


    def refresh_performance_observability(self) -> None:
        if self.performance_observability_text is None:
            return
        self.performance_observability_text.value = self.performance_observability.compact_text()
        try:
            self.performance_observability_text.update()
        except Exception:
            pass

    async def clear_cookie_health_records(self) -> None:
        if not await self._confirm_or_arm("clear_cookie_health", "清理 Cookie 健康记录会删除当前冷却/失败统计。"):
            return
        cleared = self.performance_observability.clear_cookie_health("douyin")
        self.refresh_performance_observability()
        await self._show_feedback("settings", f"已清理 Cookie 健康记录 {cleared} 条", success=True)

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

    async def inspect_storage_dir(self) -> None:
        path = str((self.download_path_field.value if self.download_path_field else "") or "").strip() or self._storage_dir()
        if self.storage_status_text is not None:
            self.storage_status_text.value = "正在检查存储目录..."
            self.storage_status_text.color = ft.Colors.PRIMARY
            self._safe_update(self.storage_status_text)
        result = await self.storage_service.inspect(path)
        color = ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR
        if self.storage_status_text is not None:
            self.storage_status_text.value = result.summary()
            self.storage_status_text.color = color
            self._safe_update(self.storage_status_text)
        await self._show_feedback("settings", result.summary(), success=result.ok, duration=5000)

    async def scan_storage_residue(self) -> None:
        path = str((self.download_path_field.value if self.download_path_field else "") or "").strip() or self._storage_dir()
        if self.storage_status_text is not None:
            self.storage_status_text.value = "正在扫描存储残留..."
            self.storage_status_text.color = ft.Colors.PRIMARY
            self._safe_update(self.storage_status_text)
        result = await self.storage_service.scan_maintenance(path)
        color = ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR
        if self.storage_status_text is not None:
            self.storage_status_text.value = result.summary()
            self.storage_status_text.color = color
            self._safe_update(self.storage_status_text)
        await self._show_feedback("settings", result.summary(), success=result.ok, duration=6000)

    async def cleanup_storage_residue(self) -> None:
        path = str((self.download_path_field.value if self.download_path_field else "") or "").strip() or self._storage_dir()
        scan = await self.storage_service.scan_maintenance(path)
        if not scan.ok:
            await self._show_feedback("settings", scan.summary(), success=False, duration=6000)
            return
        if scan.temp_files <= 0:
            await self._show_feedback("settings", "未发现可清理的临时下载残留。", success=True, duration=4000)
            if self.storage_status_text is not None:
                self.storage_status_text.value = scan.summary()
                self.storage_status_text.color = ft.Colors.PRIMARY
                self._safe_update(self.storage_status_text)
            return
        if not await self._confirm_or_arm("cleanup_storage_residue", f"将删除 {scan.temp_files} 个临时下载残留，预计释放 {scan.temp_mb:.1f} MB。"):
            return
        if self.storage_status_text is not None:
            self.storage_status_text.value = "正在清理临时下载残留..."
            self.storage_status_text.color = ft.Colors.PRIMARY
            self._safe_update(self.storage_status_text)
        result = await self.storage_service.cleanup_temp_files(path)
        color = ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR
        if self.storage_status_text is not None:
            self.storage_status_text.value = result.summary()
            self.storage_status_text.color = color
            self._safe_update(self.storage_status_text)
        await self._show_feedback("settings", result.summary(), success=result.ok, duration=7000)

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
        self._last_form_signature = self._current_form_signature()
        self._dirty = False
        self._update_dirty_status()
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
        self._last_form_signature = self._current_form_signature()
        self._dirty = False
        self._update_dirty_status()
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
        self._update_dirty_state()

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
        return self.workflow.format_cookie_pool_for_field(cookies_config, platform)

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
        return SettingsWorkflow.looks_like_cookie(cookie)

    def _section(self, title: str, controls: list[ft.Control]) -> ft.Container:
        container = ft.Container(
            content=ft.Column([ft.Text(title, theme_style=ft.TextThemeStyle.TITLE_MEDIUM), *controls], spacing=10),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=14,
        )
        search_text = " ".join([title, self._controls_search_text(controls)]).lower()
        self._settings_sections.append((container, search_text))
        return container

    def _controls_search_text(self, controls: list[ft.Control]) -> str:
        parts: list[str] = []

        def walk(control: Any) -> None:
            if control is None:
                return
            for attr in ("label", "tooltip", "hint_text", "value"):
                value = getattr(control, attr, None)
                if isinstance(value, str) and value:
                    parts.append(value)
            child = getattr(control, "content", None)
            if child is not None:
                walk(child)
            for child in list(getattr(control, "controls", []) or []):
                walk(child)

        for control in controls:
            walk(control)
        return " ".join(parts)

    def filter_settings_sections(self, _=None) -> None:
        query = str((self.settings_search_field.value if self.settings_search_field else "") or "").strip().lower()
        for section, search_text in self._settings_sections:
            section.visible = not query or query in search_text
            self._safe_update(section)

    def _settings_action_row(self, *, include_reload: bool = False) -> ft.Row:
        self.save_button = ft.FilledButton(
            self._.get("save_settings", "保存设置"),
            icon=ft.Icons.SAVE,
            on_click=lambda e: self.run_async(self.save_settings()),
        )
        controls: list[ft.Control] = [self.save_button]
        if include_reload:
            controls.append(ft.OutlinedButton("重新加载完整设置页", icon=ft.Icons.REFRESH, on_click=lambda e: self.run_async(self.load())))
        else:
            controls.append(
                ft.OutlinedButton(
                    self._.get("restore_default_naming", "恢复默认命名"),
                    icon=ft.Icons.RESTART_ALT,
                    on_click=self.reset_filename_template,
                )
            )
        controls.append(self.settings_status_text)
        return ft.Row(controls, spacing=10, wrap=True)

    def _reset_optional_controls_for_fallback(self) -> None:
        self.language_dropdown = None
        self.filename_template_field = None
        self.filename_preview_text = None
        self.backup_dropdown = None
        self.config_import_field = None
        self.download_strategy_dropdown = None
        self.max_parallel_downloads_field = None
        self.parse_concurrency_field = None
        self.media_retry_count_field = None
        self.monitor_batch_concurrency_field = None
        self.batch_parse_size_field = None
        self.batch_download_concurrency_field = None
        self.download_chunk_size_field = None
        self.gallery_image_concurrency_field = None
        self.gallery_image_save_format_dropdown = None
        self.cookie_cooldown_field = None
        self.incremental_pages_field = None
        self.segmented_parts_field = None
        self.segmented_min_size_field = None
        self.monitor_fast_switch = None
        self.development_bypass_switch = None
        self.global_rate_limiter_switch = None
        self.cookie_cooldown_enabled_switch = None
        self.risk_backoff_switch = None
        self.cookie_health_persistence_switch = None
        self.pipeline_download_switch = None
        self.segmented_download_switch = None
        self.auto_update_enabled_switch = None
        self.auto_update_startup_switch = None
        self.auto_update_silent_switch = None
        self.auto_update_manifest_url_field = None
        self.auto_update_channel_dropdown = None
        self.auto_update_install_kind_dropdown = None
        self.auto_update_status_text = None
        self.monitor_interval_field = None
        self.performance_observability_text = None
        self.runtime_preset_status_text = None
        self.account_notify_switches = {}
        self.account_notify_values = {}
        self.account_notify_page = 0
        self.account_notify_search_field = None
        self.account_notify_page_text = None
        self._account_notify_accounts_cache = []
        self.account_notify_list_container = None
        self.account_notify_toggle_icon = None
        self.account_notify_toggle_text = None
        self.account_notify_summary_text = None


    def _account_notify_controls(self) -> list[ft.Control]:
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        accounts = list(getattr(monitor, "accounts", []) or [])
        self._account_notify_accounts_cache = accounts
        self.account_notify_switches = {}
        if not accounts:
            return [ft.Text(self._.get("no_accounts_for_notify", "暂无账号通知设置"), size=12, color=ft.Colors.ON_SURFACE_VARIANT)]

        # Keep the full state in a lightweight dict and render only one page of buttons.
        # This avoids mounting one native switch per account, which is costly on Windows/Flet.
        self.account_notify_values = {
            str(getattr(account, "account_id", "")): bool(getattr(account, "notify_enabled", True))
            for account in accounts
            if str(getattr(account, "account_id", ""))
        }
        self.account_notify_summary_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)
        self.account_notify_page_text = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        self.account_notify_search_field = ft.TextField(
            label="搜索账号通知",
            hint_text="昵称 / 主页 / 账号 ID",
            width=360,
            height=self.SINGLE_LINE_FIELD_HEIGHT,
            dense=True,
            on_change=self.filter_account_notify_list,
        )
        self.account_notify_toggle_icon = ft.Icon(
            ft.Icons.EXPAND_LESS if self.account_notify_expanded else ft.Icons.EXPAND_MORE,
            size=18,
        )
        self.account_notify_toggle_text = ft.Text("收起" if self.account_notify_expanded else "展开", size=12)
        self.account_notify_list_container = ft.Container(
            content=self._account_notify_list_content(),
            visible=self.account_notify_expanded,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        )
        self._update_account_notify_summary()

        header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(self._.get("account_notify", "单账号通知开关"), theme_style=ft.TextThemeStyle.TITLE_SMALL),
                            self.account_notify_summary_text,
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.TextButton(
                        content=ft.Row([self.account_notify_toggle_icon, self.account_notify_toggle_text], spacing=4, tight=True),
                        tooltip="展开或收起单账号通知列表",
                        on_click=self.toggle_account_notify_list,
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=8),
        )
        return [header, self.account_notify_list_container]

    def _account_label(self, account: Any) -> str:
        return str(
            getattr(account, "display_name", "")
            or getattr(account, "douyin_nickname", "")
            or getattr(account, "homepage_url", "")
            or getattr(account, "account_id", "")
        )

    def _filtered_account_notify_accounts(self) -> list[Any]:
        query = str((self.account_notify_search_field.value if self.account_notify_search_field else "") or "").strip().lower()
        accounts = list(self._account_notify_accounts_cache or [])
        if not query:
            return accounts
        return [
            account for account in accounts
            if query in " ".join([
                self._account_label(account),
                str(getattr(account, "homepage_url", "") or ""),
                str(getattr(account, "account_id", "") or ""),
            ]).lower()
        ]

    def _account_notify_page_accounts(self) -> tuple[list[Any], int, int]:
        filtered = self._filtered_account_notify_accounts()
        total_pages = max(1, (len(filtered) + self.ACCOUNT_NOTIFY_PAGE_SIZE - 1) // self.ACCOUNT_NOTIFY_PAGE_SIZE)
        self.account_notify_page = max(0, min(self.account_notify_page, total_pages - 1))
        start = self.account_notify_page * self.ACCOUNT_NOTIFY_PAGE_SIZE
        end = start + self.ACCOUNT_NOTIFY_PAGE_SIZE
        return filtered[start:end], len(filtered), total_pages

    def _account_notify_list_content(self) -> ft.Column:
        page_accounts, filtered_count, total_pages = self._account_notify_page_accounts()
        self.account_notify_switches = {}
        buttons = [self._make_account_notify_button(account) for account in page_accounts]
        if not buttons:
            buttons = [ft.Text("没有匹配的账号", size=12, color=ft.Colors.ON_SURFACE_VARIANT)]
        page_info = f"第 {self.account_notify_page + 1}/{total_pages} 页 · 当前筛选 {filtered_count} 个 · 每页最多 {self.ACCOUNT_NOTIFY_PAGE_SIZE} 个"
        if self.account_notify_page_text is not None:
            self.account_notify_page_text.value = page_info
        return ft.Column(
            controls=[
                ft.Row([
                    self.account_notify_search_field,
                    ft.OutlinedButton("筛选全部开启", icon=ft.Icons.CHECK_CIRCLE, on_click=lambda e: self.set_filtered_account_notify(True)),
                    ft.OutlinedButton("筛选全部关闭", icon=ft.Icons.PAUSE_CIRCLE, on_click=lambda e: self.set_filtered_account_notify(False)),
                ], spacing=8, wrap=True),
                ft.Row([
                    ft.OutlinedButton("上一页", icon=ft.Icons.CHEVRON_LEFT, on_click=lambda e: self.change_account_notify_page(-1)),
                    ft.OutlinedButton("下一页", icon=ft.Icons.CHEVRON_RIGHT, on_click=lambda e: self.change_account_notify_page(1)),
                    self.account_notify_page_text,
                ], spacing=8, wrap=True),
                ft.Container(
                    content=ft.Column(
                        buttons,
                        spacing=4,
                        scroll=ft.ScrollMode.AUTO,
                        height=self.ACCOUNT_NOTIFY_LIST_HEIGHT,
                    ),
                    height=self.ACCOUNT_NOTIFY_LIST_HEIGHT,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=6,
                    padding=ft.Padding.symmetric(horizontal=4, vertical=4),
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
            ],
            spacing=8,
        )

    def _make_account_notify_button(self, account: Any) -> ft.Control:
        account_id = str(getattr(account, "account_id", "") or "")
        label = self._account_label(account)
        value = bool(self.account_notify_values.get(account_id, True))
        button = ft.OutlinedButton(
            self._toggle_text(label, value),
            icon=self._toggle_icon(value),
            on_click=lambda e, target_id=account_id: self.toggle_account_notify_value(target_id),
        )
        self.account_notify_switches[account_id] = button
        return button

    def _refresh_account_notify_list(self) -> None:
        if self.account_notify_list_container is not None:
            self.account_notify_list_container.content = self._account_notify_list_content()
            self._safe_update(self.account_notify_list_container)
        if self.account_notify_page_text is not None:
            self._safe_update(self.account_notify_page_text)
        self._update_account_notify_summary()

    def filter_account_notify_list(self, _=None) -> None:
        self.account_notify_page = 0
        self._refresh_account_notify_list()

    def change_account_notify_page(self, delta: int) -> None:
        self.account_notify_page += int(delta)
        self._refresh_account_notify_list()

    def toggle_account_notify_value(self, account_id: str) -> None:
        if not account_id:
            return
        self.account_notify_values[account_id] = not bool(self.account_notify_values.get(account_id, True))
        self._refresh_account_notify_list()
        self._update_dirty_state()

    def set_filtered_account_notify(self, value: bool) -> None:
        for account in self._filtered_account_notify_accounts():
            account_id = str(getattr(account, "account_id", "") or "")
            if account_id:
                self.account_notify_values[account_id] = bool(value)
        self._refresh_account_notify_list()
        self._update_dirty_state()

    def _update_account_notify_summary(self) -> None:
        if self.account_notify_summary_text is None:
            return
        total = len(self.account_notify_values)
        enabled_count = sum(1 for enabled in self.account_notify_values.values() if bool(enabled))
        disabled_count = max(total - enabled_count, 0)
        self.account_notify_summary_text.value = f"{total} 个账号 · 已开启 {enabled_count} · 已关闭 {disabled_count}"
        self._safe_update(self.account_notify_summary_text)

    def toggle_account_notify_list(self, _=None) -> None:
        self.account_notify_expanded = not self.account_notify_expanded
        if self.account_notify_list_container is not None:
            self.account_notify_list_container.visible = self.account_notify_expanded
            self._safe_update(self.account_notify_list_container)
        if self.account_notify_toggle_icon is not None:
            self.account_notify_toggle_icon.name = ft.Icons.EXPAND_LESS if self.account_notify_expanded else ft.Icons.EXPAND_MORE
            self._safe_update(self.account_notify_toggle_icon)
        if self.account_notify_toggle_text is not None:
            self.account_notify_toggle_text.value = "收起" if self.account_notify_expanded else "展开"
            self._safe_update(self.account_notify_toggle_text)

    def _begin_edit_tracking(self) -> None:
        self._attach_dirty_handlers()
        self._last_form_signature = self._current_form_signature()
        self._dirty = False
        self._update_dirty_status()

    def _attach_dirty_handlers(self) -> None:
        controls: list[Any] = [
            self.language_dropdown,
            self.download_path_field,
            self.filename_template_field,
            self.download_strategy_dropdown,
            self.max_parallel_downloads_field,
            self.parse_concurrency_field,
            self.media_retry_count_field,
            self.monitor_batch_concurrency_field,
            self.batch_parse_size_field,
            self.batch_download_concurrency_field,
            self.download_chunk_size_field,
            self.gallery_image_concurrency_field,
            self.gallery_image_save_format_dropdown,
            self.cookie_cooldown_field,
            self.incremental_pages_field,
            self.segmented_parts_field,
            self.segmented_min_size_field,
            self.monitor_interval_field,
            self.auto_update_manifest_url_field,
            self.auto_update_channel_dropdown,
            self.auto_update_install_kind_dropdown,
            self.douyin_cookie_field,
            self.tiktok_cookie_field,
            self.proxy_address_field,
        ]
        for control in controls:
            self._chain_dirty_handler(control)

    def _chain_dirty_handler(self, control: Any) -> None:
        if control is None or getattr(control, "_settings_dirty_wrapped", False):
            return
        previous = getattr(control, "on_change", None)

        def handler(event, previous=previous):
            if callable(previous):
                previous(event)
            self._update_dirty_state()

        try:
            control.on_change = handler
            setattr(control, "_settings_dirty_wrapped", True)
        except Exception:
            pass

    def _current_form_signature(self) -> str:
        payload = {
            "values": self._collect_settings_form_values(),
            "douyin_cookie": (self.douyin_cookie_field.value if self.douyin_cookie_field else "") or "",
            "tiktok_cookie": (self.tiktok_cookie_field.value if self.tiktok_cookie_field else "") or "",
            "account_notify": self._collect_account_notify_values(),
        }
        try:
            return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except Exception:
            return repr(payload)

    def _update_dirty_state(self) -> None:
        current = self._current_form_signature()
        self._dirty = bool(self._last_form_signature and current != self._last_form_signature)
        self._update_dirty_status()

    def _update_dirty_status(self) -> None:
        if self.settings_status_text is None:
            return
        if self._dirty:
            self.settings_status_text.value = "有未保存修改"
            self.settings_status_text.color = ft.Colors.ORANGE
        elif not self.settings_status_text.value or self.settings_status_text.value == "有未保存修改":
            self.settings_status_text.value = ""
            self.settings_status_text.color = ft.Colors.ON_SURFACE_VARIANT
        self._safe_update(self.settings_status_text)

    def _set_save_busy(self, busy: bool) -> None:
        self._saving = bool(busy)
        if self.save_button is not None:
            try:
                self.save_button.disabled = busy
                if hasattr(self.save_button, "text"):
                    self.save_button.text = "正在保存..." if busy else self._.get("save_settings", "保存设置")
                self._safe_update(self.save_button)
            except Exception:
                pass

    async def _confirm_or_arm(self, key: str, message: str, *, duration: int = 6000) -> bool:
        now = time.monotonic()
        if self._pending_confirmation and self._pending_confirmation[0] == key and self._pending_confirmation[1] > now:
            self._pending_confirmation = None
            return True
        self._pending_confirmation = (key, now + max(3, duration // 1000))
        await self._show_feedback("settings", f"{message} 再次点击同一操作确认。", success=False, duration=duration)
        return False

    def reset_filename_template(self, _=None) -> None:
        if self.filename_template_field is not None:
            self.filename_template_field.value = DEFAULT_FILENAME_TEMPLATE
            self.update_filename_preview()
            self._update_dirty_state()
            self.filename_template_field.update()

    def insert_filename_token(self, token: str) -> None:
        if self.filename_template_field is None:
            return
        current = str(self.filename_template_field.value or "")
        joiner = "" if not current or current.endswith(("_", "-", " ")) else "_"
        self.filename_template_field.value = f"{current}{joiner}{token}"
        self.update_filename_preview()
        self._update_dirty_state()
        try:
            self.filename_template_field.update()
        except Exception:
            pass

    def apply_download_strategy(self, _=None) -> None:
        preset = str((self.download_strategy_dropdown.value if self.download_strategy_dropdown else "") or "standard")
        strategy = self.workflow.strategy_values(preset)
        field_map = {
            "max_parallel_downloads": self.max_parallel_downloads_field,
            "video_parse_concurrency": self.parse_concurrency_field,
            "media_download_retry_count": self.media_retry_count_field,
            "monitor_batch_concurrency": self.monitor_batch_concurrency_field,
            "batch_download_concurrency": self.batch_download_concurrency_field,
            "gallery_image_concurrency": self.gallery_image_concurrency_field,
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
        self._update_dirty_state()

    def update_filename_preview(self, _=None) -> None:
        if self.filename_preview_text is None:
            return
        template = str((self.filename_template_field.value if self.filename_template_field else "") or DEFAULT_FILENAME_TEMPLATE)
        self.filename_preview_text.value = self.workflow.filename_preview(template)
        try:
            self.filename_preview_text.update()
        except Exception:
            pass

    async def restore_selected_backup(self) -> None:
        if not await self._confirm_or_arm("restore_selected_backup", "恢复配置备份会覆盖当前设置。"):
            return
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
        path = await self.backup_service.export_config_package()
        await self.app.snack_bar.show_snack_bar(
            f"配置包已导出：{path.name}。位置：downloads/config_exports",
            bgcolor=ft.Colors.PRIMARY,
            duration=6000,
            show_close_icon=True,
        )

    async def export_full_backup(self) -> None:
        if not await self._confirm_or_arm("export_full_backup", "完整备份可能包含 Cookie 和登录凭证。"):
            return
        path = await self.backup_service.export_full_backup()
        await self.app.snack_bar.show_snack_bar(
            f"完整备份已导出：{path.name}。注意：备份内可能包含 Cookie，请妥善保存。",
            bgcolor=ft.Colors.PRIMARY,
            duration=8000,
            show_close_icon=True,
        )

    async def export_sanitized_backup(self) -> None:
        path = await self.backup_service.export_sanitized_backup()
        await self.app.snack_bar.show_snack_bar(
            f"脱敏备份已导出：{path.name}。不包含 Cookie 和 web_auth 登录凭证。",
            bgcolor=ft.Colors.PRIMARY,
            duration=7000,
            show_close_icon=True,
        )

    async def import_config_package(self) -> None:
        path = Path(str((self.config_import_field.value if self.config_import_field else "") or "").strip())
        result = await self.backup_service.import_config_package(path)
        await self.app.snack_bar.show_snack_bar(
            result.message,
            bgcolor=ft.Colors.PRIMARY if result.success else ft.Colors.ERROR,
            duration=7000,
            show_close_icon=True,
        )
        if result.success:
            await self.load()

    async def import_full_backup(self) -> None:
        if not await self._confirm_or_arm("import_full_backup", "恢复完整备份会覆盖账号、Cookie 和监控配置。"):
            return
        path = Path(str((self.config_import_field.value if self.config_import_field else "") or "").strip())
        result = await self.backup_service.import_full_backup(path)
        await self.app.snack_bar.show_snack_bar(
            result.message,
            bgcolor=ft.Colors.PRIMARY if result.success else ft.Colors.ERROR,
            duration=8000,
            show_close_icon=True,
        )
        if result.success:
            await self.load()

    def _storage_dir(self) -> str:
        return self.workflow.storage_dir()

    async def open_current_storage_dir(self) -> None:
        await self.open_storage_dir()

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

    async def check_auto_update(self) -> None:
        service = getattr(self.app.services, "auto_update_service", None)
        if service is None:
            if self.auto_update_status_text is not None:
                self.auto_update_status_text.value = "自动更新服务未初始化"
                self.auto_update_status_text.color = ft.Colors.ERROR
                self.auto_update_status_text.update()
            return
        manifest_url = str((self.auto_update_manifest_url_field.value if self.auto_update_manifest_url_field else "") or "").strip()
        if not manifest_url:
            if self.auto_update_status_text is not None:
                self.auto_update_status_text.value = "请先填写更新清单 URL。"
                self.auto_update_status_text.color = ft.Colors.ERROR
                self.auto_update_status_text.update()
            return
        if self.auto_update_status_text is not None:
            self.auto_update_status_text.value = "正在检查更新..."
            self.auto_update_status_text.color = ft.Colors.PRIMARY
            self.auto_update_status_text.update()
        try:
            info = await service.check_for_updates(manifest_url)
            if info is None:
                message = "未配置更新清单。"
            elif info.available:
                asset = info.best_asset(preferred_kind=str((self.auto_update_install_kind_dropdown.value if self.auto_update_install_kind_dropdown else "") or "installer"))
                message = f"发现新版本 {info.latest_version}；当前版本 {info.current_version}。"
                if asset is not None:
                    message += f" 推荐下载：{asset.name}"
            else:
                message = f"当前已是最新版本：{info.current_version}"
            if self.auto_update_status_text is not None:
                self.auto_update_status_text.value = message
                self.auto_update_status_text.color = ft.Colors.PRIMARY
                self.auto_update_status_text.update()
        except Exception as exc:
            logger.exception(f"check auto update failed: {exc}")
            if self.auto_update_status_text is not None:
                self.auto_update_status_text.value = f"检查更新失败：{exc}"
                self.auto_update_status_text.color = ft.Colors.ERROR
                self.auto_update_status_text.update()

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
        proxy = (self.proxy_address_field.value or "").strip() if self._toggle_value("enable_proxy", False) else None
        return await self.workflow.default_cookie_test(platform, cookie, proxy)

    def analyze_cookie_pool(self, _=None) -> None:
        douyin_raw = (self.douyin_cookie_field.value if self.douyin_cookie_field else "") or ""
        tiktok_raw = (self.tiktok_cookie_field.value if self.tiktok_cookie_field else "") or ""
        detail = self.cookie_service.summarize_pair(douyin_raw, tiktok_raw)
        douyin_detail = self.cookie_service.analyze("douyin", douyin_raw).details(limit=6)
        message = detail if not douyin_raw.strip() else douyin_detail + "\n" + self.cookie_service.analyze("tiktok", tiktok_raw).summary()
        if self.cookie_inventory_status_text is not None:
            self.cookie_inventory_status_text.value = message
            self.cookie_inventory_status_text.color = ft.Colors.ON_SURFACE_VARIANT
            self._safe_update(self.cookie_inventory_status_text)
        self._set_inline_status("cookie", "Cookie 池分析已更新。", ft.Colors.PRIMARY)

    async def test_cookie_pool(self, platform: str) -> None:
        field = self.douyin_cookie_field if platform == "douyin" else self.tiktok_cookie_field
        raw_cookie = (field.value if field else "") or ""
        pool = parse_cookie_pool(raw_cookie) if platform == "douyin" else ([sanitize_cookie_header(raw_cookie)] if sanitize_cookie_header(raw_cookie) else [])
        label = "抖音" if platform == "douyin" else "TikTok"
        if not pool:
            await self._show_feedback("cookie", f"{label} Cookie 为空，请先粘贴后再测试", success=False)
            return
        max_items = 10
        tested = pool[:max_items]
        self._set_inline_status("cookie", f"正在测试 {label} Cookie 池：0/{len(tested)}...", ft.Colors.PRIMARY)
        tester = self.cookie_tester or self._default_cookie_test
        success_count = 0
        failures: list[str] = []
        for index, cookie in enumerate(tested, start=1):
            if not self._looks_like_cookie(cookie):
                failures.append(f"#{index} 格式可疑")
                continue
            try:
                result = tester(platform, cookie)
                if inspect.isawaitable(result):
                    result = await result
                success = bool(result.get("success")) if isinstance(result, dict) else bool(result)
                reason = str(result.get("reason") if isinstance(result, dict) else ("可用" if success else "不可用"))
                if success:
                    success_count += 1
                else:
                    failures.append(f"#{index} {reason[:80]}")
            except Exception as exc:
                failures.append(f"#{index} 异常：{str(exc)[:80]}")
            self._set_inline_status("cookie", f"正在测试 {label} Cookie 池：{index}/{len(tested)}...", ft.Colors.PRIMARY)
        skipped = max(0, len(pool) - len(tested))
        summary = f"{label} Cookie 池测试完成：成功 {success_count}/{len(tested)}"
        if skipped:
            summary += f"，为避免请求过多已跳过 {skipped} 个"
        if failures:
            summary += "；" + "；".join(failures[:3])
            if len(failures) > 3:
                summary += f"；另有 {len(failures) - 3} 个失败"
        self.analyze_cookie_pool()
        await self._show_feedback("cookie", summary, success=success_count > 0, duration=8000)

    def validate_proxy_settings(self, _=None) -> None:
        enabled = self._toggle_value("enable_proxy", False)
        raw_proxy = (self.proxy_address_field.value if self.proxy_address_field else "") or ""
        result = SettingsProxyService.validate(raw_proxy, enabled=enabled)
        if result.ok and result.enabled and self.proxy_address_field is not None and result.normalized and result.normalized != raw_proxy.strip():
            self.proxy_address_field.value = result.normalized
            self._safe_update(self.proxy_address_field)
            self._update_dirty_state()
        if self.proxy_status_text is not None:
            self.proxy_status_text.value = result.summary()
            self.proxy_status_text.color = ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR
            self._safe_update(self.proxy_status_text)
        self._set_inline_status("settings", result.summary(), ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR)

    async def test_proxy_settings(self) -> None:
        enabled = self._toggle_value("enable_proxy", False)
        raw_proxy = (self.proxy_address_field.value if self.proxy_address_field else "") or ""
        if self.proxy_status_text is not None:
            self.proxy_status_text.value = "正在测试代理连通性..."
            self.proxy_status_text.color = ft.Colors.PRIMARY
            self._safe_update(self.proxy_status_text)
        result = await self.proxy_service.test(raw_proxy, enabled=enabled)
        if result.validation.ok and result.validation.enabled and self.proxy_address_field is not None and result.validation.normalized != raw_proxy.strip():
            self.proxy_address_field.value = result.validation.normalized
            self._safe_update(self.proxy_address_field)
            self._update_dirty_state()
        message = result.summary()
        if self.proxy_status_text is not None:
            self.proxy_status_text.value = message
            self.proxy_status_text.color = ft.Colors.PRIMARY if result.ok else ft.Colors.ERROR
            self._safe_update(self.proxy_status_text)
        await self._show_feedback("settings", message, success=result.ok, duration=6000)

    def _collect_settings_form_values(self) -> dict[str, Any]:
        settings = self.app.services.settings_config
        user_config = getattr(settings, "user_config", {}) or {}

        def field_value(field: ft.TextField | None, config_key: str, default: Any = "") -> Any:
            if field is not None and field.value is not None:
                return field.value
            return user_config.get(config_key, default)

        def dropdown_value(dropdown: ft.Dropdown | None, config_key: str, default: Any = "") -> Any:
            if dropdown is not None and dropdown.value is not None:
                return dropdown.value
            return user_config.get(config_key, default)

        def toggle_value(config_key: str, default: bool = False) -> bool:
            return self._toggle_value(config_key, bool(user_config.get(config_key, default)))

        return {
            "language": dropdown_value(self.language_dropdown, "language", "Chinese"),
            "download_path": field_value(self.download_path_field, "douyin_content_download_path", ""),
            "filename_template": field_value(self.filename_template_field, "douyin_content_filename_template", DEFAULT_FILENAME_TEMPLATE),
            "download_strategy_preset": dropdown_value(self.download_strategy_dropdown, "download_strategy_preset", "standard"),
            "max_parallel_downloads": field_value(self.max_parallel_downloads_field, "max_parallel_downloads", 2),
            "video_parse_concurrency": field_value(self.parse_concurrency_field, "video_parse_concurrency", 4),
            "media_download_retry_count": field_value(self.media_retry_count_field, "media_download_retry_count", 1),
            "monitor_batch_concurrency": field_value(self.monitor_batch_concurrency_field, "monitor_batch_concurrency", 2),
            "batch_parse_size": field_value(self.batch_parse_size_field, "batch_parse_size", 20),
            "batch_download_concurrency": field_value(self.batch_download_concurrency_field, "batch_download_concurrency", 3),
            "download_chunk_size_kb": field_value(self.download_chunk_size_field, "download_chunk_size_kb", 512),
            "gallery_image_concurrency": field_value(self.gallery_image_concurrency_field, "gallery_image_concurrency", 4),
            "gallery_image_save_format": dropdown_value(self.gallery_image_save_format_dropdown, "gallery_image_save_format", "original"),
            "douyin_cookie_cooldown_seconds": field_value(self.cookie_cooldown_field, "douyin_cookie_cooldown_seconds", 600),
            "douyin_monitor_incremental_pages": field_value(self.incremental_pages_field, "douyin_monitor_incremental_pages", 3),
            "segmented_download_parts": field_value(self.segmented_parts_field, "segmented_download_parts", 4),
            "segmented_download_min_size_mb": field_value(self.segmented_min_size_field, "segmented_download_min_size_mb", 50),
            "douyin_content_monitor_interval_minutes": field_value(self.monitor_interval_field, "douyin_content_monitor_interval_minutes", 10),
            "monitor_fast_check_enabled": toggle_value("monitor_fast_check_enabled", True),
            "development_bypass_risk_controls_enabled": toggle_value("development_bypass_risk_controls_enabled", False),
            "global_request_limiter_enabled": toggle_value("global_request_limiter_enabled", True),
            "cookie_cooldown_enabled": toggle_value("cookie_cooldown_enabled", True),
            "risk_backoff_enabled": toggle_value("risk_backoff_enabled", True),
            "cookie_health_persistence_enabled": toggle_value("cookie_health_persistence_enabled", True),
            "batch_parse_download_pipeline_enabled": toggle_value("batch_parse_download_pipeline_enabled", False),
            "segmented_download_enabled": toggle_value("segmented_download_enabled", False),
            "auto_update_enabled": toggle_value("auto_update_enabled", False),
            "auto_update_check_on_startup": toggle_value("auto_update_check_on_startup", False),
            "auto_update_silent_install": toggle_value("auto_update_silent_install", False),
            "auto_update_manifest_url": field_value(self.auto_update_manifest_url_field, "auto_update_manifest_url", ""),
            "auto_update_channel": dropdown_value(self.auto_update_channel_dropdown, "auto_update_channel", "stable"),
            "auto_update_install_kind": dropdown_value(self.auto_update_install_kind_dropdown, "auto_update_install_kind", "installer"),
            "enable_proxy": toggle_value("enable_proxy", False),
            "proxy_address": field_value(self.proxy_address_field, "proxy_address", ""),
        }

    def _collect_account_notify_values(self) -> dict[str, bool]:
        return {str(account_id): bool(value) for account_id, value in self.account_notify_values.items()}

    def _apply_saved_settings_to_controls(self, user_config: dict[str, Any]) -> None:
        def set_field(field: ft.TextField | None, value: Any) -> None:
            if field is not None:
                field.value = "" if value is None else str(value)
                self._safe_update(field)

        def set_dropdown(dropdown: ft.Dropdown | None, value: Any) -> None:
            if dropdown is not None:
                dropdown.value = None if value is None else str(value)
                self._safe_update(dropdown)

        def set_toggle(key: str, value: Any) -> None:
            self._set_toggle_value(key, value, update=True)

        saved_download_path = str(user_config.get("douyin_content_download_path") or "").strip()
        self.selected_download_path = saved_download_path
        set_dropdown(self.language_dropdown, user_config.get("language"))
        set_field(self.download_path_field, saved_download_path)
        set_field(self.filename_template_field, user_config.get("douyin_content_filename_template", DEFAULT_FILENAME_TEMPLATE))
        set_dropdown(self.download_strategy_dropdown, user_config.get("download_strategy_preset", "standard"))
        set_field(self.max_parallel_downloads_field, user_config.get("max_parallel_downloads", 2))
        set_field(self.parse_concurrency_field, user_config.get("video_parse_concurrency", 4))
        set_field(self.media_retry_count_field, user_config.get("media_download_retry_count", 1))
        set_field(self.monitor_batch_concurrency_field, user_config.get("monitor_batch_concurrency", 2))
        set_field(self.batch_parse_size_field, user_config.get("batch_parse_size", 20))
        set_field(self.batch_download_concurrency_field, user_config.get("batch_download_concurrency", 3))
        set_field(self.download_chunk_size_field, user_config.get("download_chunk_size_kb", 512))
        set_field(self.gallery_image_concurrency_field, user_config.get("gallery_image_concurrency", 4))
        set_dropdown(self.gallery_image_save_format_dropdown, user_config.get("gallery_image_save_format", "original"))
        set_field(self.cookie_cooldown_field, user_config.get("douyin_cookie_cooldown_seconds", 600))
        set_field(self.incremental_pages_field, user_config.get("douyin_monitor_incremental_pages", 3))
        set_field(self.segmented_parts_field, user_config.get("segmented_download_parts", 4))
        set_field(self.segmented_min_size_field, user_config.get("segmented_download_min_size_mb", 50))
        set_field(self.monitor_interval_field, user_config.get("douyin_content_monitor_interval_minutes", 10))
        set_toggle("monitor_fast_check_enabled", user_config.get("monitor_fast_check_enabled", True))
        set_toggle("development_bypass_risk_controls_enabled", user_config.get("development_bypass_risk_controls_enabled", False))
        set_toggle("global_request_limiter_enabled", user_config.get("global_request_limiter_enabled", True))
        set_toggle("cookie_cooldown_enabled", user_config.get("cookie_cooldown_enabled", True))
        set_toggle("risk_backoff_enabled", user_config.get("risk_backoff_enabled", True))
        set_toggle("cookie_health_persistence_enabled", user_config.get("cookie_health_persistence_enabled", True))
        set_toggle("batch_parse_download_pipeline_enabled", user_config.get("batch_parse_download_pipeline_enabled", False))
        set_toggle("segmented_download_enabled", user_config.get("segmented_download_enabled", False))
        set_toggle("auto_update_enabled", user_config.get("auto_update_enabled", False))
        set_toggle("auto_update_check_on_startup", user_config.get("auto_update_check_on_startup", False))
        set_toggle("auto_update_silent_install", user_config.get("auto_update_silent_install", False))
        set_field(self.auto_update_manifest_url_field, user_config.get("auto_update_manifest_url", ""))
        set_dropdown(self.auto_update_channel_dropdown, user_config.get("auto_update_channel", "stable"))
        set_dropdown(self.auto_update_install_kind_dropdown, user_config.get("auto_update_install_kind", "installer"))
        set_toggle("enable_proxy", user_config.get("enable_proxy", False))
        set_field(self.proxy_address_field, user_config.get("proxy_address", ""))

    @staticmethod
    def _safe_update(control: ft.Control) -> None:
        try:
            control.update()
        except Exception:
            pass

    async def save_settings(self) -> None:
        if self._saving:
            await self._show_feedback("settings", "设置正在保存，请勿重复点击", success=False, duration=2500)
            return
        raw_values = self._collect_settings_form_values()
        latest_user_config = self.app.services.config_manager.load_user_config() or {}
        if bool(raw_values.get("development_bypass_risk_controls_enabled")) and not bool(latest_user_config.get("development_bypass_risk_controls_enabled", False)):
            if not await self._confirm_or_arm("enable_development_bypass", "将开启开发模式，系统会跳过冷却、限速和风控退避。"):
                return
        self._set_save_busy(True)
        await self._show_feedback("settings", "正在保存设置", success=True)
        raw_douyin_cookie = (self.douyin_cookie_field.value if self.douyin_cookie_field else "") or ""
        raw_tiktok_cookie = (self.tiktok_cookie_field.value if self.tiktok_cookie_field else "") or ""

        # Regression anchors kept here because older tests inspect settings_view.py directly:
        # download_path = (self.download_path_field.value if self.download_path_field else "") or self.selected_download_path or ""
        # saved_user_config = self.app.services.config_manager.load_user_config()
        # saved_download_path != download_path
        # parse_cookie_pool(raw_douyin_cookie)
        # cookies_config["douyin_cookie_pool"] = douyin_cookie_pool
        # douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else ""
        # cookie_sync_warnings / sync {platform} cookie to parser failed
        # Cookie 已保存，但同步到内置解析器时有警告
        try:
            result = await self.settings_service.save(
                raw_values=raw_values,
                raw_douyin_cookie=raw_douyin_cookie,
                raw_tiktok_cookie=raw_tiktok_cookie,
                account_notify_values=self._collect_account_notify_values(),
            )
            self._apply_saved_settings_to_controls(result.user_config)
            if self.douyin_cookie_field is not None:
                self.douyin_cookie_field.value = "\n".join(result.cookies_config.get("douyin_cookie_pool", []) or [])
                self._safe_update(self.douyin_cookie_field)
            if self.tiktok_cookie_field is not None:
                self.tiktok_cookie_field.value = str(result.cookies_config.get("tiktok_cookie") or "")
                self._safe_update(self.tiktok_cookie_field)
            self.analyze_cookie_pool()
            self.validate_proxy_settings()
            self.update_filename_preview()
            self._last_form_signature = self._current_form_signature()
            self._dirty = False
            await self._show_feedback("settings", result.summary(), success=True, duration=8000)
        finally:
            self._set_save_busy(False)


    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Settings UI task failed: {exc}")
            await self._show_feedback("settings", str(exc), success=False, duration=6000)

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
