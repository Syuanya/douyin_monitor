import asyncio
import inspect
import os
import webbrowser
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import flet as ft
import flet_video as ftv

from ....utils import utils
from ....utils.logger import logger


class VideoPlayer:
    def __init__(self, app):
        self.app = app
        self._ = {}
        self.load_language()

    def load_language(self):
        language = self.app.language_manager.language
        for key in ("video_player", "storage_page", "base"):
            self._.update(language.get(key, {}))

    async def _maybe_await(self, value):
        if inspect.isawaitable(value):
            return await value
        return value

    def _safe_update_dialog_area(self) -> None:
        try:
            self.app.dialog_area.update()
        except Exception as exc:
            logger.debug(f"Update video dialog area failed: {exc}")

    def _close_dialog_only(self, dialog=None, force_detach: bool = False, video_control=None) -> None:
        dialog = dialog or getattr(self.app, "current_video_dialog", None)
        if dialog:
            try:
                dialog.open = False
            except Exception as exc:
                logger.debug(f"Set preview dialog closed failed: {exc}")

        self.app.current_video_dialog = None
        self.app.current_video_control = None
        self._safe_update_dialog_area()

        async def detach_closed_dialog():
            await asyncio.sleep(0.2)
            try:
                if getattr(self.app.dialog_area, "content", None) is dialog:
                    self.app.dialog_area.content = None
                    self.app.dialog_area.update()
            except Exception as exc:
                logger.debug(f"Detach closed video dialog failed: {exc}")

        try:
            self.app.page.run_task(detach_closed_dialog)
        except Exception:
            try:
                asyncio.create_task(detach_closed_dialog())
            except Exception as exc:
                logger.debug(f"Schedule closed video dialog detach failed: {exc}")

    async def _close_existing_video_dialog(self):
        dialog = getattr(self.app, "current_video_dialog", None)
        if dialog or getattr(self.app.dialog_area, "content", None):
            self._close_dialog_only(dialog)
            await asyncio.sleep(0.35)

    async def _copy_to_clipboard(self, text: str) -> bool:
        if not text:
            return False

        page = getattr(self.app, "page", None)
        try:
            if page and hasattr(page, "set_clipboard"):
                await self._maybe_await(page.set_clipboard(text))
                return True
        except Exception as exc:
            logger.debug(f"page.set_clipboard failed: {exc}")

        try:
            if page and hasattr(page, "clipboard") and hasattr(page.clipboard, "set"):
                await self._maybe_await(page.clipboard.set(text))
                return True
        except Exception as exc:
            logger.debug(f"page.clipboard.set failed: {exc}")

        try:
            if hasattr(ft, "Clipboard"):
                await self._maybe_await(ft.Clipboard().set(text))
                return True
        except Exception as exc:
            logger.debug(f"ft.Clipboard().set failed: {exc}")

        return False

    async def _open_url(self, url: str) -> bool:
        if not url:
            return False

        if os.path.exists(url):
            try:
                os.startfile(url)  # type: ignore[attr-defined]
                return True
            except Exception as exc:
                logger.debug(f"os.startfile failed: {exc}")

        page = getattr(self.app, "page", None)
        try:
            if page and hasattr(page, "launch_url"):
                await self._maybe_await(page.launch_url(url))
                return True
        except Exception as exc:
            logger.debug(f"page.launch_url failed: {exc}")

        try:
            return bool(webbrowser.open(url))
        except Exception as exc:
            logger.debug(f"webbrowser.open failed: {exc}")
            return False

    async def open_douyin_playback(self, source_url: str, fallback_url: str = "") -> bool:
        """Open the original Douyin/TikTok page so the platform handles playback."""
        target = self._normalize_room_url(source_url) or fallback_url
        ok = await self._open_url(target or "")
        if not ok and fallback_url and fallback_url != target:
            ok = await self._open_url(fallback_url)
        return ok

    @staticmethod
    def _normalize_room_url(room_url: str | None) -> str | None:
        if not room_url:
            return room_url
        try:
            parsed = urlparse(room_url)
            host = (parsed.netloc or "").lower()
            if any(k in host for k in ("douyin.com", "iesdouyin.com")):
                return parsed._replace(query="", fragment="").geturl()
        except Exception:
            pass
        return room_url

    async def create_video_dialog(
        self,
        title: str,
        video_source: str,
        is_file_path: bool = True,
        room_url: str | None = None,
        copy_source_url: str | None = None,
    ):
        await self._close_existing_video_dialog()

        copy_source_url = copy_source_url or video_source
        room_url = self._normalize_room_url(room_url)
        playback_source = video_source

        dialog_ref = {"dialog": None}

        def close_dialog(_=None):
            self._close_dialog_only(dialog_ref.get("dialog"))

        if self.app.is_mobile:
            video_width = 320
            video_height = 180
        else:
            video_width = 720
            video_height = 405

        video = ftv.Video(
            width=video_width,
            height=video_height,
            playlist=[ftv.VideoMedia(playback_source)],
            autoplay=True,
        )

        async def copy_source(_):
            ok = await self._copy_to_clipboard(copy_source_url)
            if ok:
                await self.app.snack_bar.show_snack_bar(self._["copy_success"])
            else:
                await self.app.snack_bar.show_snack_bar(self._.get("copy_failed", "Copy failed"))

        async def open_in_browser(_):
            ok = await self._open_url(room_url or "")
            if not ok:
                await self.app.snack_bar.show_snack_bar(self._.get("open_failed", "Open failed"))

        async def play_in_browser(_):
            ok = await self._open_url(playback_source)
            if not ok:
                await self.app.snack_bar.show_snack_bar(self._.get("open_failed", "Open failed"))

        async def take_screenshot(_):
            await self._take_screenshot(video, video_source, is_file_path)

        actions = [ft.TextButton(self._["close"], on_click=close_dialog)]
        actions.insert(0, ft.TextButton(self._["screenshot"], on_click=take_screenshot))
        actions.insert(0, ft.TextButton(self._.get("browser_play", "浏览器播放"), on_click=play_in_browser))
        if room_url:
            actions.insert(0, ft.TextButton(self._["open_live_room_page"], on_click=open_in_browser))
        if not is_file_path:
            actions.insert(0, ft.TextButton(self._["copy_video_url"], on_click=copy_source))

        if self.app.is_mobile:
            actions_row = ft.Row(
                controls=actions,
                spacing=5,
                alignment=ft.MainAxisAlignment.CENTER,
                wrap=True,
            )
            video_container = ft.Container(
                content=video,
                alignment=ft.alignment.Alignment.CENTER,
                width=video_width,
                height=video_height,
            )
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(title, overflow=ft.TextOverflow.ELLIPSIS, max_lines=1, size=14),
                content=ft.Column(
                    [video_container, actions_row],
                    spacing=5,
                    alignment=ft.MainAxisAlignment.CENTER,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    tight=True,
                ),
                actions=[],
                inset_padding=ft.Padding.only(left=10, right=10, top=5, bottom=5),
                content_padding=ft.Padding.only(left=5, right=5, top=5, bottom=0),
                on_dismiss=close_dialog,
            )
        else:
            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text(title),
                content=video,
                actions=actions,
                actions_alignment=ft.MainAxisAlignment.END,
                on_dismiss=close_dialog,
            )

        dialog_ref["dialog"] = dialog
        dialog.open = True
        self.app.current_video_dialog = dialog
        self.app.current_video_control = video
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def _take_screenshot(self, video: ftv.Video, video_source: str, is_file_path: bool):
        try:
            image_bytes = await video.take_screenshot(format="image/png")
        except Exception as exc:
            logger.error(f"Failed to take screenshot: {exc}")
            await self.app.snack_bar.show_snack_bar(self._["screenshot_failed"])
            return

        if not image_bytes:
            await self.app.snack_bar.show_snack_bar(self._["screenshot_failed"])
            return

        try:
            if is_file_path and video_source and os.path.isfile(video_source):
                screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(video_source)), "screenshots")
                base_name = Path(video_source).stem
            else:
                screenshot_dir = os.path.join(self.app.run_path, "downloads", "screenshots")
                base_name = "screenshot"
            os.makedirs(screenshot_dir, exist_ok=True)
            filename = f"{base_name}_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.png"
            file_path = os.path.join(screenshot_dir, filename)
            with open(file_path, "wb") as file:
                file.write(image_bytes)
        except Exception as exc:
            logger.error(f"Failed to save screenshot: {exc}")
            await self.app.snack_bar.show_snack_bar(self._["screenshot_failed"])
            return

        logger.info(f"Screenshot saved: {file_path}")
        await self.app.snack_bar.show_snack_bar(
            f"{self._['screenshot_success']}", bgcolor=ft.Colors.PRIMARY, duration=3000
        )

    async def preview_video(
        self,
        source: str,
        is_file_path: bool = True,
        room_url: str | None = None,
        copy_source_url: str | None = None,
    ):
        if is_file_path:
            if not utils.is_valid_video_file(source):
                logger.warning(f"unsupported file type: {Path(source).suffix.lower()}")
                await self.app.snack_bar.show_snack_bar(
                    self._["unsupported_file_type"] + ":" + os.path.basename(source)
                )
                return
            title = os.path.basename(source)
        else:
            parsed = urlparse(source)
            params = parse_qs(parsed.query)
            filename = params.get("filename", [""])[0]
            sub_folder = params.get("subfolder", [""])[0]
            if filename:
                title = self._["previewing"] + ": " + (f"{sub_folder}/{filename}" if sub_folder else filename)
                if Path(filename).suffix.lower() != ".mp4":
                    await self.app.snack_bar.show_snack_bar(self._["unsupported_play_on_web"])
                    return
            else:
                title = self._["view_stream_source_now"]
        await self.create_video_dialog(title, source, is_file_path, room_url, copy_source_url)
