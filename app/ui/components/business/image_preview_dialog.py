from __future__ import annotations

import asyncio
from typing import Sequence

import flet as ft

from ....core.media.image_urls import image_identity_key


class ImagePreviewDialog:
    def __init__(self, app, gallery_label: str):
        self.app = app
        self.gallery_label = gallery_label
        self.dialog: ft.AlertDialog | None = None
        self.title_control: ft.Text | None = None
        self.image_control: ft.Image | None = None
        self.thumb_row: ft.Row | None = None
        self._urls: list[str] = []
        self._titles: list[str] = []
        self._selected_index = 0
        self._zoom = 1.0
        self._closing = False

    def show(
        self,
        urls: Sequence[str],
        titles: Sequence[str] | None = None,
        selected_index: int = 0,
        dedupe: bool = True,
    ) -> None:
        self._close_active_video_preview()
        raw_titles = [str(title) for title in titles] if titles else []
        url_list: list[str] = []
        title_list: list[str] = []
        seen: set[str] = set()
        for index, url in enumerate(urls):
            text = str(url or "").strip()
            if not text:
                continue
            key = image_identity_key(text) if dedupe else text
            if key in seen:
                continue
            seen.add(key)
            url_list.append(text)
            title_list.append(raw_titles[index] if index < len(raw_titles) else "")
        if not url_list:
            return
        selected_index = max(0, min(selected_index, len(url_list) - 1))
        title_list = [
            title if title else f"图片 {index + 1}"
            for index, title in enumerate(title_list)
        ]

        if self.dialog is not None and self.app.dialog_area.content is self.dialog:
            self.update(url_list, title_list, selected_index)
            return

        self.title_control = ft.Text("", max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.image_control = ft.Image(src=url_list[selected_index], fit=ft.BoxFit.CONTAIN)
        self.thumb_row = ft.Row(spacing=8, scroll=ft.ScrollMode.AUTO)
        self.dialog = ft.AlertDialog(
            modal=True,
            title=self.title_control,
            content=ft.Container(
                width=780,
                content=ft.Column(
                    controls=[
                        ft.Container(
                            width=760,
                            height=380,
                            alignment=ft.Alignment(0, 0),
                            content=self.image_control,
                        ),
                        ft.Row(
                            controls=[
                                ft.IconButton(icon=ft.Icons.CHEVRON_LEFT, tooltip="上一张", on_click=lambda e: self.previous()),
                                ft.IconButton(icon=ft.Icons.ZOOM_OUT, tooltip="缩小", on_click=lambda e: self.zoom_out()),
                                ft.IconButton(icon=ft.Icons.FIT_SCREEN, tooltip="适应窗口", on_click=lambda e: self.reset_zoom()),
                                ft.IconButton(icon=ft.Icons.ZOOM_IN, tooltip="放大", on_click=lambda e: self.zoom_in()),
                                ft.IconButton(icon=ft.Icons.CHEVRON_RIGHT, tooltip="下一张", on_click=lambda e: self.next()),
                            ],
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=4,
                        ),
                        ft.Text(self.gallery_label, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Container(height=102, content=self.thumb_row),
                    ],
                    tight=True,
                    spacing=10,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=self.close)],
            actions_alignment=ft.MainAxisAlignment.END,
            on_dismiss=self.close,
            open=True,
        )
        self.update(url_list, title_list, selected_index, update_page=False)
        self.app.dialog_area.content = self.dialog
        self.app.dialog_area.update()

    def _close_active_video_preview(self) -> None:
        dialog = getattr(self.app, "current_video_dialog", None)
        if dialog is None:
            return
        try:
            dialog.open = False
        except Exception:
            pass
        if getattr(self.app.dialog_area, "content", None) is dialog:
            self.app.dialog_area.content = None
        self.app.current_video_dialog = None
        self.app.current_video_control = None
        try:
            self.app.dialog_area.update()
        except Exception:
            pass

    def update(self, urls: Sequence[str], titles: Sequence[str], selected_index: int, update_page: bool = True) -> None:
        if self.title_control is None or self.image_control is None or self.thumb_row is None:
            return
        if not urls:
            return
        selected_index = max(0, min(selected_index, len(urls) - 1))
        self._urls = list(urls)
        self._titles = list(titles)
        self._selected_index = selected_index
        thumb_size = 84
        self.title_control.value = f"{titles[selected_index]}  ({selected_index + 1}/{len(urls)})"
        self.image_control.src = urls[selected_index]
        self.image_control.width = int(760 * self._zoom)
        self.image_control.height = int(380 * self._zoom)
        self.thumb_row.controls = [
            ft.Container(
                width=thumb_size,
                height=thumb_size,
                border=ft.Border.all(2, ft.Colors.PRIMARY if index == selected_index else ft.Colors.TRANSPARENT),
                border_radius=6,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Image(src=url, width=thumb_size, height=thumb_size, fit=ft.BoxFit.COVER),
                on_click=lambda e, index=index: self.update(urls, titles, index),
            )
            for index, url in enumerate(urls)
        ]
        if update_page:
            try:
                self.title_control.update()
                self.image_control.update()
                self.thumb_row.update()
            except Exception:
                self.app.dialog_area.update()

    def close(self, _=None) -> None:
        if self._closing:
            return
        self._closing = True
        dialog = self.dialog
        dialog_area = self.app.dialog_area
        try:
            if dialog is None:
                return
            try:
                dialog.open = False
            except Exception:
                pass
            try:
                dialog_area.update()
            except Exception:
                try:
                    self.app.page.update()
                except Exception:
                    pass
            self.dialog = None
            self.title_control = None
            self.image_control = None
            self.thumb_row = None
            self._urls = []
            self._titles = []
            self._selected_index = 0
            self._zoom = 1.0

            async def detach_closed_dialog():
                await asyncio.sleep(0.2)
                try:
                    if getattr(dialog_area, "content", None) is dialog:
                        dialog_area.content = None
                    if getattr(dialog_area, "_mounted", None) is dialog:
                        dialog_area._mounted = None
                    dialog_area.update()
                except Exception:
                    try:
                        self.app.page.update()
                    except Exception:
                        pass

            try:
                self.app.page.run_task(detach_closed_dialog)
            except Exception:
                try:
                    asyncio.create_task(detach_closed_dialog())
                except Exception:
                    pass
        finally:
            self._closing = False

    def previous(self) -> None:
        if not self._urls:
            return
        self.update(self._urls, self._titles, (self._selected_index - 1) % len(self._urls))

    def next(self) -> None:
        if not self._urls:
            return
        self.update(self._urls, self._titles, (self._selected_index + 1) % len(self._urls))

    def zoom_in(self) -> None:
        self._zoom = min(2.5, self._zoom + 0.25)
        self.update(self._urls, self._titles, self._selected_index)

    def zoom_out(self) -> None:
        self._zoom = max(0.5, self._zoom - 0.25)
        self.update(self._urls, self._titles, self._selected_index)

    def reset_zoom(self) -> None:
        self._zoom = 1.0
        self.update(self._urls, self._titles, self._selected_index)
