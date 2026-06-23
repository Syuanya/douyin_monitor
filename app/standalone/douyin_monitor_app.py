from __future__ import annotations

import asyncio
import os
import threading
import weakref
from typing import Any

import flet as ft

from ..core.application.service_container import DouyinMonitorServices
from ..core.config.config_manager import ConfigManager
from ..core.config.language_manager import LanguageManager
from ..core.config.settings_config import SettingsConfig
from ..core.content_monitor.facade import DouyinContentMonitorManager
from ..core.media.parsed_media_downloader import ParsedMediaDownloader
from ..core.media.video_parser_service import ParsedVideoResult, VideoParserService
from ..core.runtime.media_task_queue import MediaTaskQueue
from ..core.runtime.task_center import TaskCenter
from ..core.runtime.download_recovery_service import DownloadRecoveryService
from ..core.storage.sqlite_store import SQLiteStore
from ..core.diagnostics.health_check_service import HealthCheckService
from ..ui.components.common.show_snackbar import ShowSnackBar
from ..ui.views.douyin_content_view import DouyinContentMonitorPage
from ..ui.views.download_history_view import DownloadHistoryPage
from ..ui.views.diagnostic_health_view import DiagnosticHealthPage
from ..ui.views.home_dashboard_view import HomeDashboardPage
from ..ui.views.issue_center_view import IssueCenterPage
from ..ui.views.settings_view import SettingsPage
from ..ui.views.startup_wizard import StartupWizard
from ..ui.views.storage_view import StoragePage
from ..ui.views.task_center_view import TaskCenterPage
from ..ui.views.video_parse_view import VideoParsePage
from ..utils.logger import logger

APP_FONT_NAME = "AlibabaPuHuiTi"
APP_FONT_ASSET = "fonts/AlibabaPuHuiTi-2/AlibabaPuHuiTi-2-45-Light.otf"


def configure_page_fonts(page: ft.Page, run_path: str) -> None:
    font_path = os.path.join(run_path, "assets", *APP_FONT_ASSET.split("/"))
    if not os.path.exists(font_path):
        logger.debug(f"App font not found, using default font: {font_path}")
        return
    page.fonts = {APP_FONT_NAME: APP_FONT_ASSET}
    page.theme = ft.Theme(font_family=APP_FONT_NAME)
    page.dark_theme = ft.Theme(font_family=APP_FONT_NAME)


class OverlaySlot:
    def __init__(self, page: ft.Page):
        self.page = page
        self.content: ft.Control | None = None
        self._mounted: ft.Control | None = None

    def clear(self, target: ft.Control | None = None, marker: str = "") -> None:
        overlay = self.page.overlay
        targets = []
        if target is not None:
            targets.append(target)
        if marker:
            targets.extend([control for control in list(overlay) if getattr(control, marker, False)])
        seen: set[int] = set()
        unique_targets = []
        for candidate in targets:
            identity = id(candidate)
            if identity in seen:
                continue
            seen.add(identity)
            unique_targets.append(candidate)
        for control in unique_targets:
            try:
                if hasattr(control, "open"):
                    control.open = False
            except Exception:
                pass
            try:
                while control in overlay:
                    overlay.remove(control)
            except ValueError:
                pass
        if target is None or self.content is target or (marker and getattr(self.content, marker, False)):
            self.content = None
        if target is None or self._mounted is target or (marker and getattr(self._mounted, marker, False)):
            self._mounted = None
        try:
            self.page.update()
        except Exception:
            pass

    def update(self) -> None:
        overlay = self.page.overlay
        if self._mounted is not None and self._mounted is not self.content:
            try:
                overlay.remove(self._mounted)
            except ValueError:
                pass
            self._mounted = None
        if self.content is not None and self.content not in overlay:
            overlay.append(self.content)
            self._mounted = self.content
        elif self.content is not None:
            self._mounted = self.content
        try:
            self.page.update()
        except Exception:
            pass


