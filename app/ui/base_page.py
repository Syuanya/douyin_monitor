from __future__ import annotations

import inspect
import os
import subprocess
import sys
import webbrowser
from typing import Any
from urllib.parse import urlparse

import flet as ft

from ..utils.logger import logger


class PageBase:
    def __init__(self, app):
        """Initialize the base page class.

        :param app: The main application object.
        """
        self.app = app
        self.page: ft.Page = app.page
        self.content_area = app.content_area
        self._ = {}

    async def load(self):
        """Load page content into the content area."""
        raise NotImplementedError("Subclasses must implement this method")

    def is_active_page(self) -> bool:
        return getattr(self.app, "current_page_name", getattr(self, "page_name", "")) == getattr(self, "page_name", "")

    def safe_content_update(self) -> bool:
        if not self.is_active_page():
            return False
        try:
            self.content_area.update()
            return True
        except Exception as exc:
            logger.debug(f"content area update failed: {exc}")
            return False

    async def _maybe_await(self, value: Any) -> Any:
        if inspect.isawaitable(value):
            return await value
        return value

    def show_dialog(self, dialog: ft.AlertDialog) -> None:
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    def close_dialog(self, dialog: ft.AlertDialog | None = None) -> None:
        target = dialog or getattr(self.app.dialog_area, "content", None)
        if target is not None:
            try:
                target.open = False
            except Exception as exc:
                logger.debug(f"close dialog failed: {exc}")
        try:
            self.app.dialog_area.update()
        except Exception as exc:
            logger.debug(f"update dialog area failed: {exc}")

    async def copy_to_clipboard(self, text: str, success: str = "已复制", failed: str = "复制失败") -> bool:
        page = getattr(self, "page", None)
        try:
            if page is not None and hasattr(page, "set_clipboard"):
                await self._maybe_await(page.set_clipboard(text))
                await self.app.snack_bar.show_snack_bar(success, bgcolor=ft.Colors.PRIMARY)
                return True
            if page is not None and hasattr(page, "clipboard") and hasattr(page.clipboard, "set"):
                await self._maybe_await(page.clipboard.set(text))
                await self.app.snack_bar.show_snack_bar(success, bgcolor=ft.Colors.PRIMARY)
                return True
            if hasattr(ft, "Clipboard"):
                await self._maybe_await(ft.Clipboard().set(text))
                await self.app.snack_bar.show_snack_bar(success, bgcolor=ft.Colors.PRIMARY)
                return True
        except Exception as exc:
            logger.debug(f"copy to clipboard failed: {exc}")
        await self.app.snack_bar.show_snack_bar(failed, bgcolor=ft.Colors.ERROR)
        return False

    async def open_path_or_url(self, target: str, success: str = "", failed_prefix: str = "打开失败", **kwargs: Any) -> bool:
        # Backward-compatible alias. A previous settings button used
        # error=..., which raised TypeError before the path was opened.
        if kwargs.get("error") and failed_prefix == "打开失败":
            failed_prefix = str(kwargs.get("error") or failed_prefix)
        text = self._normalize_open_target(target)
        if not text:
            await self.app.snack_bar.show_snack_bar(f"{failed_prefix}：路径为空", bgcolor=ft.Colors.ERROR)
            return False
        try:
            if os.path.exists(text):
                self._open_local_path(text)
            elif self._is_url(text) and hasattr(self.page, "launch_url"):
                await self._maybe_await(self.page.launch_url(text))
            elif self._is_url(text):
                webbrowser.open(text)
            else:
                await self.app.snack_bar.show_snack_bar(f"{failed_prefix}：路径不存在：{text}", bgcolor=ft.Colors.ERROR, duration=5000, show_close_icon=True)
                return False
            if success:
                await self.app.snack_bar.show_snack_bar(success, bgcolor=ft.Colors.PRIMARY)
            return True
        except Exception as exc:
            logger.debug(f"open path or url failed: {text}, error={exc}")
            try:
                if os.path.exists(text):
                    self._open_local_path(text)
                elif self._is_url(text):
                    webbrowser.open(text)
                else:
                    raise FileNotFoundError(text)
                if success:
                    await self.app.snack_bar.show_snack_bar(success, bgcolor=ft.Colors.PRIMARY)
                return True
            except Exception as fallback_exc:
                logger.debug(f"fallback open failed: {text}, error={fallback_exc}")
        await self.app.snack_bar.show_snack_bar(f"{failed_prefix}：{text}", bgcolor=ft.Colors.ERROR, duration=5000, show_close_icon=True)
        return False

    @staticmethod
    def _normalize_open_target(target: str) -> str:
        text = str(target or "").strip().strip('"')
        if not text:
            return ""
        if PageBase._is_url(text):
            return text
        return os.path.abspath(os.path.expanduser(text))

    @staticmethod
    def _is_url(target: str) -> bool:
        parsed = urlparse(str(target or ""))
        return parsed.scheme in {"http", "https", "file"}

    @staticmethod
    def _open_local_path(path: str) -> None:
        if hasattr(os, "startfile"):
            os.startfile(path)  # type: ignore[attr-defined]
            return
        if sys.platform == "darwin":
            subprocess.Popen(["open", path])
            return
        subprocess.Popen(["xdg-open", path])

    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"UI task failed: {exc}")
            try:
                await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3500, show_close_icon=True)
            except Exception:
                pass

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