class DouyinMonitorStandaloneApp:
    """Minimal app shape required by DouyinContentMonitorPage."""

    def __init__(self, page: ft.Page, run_path: str):
        self.page = page
        self.run_path = run_path
        self.assets_dir = os.path.join(run_path, "assets")
        self.services = DouyinMonitorServices(run_path)
        self.config_manager = self.services.config_manager
        self.language_manager = self.services.language_manager
        self.is_web_mode = page.web
        self.is_mobile = False
        self.content_area = ft.Column(
            controls=[],
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.CrossAxisAlignment.START,
        )
        self.nav_area = ft.Column(
            controls=[],
            spacing=8,
            expand=True,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.dialog_area = OverlaySlot(page)
        self.snack_bar_area = OverlaySlot(page)
        self.snack_bar = ShowSnackBar(self)
        self.home_dashboard = HomeDashboardPage(self)
        self.douyin_content = DouyinContentMonitorPage(self)
        self.video_parse = VideoParsePage(self)
        self.settings_page = SettingsPage(self)
        self.storage_page = StoragePage(self)
        self.task_center_page = TaskCenterPage(self)
        self.download_history_page = DownloadHistoryPage(self)
        self.issue_center_page = IssueCenterPage(self)
        self.diagnostic_health_page = DiagnosticHealthPage(self)
        self.startup_wizard = StartupWizard(self)
        self.current_page = self.home_dashboard
        self.current_page_name = self.home_dashboard.page_name
        self.current_video_dialog = None
        self.current_video_control = None
        self.current_preview_relay = None
        self.main_content_area = ft.Column(
            controls=[self.content_area],
            expand=True,
            spacing=0,
        )
        self.shell_area = ft.Row(
            controls=[
                ft.Container(
                    width=172,
                    padding=ft.Padding.only(left=10, top=12, right=10, bottom=12),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
                    content=self.nav_area,
                ),
                ft.VerticalDivider(width=1),
                ft.Container(
                    expand=True,
                    padding=ft.Padding.only(left=18, top=16, right=18, bottom=12),
                    content=self.main_content_area,
                ),
            ],
            expand=True,
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.complete_page = ft.Row(
            expand=True,
            controls=[
                self.shell_area,
            ],
        )
        self.services.register_ui_bridge(self)
        self.refresh_nav()

    def _get_session_loop(self) -> asyncio.AbstractEventLoop | None:
        try:
            session = self.page.session
            if session is None:
                return None
            connection = getattr(session, "connection", None)
            if connection is None:
                return None
            return getattr(connection, "loop", None)
        except Exception:
            return None

    def schedule_snack(self, text: str, **kw: Any) -> None:
        loop = self._get_session_loop()
        if loop is None:
            return
        try:
            asyncio.run_coroutine_threadsafe(self.snack_bar.show_snack_bar(text, **kw), loop)
        except Exception as exc:
            logger.debug(f"standalone douyin schedule_snack dropped: {exc}")

    def schedule_pubsub(self, topic: str, payload: Any) -> None:
        loop = self._get_session_loop()
        if loop is not None and topic == "douyin_monitor_update" and self.current_page_name == self.douyin_content.page_name:
            try:
                asyncio.run_coroutine_threadsafe(self.douyin_content.subscribe_update(payload), loop)
            except Exception as exc:
                logger.debug(f"standalone douyin direct refresh dropped: {exc}")
        try:
            self.page.pubsub.send_others_on_topic(topic, payload)
        except Exception as exc:
            logger.debug(f"standalone douyin schedule_pubsub dropped: {exc}")

    def schedule_card_update(self, _recording: Any) -> None:
        return

    def schedule_card_remove(self, _recordings: Any) -> None:
        return

    async def load(self) -> None:
        await self.current_page.load()

    async def start_periodic_tasks(self) -> None:
        await self.services.douyin_content_monitor.setup_periodic_check()

    async def cleanup(self) -> None:
        try:
            await self.services.douyin_content_monitor.stop_periodic_check()
        except Exception as exc:
            logger.debug(f"douyin content monitor periodic stop skipped: {exc}")
        try:
            await self.services.douyin_content_monitor.flush_persist()
        except Exception as exc:
            logger.debug(f"douyin content monitor flush skipped: {exc}")
        self.services.unregister_ui_bridge(self)

    def refresh_nav(self) -> None:
        sidebar = (getattr(self.language_manager, "language", {}) or {}).get("sidebar", {})
        def nav_button(label: str, icon: str, page_name: str) -> ft.Control:
            selected = self.current_page_name == page_name
            return ft.FilledTonalButton(
                label,
                icon=icon,
                width=150,
                disabled=selected,
                on_click=lambda e, target=page_name: self.page.run_task(self.switch_page, target),
            )

        self.nav_area.controls = [
            ft.Text("功能菜单", size=13, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
            nav_button(sidebar.get("home_dashboard", "主页"), ft.Icons.DASHBOARD, self.home_dashboard.page_name),
            nav_button(sidebar.get("douyin_content", "内容监控"), ft.Icons.VIDEO_LIBRARY, self.douyin_content.page_name),
            nav_button(sidebar.get("video_parse", "视频解析"), ft.Icons.TRAVEL_EXPLORE, self.video_parse.page_name),
            nav_button(sidebar.get("task_center", "任务中心"), ft.Icons.TASK_ALT, self.task_center_page.page_name),
            nav_button(sidebar.get("download_history", "下载历史"), ft.Icons.HISTORY, self.download_history_page.page_name),
            nav_button(sidebar.get("issue_center", "问题中心"), ft.Icons.ERROR_OUTLINE, self.issue_center_page.page_name),
            nav_button(sidebar.get("settings", "设置"), ft.Icons.SETTINGS, self.settings_page.page_name),
            nav_button(sidebar.get("storage", "存储"), ft.Icons.FOLDER_OPEN, self.storage_page.page_name),
            nav_button(sidebar.get("diagnostic_health", "诊断"), ft.Icons.HEALTH_AND_SAFETY, self.diagnostic_health_page.page_name),
            ft.Container(expand=True),
        ]

    async def switch_page(self, page_name: str) -> None:
        if page_name == self.current_page_name:
            return
        if page_name == self.home_dashboard.page_name:
            self.current_page = self.home_dashboard
        elif page_name == self.video_parse.page_name:
            self.current_page = self.video_parse
        elif page_name == self.task_center_page.page_name:
            self.current_page = self.task_center_page
        elif page_name == self.download_history_page.page_name:
            self.current_page = self.download_history_page
        elif page_name == self.issue_center_page.page_name:
            self.current_page = self.issue_center_page
        elif page_name == self.settings_page.page_name:
            self.current_page = self.settings_page
        elif page_name == self.storage_page.page_name:
            self.current_page = self.storage_page
        elif page_name == self.diagnostic_health_page.page_name:
            self.current_page = self.diagnostic_health_page
        else:
            self.current_page = self.douyin_content
        self.current_page_name = self.current_page.page_name
        self.refresh_nav()
        await self.current_page.load()
        self.shell_area.update()


async def main(page: ft.Page, run_path: str) -> None:
    page.title = "Douyin Monitor"
    page.window.min_width = 920
    page.window.min_height = 620
    page.window.width = 1180
    page.window.height = 760
    configure_page_fonts(page, run_path)
    icon_path = os.path.join(run_path, "assets", "icon.ico")
    if os.path.exists(icon_path):
        page.window.icon = icon_path

    app = DouyinMonitorStandaloneApp(page, run_path)
    page.data = app
    theme_mode = app.services.settings_config.user_config.get("theme_mode", "light")
    page.theme_mode = ft.ThemeMode.DARK if theme_mode == "dark" else ft.ThemeMode.LIGHT

    async def on_disconnect(_: ft.ControlEvent) -> None:
        await app.cleanup()

    page.on_disconnect = on_disconnect
    page.add(app.complete_page)
    await app.load()
    await app.startup_wizard.maybe_show()
    page.run_task(app.start_periodic_tasks)
    page.update()
