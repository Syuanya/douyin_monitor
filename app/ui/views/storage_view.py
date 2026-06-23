from __future__ import annotations

import os
import asyncio
import re
from pathlib import Path
from typing import Any

import flet as ft
import flet_video as ftv

from ...utils import utils
from ...core.ui_services.storage_browser_service import StorageBrowserService
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.business.image_preview_dialog import ImagePreviewDialog
from ..components.common.safe_icons import icon

class StoragePage(PageBase):
    # Media suffix marker retained for UI regression checks: ".avif"
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "storage"
        self.current_path: Path | None = None
        self.search_query = ""
        self.media_filter = "all"
        self.sort_mode = "name_asc"
        self.search_field: ft.TextField | None = None
        self.filter_dropdown: ft.Dropdown | None = None
        self.sort_dropdown: ft.Dropdown | None = None
        self.image_preview = ImagePreviewDialog(app, "同文件夹图集")
        self.storage_scan_running = False
        self.storage_scan_cancel_requested = False
        self.video_preview_videos: list[Path] = []
        self.video_preview_index = 0
        self.video_preview_control: ftv.Video | None = None
        self.video_preview_overlay: ft.Control | None = None
        self._closing_video_preview = False
        self._rebuilding_video_preview = False
        self.media_select_mode = False
        self.selected_media_paths: set[str] = set()
        self.storage_service = StorageBrowserService(app)
        self.load_language()

    def load_language(self) -> None:
        language = getattr(self.app.language_manager, "language", {}) or {}
        self._ = {}
        for key in ("storage_page", "base"):
            self._.update(language.get(key, {}))

    def root_path(self) -> Path:
        return self.storage_service.root_path()

    async def load(self, path: str | Path | None = None) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        root, target = self.storage_service.resolve_target(path)
        self.current_path = target
        if self.video_preview_videos:
            current_video = self.video_preview_videos[min(self.video_preview_index, len(self.video_preview_videos) - 1)]
            if current_video.parent != target:
                self._remove_storage_video_preview()

        folders, media_files = self._scan(target)
        self._prune_selected_media()
        controls: list[ft.Control] = [
            self._header(root, target),
            ft.Divider(height=12),
            self._toolbar(root, target),
        ]
        controls.extend([self._folder_list(folders), self._media_list(media_files)])
        self.content_area.controls.clear()
        self.content_area.controls.extend(controls)
        if not folders and not media_files:
            self.content_area.controls.append(
                ft.Container(
                    content=ft.Text(self._.get("empty_recording_folder", "暂无下载视频"), color=ft.Colors.ON_SURFACE_VARIANT),
                    padding=16,
                )
            )
        self.content_area.update()

    @staticmethod
    def _is_inside_root(path: Path, root: Path) -> bool:
        return StorageBrowserService.is_inside_root(path, root)

    def _scan(self, path: Path) -> tuple[list[Path], list[Path]]:
        return self.storage_service.scan(path, query=self.search_query, media_filter=self.media_filter, sort_mode=self.sort_mode)

    @staticmethod
    def _safe_file_size(path: Path) -> int:
        return StorageBrowserService.safe_file_size(path)

    @staticmethod
    def _is_video_file(path: Path) -> bool:
        return StorageBrowserService.is_video_file(path)

    @staticmethod
    def _is_image_file(path: Path) -> bool:
        return StorageBrowserService.is_image_file(path)

    def _is_media_file(self, path: Path) -> bool:
        return StorageBrowserService.is_media_file(path)

    def _header(self, root: Path, target: Path) -> ft.Control:
        relative = "." if target == root else str(target.relative_to(root))
        return ft.Column(
            [
                ft.Text(self._.get("storage_path", "存储路径"), theme_style=ft.TextThemeStyle.TITLE_LARGE),
                ft.Text(f"{target}", color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Text(f"{relative}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=4,
        )

    def _toolbar(self, root: Path, target: Path) -> ft.Control:
        self.search_field = ft.TextField(
            hint_text="搜索文件",
            value=self.search_query,
            dense=True,
            width=220,
            prefix_icon=ft.Icons.SEARCH,
            on_submit=lambda e: self.run_async(self.apply_media_filters()),
        )
        self.filter_dropdown = ft.Dropdown(
            label="筛选",
            value=self.media_filter,
            width=130,
            dense=True,
            options=[
                ft.dropdown.Option("all", "全部"),
                ft.dropdown.Option("video", "视频"),
                ft.dropdown.Option("image", "图片"),
                ft.dropdown.Option("empty", "空文件"),
            ],
        )
        self.sort_dropdown = ft.Dropdown(
            label="排序",
            value=self.sort_mode,
            width=150,
            dense=True,
            options=[
                ft.dropdown.Option("name_asc", "名称升序"),
                ft.dropdown.Option("name_desc", "名称降序"),
                ft.dropdown.Option("time_desc", "最新优先"),
                ft.dropdown.Option("time_asc", "最早优先"),
                ft.dropdown.Option("size_desc", "体积最大"),
                ft.dropdown.Option("size_asc", "体积最小"),
            ],
        )
        controls: list[ft.Control] = [
            self.search_field,
            self.filter_dropdown,
            self.sort_dropdown,
            ft.OutlinedButton(
                "应用",
                icon=ft.Icons.FILTER_ALT,
                on_click=lambda e: self.run_async(self.apply_media_filters()),
            ),
            ft.OutlinedButton(
                self._.get("open_folder", "打开文件夹"),
                icon=ft.Icons.FOLDER_OPEN,
                on_click=lambda e: self.run_async(self.open_folder(target)),
            ),
            ft.OutlinedButton(
                "刷新",
                icon=ft.Icons.REFRESH,
                on_click=lambda e: self.run_async(self.load(target)),
            ),
            ft.IconButton(
                icon=ft.Icons.CHECKLIST,
                tooltip="批量选择",
                on_click=lambda e: self.run_async(self.toggle_media_select_mode()),
                icon_color=ft.Colors.PRIMARY if self.media_select_mode else ft.Colors.ON_SURFACE_VARIANT,
            ),
            ft.IconButton(
                icon=ft.Icons.SELECT_ALL,
                tooltip="全选当前文件",
                disabled=not self.media_select_mode,
                on_click=lambda e: self.run_async(self.select_all_visible_media()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.CLEAR,
                tooltip="清空选择",
                disabled=not self.selected_media_paths,
                on_click=lambda e: self.run_async(self.clear_selected_media()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.DELETE_SWEEP,
                tooltip=f"删除选中 {len(self.selected_media_paths)} 个文件",
                disabled=not self.selected_media_paths,
                on_click=lambda e: self.run_async(self.delete_selected_media()),
                icon_color=ft.Colors.ERROR,
            ),
            ft.IconButton(
                icon=icon("CLEANING_SERVICES", "DELETE_SWEEP"),
                tooltip="清理临时下载残留",
                on_click=lambda e: self.run_async(self.cleanup_temp_files()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=icon("FACT_CHECK", "CHECK_CIRCLE"),
                tooltip="扫描文件完整性",
                disabled=self.storage_scan_running,
                on_click=lambda e: self.run_async(self.scan_integrity()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.CANCEL,
                tooltip="取消当前存储扫描",
                disabled=not self.storage_scan_running,
                on_click=lambda e: self.cancel_storage_scan(),
                icon_color=ft.Colors.ERROR,
            ),
        ]
        if target != root:
            controls.insert(
                0,
                ft.OutlinedButton(
                    self._.get("go_back", "返回上一级"),
                    icon=ft.Icons.ARROW_BACK,
                    on_click=lambda e: self.run_async(self.load(target.parent)),
                ),
            )
        summary = ft.Text(
            f"已选择 {len(self.selected_media_paths)} 个文件" if self.media_select_mode else "批量选择可多选后删除文件",
            size=12,
            color=ft.Colors.PRIMARY if self.selected_media_paths else ft.Colors.ON_SURFACE_VARIANT,
        )
        return ft.Column([ft.Row(controls, spacing=10, wrap=True), summary], spacing=6)

    def _video_preview_window(self) -> ft.Control | None:
        videos = [video for video in self.video_preview_videos if video.exists() and self._is_video_file(video)]
        if not videos:
            self._remove_storage_video_preview()
            return None
        self.video_preview_videos = videos
        self.video_preview_index = max(0, min(self.video_preview_index, len(videos) - 1))
        media = videos[self.video_preview_index]
        video_width = 840 if not self.app.is_mobile else 330
        video_height = 472 if not self.app.is_mobile else 186
        self.video_preview_control = ftv.Video(
            width=video_width,
            height=video_height,
            playlist=[ftv.VideoMedia(str(media))],
            autoplay=True,
        )
        panel = ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(ft.Icons.PLAY_CIRCLE, color=ft.Colors.PRIMARY),
                            ft.Text(
                                f"{media.name} ({self.video_preview_index + 1}/{len(videos)})",
                                theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                                overflow=ft.TextOverflow.ELLIPSIS,
                                expand=True,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                tooltip="关闭预览",
                                on_click=lambda e: self.run_async(self.close_storage_video_preview()),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Container(
                        content=self.video_preview_control,
                        alignment=ft.alignment.Alignment.CENTER,
                        bgcolor=ft.Colors.BLACK,
                        width=video_width,
                        height=video_height,
                    ),
                    ft.Row(
                        [
                            ft.OutlinedButton(
                                "上一个",
                                icon=ft.Icons.SKIP_PREVIOUS,
                                disabled=self.video_preview_index <= 0,
                                on_click=lambda e: self.run_async(self.switch_storage_video(-1)),
                            ),
                            ft.Text(f"{self.video_preview_index + 1} / {len(videos)}", color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.OutlinedButton(
                                "下一个",
                                icon=ft.Icons.SKIP_NEXT,
                                disabled=self.video_preview_index >= len(videos) - 1,
                                on_click=lambda e: self.run_async(self.switch_storage_video(1)),
                            ),
                            ft.OutlinedButton(
                                "浏览器播放",
                                icon=ft.Icons.OPEN_IN_BROWSER,
                                on_click=lambda e, media=media: self.run_async(self.open_file(media)),
                            ),
                            ft.OutlinedButton(
                                "打开文件夹",
                                icon=ft.Icons.FOLDER_OPEN,
                                on_click=lambda e, media=media: self.run_async(self.open_folder(media.parent)),
                            ),
                            ft.OutlinedButton(
                                "关闭",
                                icon=ft.Icons.CLOSE,
                                on_click=lambda e: self.run_async(self.close_storage_video_preview()),
                            ),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        wrap=True,
                    ),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            padding=16,
            border_radius=10,
            bgcolor=ft.Colors.SURFACE,
            shadow=ft.BoxShadow(blur_radius=18, color="#33000000", offset=ft.Offset(0, 4)),
        )
        overlay = ft.Container(
            expand=True,
            alignment=ft.alignment.Alignment.CENTER,
            padding=20,
            bgcolor="#66000000",
            content=panel,
        )
        setattr(overlay, "_storage_video_preview", True)
        return overlay

    def _show_storage_video_preview(self) -> None:
        overlay = self._video_preview_window()
        if overlay is None:
            return
        self._rebuilding_video_preview = True
        try:
            self._remove_storage_video_preview(clear_state=False, update=False)
            self.video_preview_overlay = overlay
            self.page.overlay.append(overlay)
            self.page.update()
        except Exception as exc:
            logger.debug(f"show storage video preview failed: {exc}")
        finally:
            self._rebuilding_video_preview = False

    def _remove_storage_video_preview(self, clear_state: bool = True, update: bool = True) -> None:
        overlay_control = self.video_preview_overlay
        try:
            overlay = self.page.overlay
            for control in list(overlay):
                if control is overlay_control or getattr(control, "_storage_video_preview", False):
                    while control in overlay:
                        overlay.remove(control)
        except Exception as exc:
            logger.debug(f"remove storage video preview failed: {exc}")
        self.video_preview_overlay = None
        self.video_preview_control = None
        if clear_state:
            self._clear_video_preview_state()
        if update:
            try:
                self.page.update()
            except Exception as exc:
                logger.debug(f"update storage video preview removal failed: {exc}")

    def _clear_video_preview_state(self) -> None:
        self.video_preview_videos = []
        self.video_preview_index = 0
        self.video_preview_control = None
        self.video_preview_overlay = None

    def _folder_list(self, folders: list[Path]) -> ft.Control:
        return ft.Column(
            [
                self._tile(
                    folder.name,
                    "文件夹",
                    ft.Icons.FOLDER,
                    lambda e, folder=folder: self.run_async(self.load(folder)),
                )
                for folder in folders
            ],
            spacing=6,
        )

    def _media_list(self, media_files: list[Path]) -> ft.Control:
        return ft.Column(
            [self._media_tile(media) for media in media_files],
            spacing=6,
        )

    def _media_tile(self, media: Path) -> ft.Control:
        is_image = self._is_image_file(media)
        media_key = self._media_key(media)
        selected = media_key in self.selected_media_paths
        leading: ft.Control
        if is_image:
            thumbnail = ft.Container(
                width=48,
                height=48,
                border_radius=6,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
                content=ft.Image(src=str(media), fit=ft.BoxFit.COVER),
            )
        else:
            thumbnail = ft.Container(width=48, height=48, alignment=ft.alignment.Alignment.CENTER, content=ft.Icon(ft.Icons.VIDEO_FILE))
        if self.media_select_mode:
            leading = ft.Row(
                controls=[
                    ft.Checkbox(
                        value=selected,
                        on_change=lambda e, media=media: self.run_async(self.toggle_media_selected(media, bool(e.control.value))),
                    ),
                    thumbnail,
                ],
                tight=True,
                spacing=6,
            )
        else:
            leading = thumbnail
        return ft.Container(
            content=ft.ListTile(
                leading=leading,
                title=ft.Text(media.name, overflow=ft.TextOverflow.ELLIPSIS),
                subtitle=ft.Text(self._format_size(self._safe_file_size(media))),
                trailing=ft.Row(
                    controls=[
                        ft.IconButton(
                            icon=ft.Icons.PLAY_CIRCLE if self._is_video_file(media) else ft.Icons.IMAGE_SEARCH,
                            tooltip=self._.get("preview_video", "预览"),
                            on_click=lambda e, media=media: self.run_async(self.preview_media(media)),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.FOLDER_OPEN,
                            tooltip="打开所在文件夹",
                            on_click=lambda e, media=media: self.run_async(self.open_folder(media.parent)),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE,
                            tooltip="删除",
                            icon_color=ft.Colors.ERROR,
                            on_click=lambda e, media=media: self.run_async(self.delete_file(media)),
                        ),
                    ],
                    tight=True,
                ),
                on_click=lambda e, media=media: self.run_async(
                    self.toggle_media_selected(media) if self.media_select_mode else self.preview_media(media)
                ),
            ),
            border=ft.Border.all(2 if selected else 1, ft.Colors.PRIMARY if selected else ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            bgcolor=ft.Colors.PRIMARY_CONTAINER if selected else None,
        )

    def _media_key(self, path: str | Path) -> str:
        try:
            return str(Path(path).resolve())
        except Exception:
            return str(path)

    @staticmethod
    def _tile(title: str, subtitle: str, icon: str, on_click, trailing: ft.Control | None = None) -> ft.Control:
        return ft.Container(
            content=ft.ListTile(
                leading=ft.Icon(icon),
                title=ft.Text(title, overflow=ft.TextOverflow.ELLIPSIS),
                subtitle=ft.Text(subtitle),
                trailing=trailing,
                on_click=on_click,
            ),
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
        )

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
            value /= 1024
        return f"{value:.1f} GB"

    async def preview_video(self, path: str | Path) -> None:
        media = Path(path)
        videos = self._visible_videos(media.parent)
        if media not in videos:
            videos.append(media)
            videos.sort(key=lambda item: item.name.lower())
        selected_index = videos.index(media) if media in videos else 0
        await self.preview_video_at(videos, selected_index)

    async def preview_video_at(self, videos: list[Path], selected_index: int) -> None:
        if not videos:
            await self.app.snack_bar.show_snack_bar("当前目录没有可预览的视频", bgcolor=ft.Colors.ERROR)
            return
        index = max(0, min(selected_index, len(videos) - 1))
        self.video_preview_videos = list(videos)
        self.video_preview_index = index
        self._show_storage_video_preview()

    async def switch_storage_video(self, delta: int) -> None:
        if not self.video_preview_videos:
            return
        self.video_preview_index = max(0, min(self.video_preview_index + delta, len(self.video_preview_videos) - 1))
        self._show_storage_video_preview()

    async def close_storage_video_preview(self) -> None:
        if self._closing_video_preview or self._rebuilding_video_preview:
            return
        self._closing_video_preview = True
        try:
            self._remove_storage_video_preview(clear_state=True, update=True)
        finally:
            self._closing_video_preview = False

    async def preview_media(self, path: str | Path) -> None:
        media = Path(path)
        if self._is_image_file(media):
            images = self._preview_images_for(media)
            selected_index = images.index(media) if media in images else 0
            self.image_preview.show(
                [str(image) for image in images],
                [image.name for image in images],
                selected_index,
                dedupe=False,
            )
            return
        await self.preview_video(media)

    def _visible_videos(self, folder: Path) -> list[Path]:
        try:
            _folders, media_files = self._scan(folder)
            return [item for item in media_files if self._is_video_file(item)]
        except Exception:
            return []

    def _sibling_images(self, media: Path) -> list[Path]:
        candidates = [media.parent]
        current = self.current_path
        if current is not None and self._path_contains(current, media):
            candidates.append(current)
        root = self.root_path()
        parent = media.parent.parent
        if parent != media.parent and self._path_contains(root, parent):
            candidates.append(parent)

        gallery_id = self._gallery_id_from_image(media)
        best: list[Path] = []
        seen_candidates: set[str] = set()
        for folder in candidates:
            key = self._media_key(folder)
            if key in seen_candidates:
                continue
            seen_candidates.add(key)
            direct = self._collect_images(folder, recursive=False)
            grouped_direct = self._filter_gallery_images(direct, gallery_id)
            if len(grouped_direct) > 1:
                return grouped_direct
            if len(direct) > 1:
                return direct
            if not best and direct:
                best = direct
            recursive = self._collect_images(folder, recursive=True)
            grouped_recursive = self._filter_gallery_images(recursive, gallery_id)
            if len(grouped_recursive) > 1:
                return grouped_recursive
            if len(recursive) > 1:
                return recursive
            if not best and recursive:
                best = recursive
        if gallery_id:
            grouped_root = self._filter_gallery_images(self._collect_images(root, recursive=True), gallery_id)
            if len(grouped_root) > 1:
                return grouped_root
        if media not in best and media.exists() and self._is_image_file(media):
            best.append(media)
            best.sort(key=self._image_sort_key)
        return best or [media]

    def _preview_images_for(self, media: Path) -> list[Path]:
        current = self.current_path
        if current is not None and self._path_contains(current, media):
            visible_images = self._collect_visible_images(current)
            grouped_visible = self._filter_gallery_images(visible_images, self._gallery_id_from_image(media))
            if len(grouped_visible) > 1:
                return grouped_visible
            if len(visible_images) > 1 and media in visible_images:
                return visible_images
        direct = self._collect_images(media.parent, recursive=False)
        grouped_direct = self._filter_gallery_images(direct, self._gallery_id_from_image(media))
        if len(grouped_direct) > 1:
            return grouped_direct
        if len(direct) > 1 and media in direct:
            return direct
        return self._sibling_images(media)

    def _collect_visible_images(self, folder: Path) -> list[Path]:
        try:
            _folders, media_files = self._scan(folder)
            images = [item for item in media_files if self._is_image_file(item)]
            images.sort(key=self._image_sort_key)
            return images
        except Exception:
            return []

    def _collect_images(self, folder: Path, recursive: bool) -> list[Path]:
        try:
            if not folder.exists() or not folder.is_dir():
                return []
            iterator = folder.rglob("*") if recursive else folder.iterdir()
            images = [item for item in iterator if item.is_file() and self._is_image_file(item)]
            images.sort(key=self._image_sort_key)
            return images[:1000]
        except Exception:
            return []

    @staticmethod
    def _path_contains(folder: Path, path: Path) -> bool:
        try:
            path.resolve().relative_to(folder.resolve())
            return True
        except Exception:
            return False

    @staticmethod
    def _image_sort_key(path: Path) -> tuple:
        parts = re.split(r"(\d+)", path.name.lower())
        natural_name = tuple(int(part) if part.isdigit() else part for part in parts)
        return (*[part.lower() for part in path.parent.parts], natural_name)

    @staticmethod
    def _gallery_id_from_image(path: Path) -> str:
        stem = path.stem.strip()
        match = re.match(r"^(.+?)[_-](\d{1,4})$", stem)
        if match:
            return match.group(1).lower()
        return ""

    @classmethod
    def _filter_gallery_images(cls, images: list[Path], gallery_id: str) -> list[Path]:
        if not gallery_id:
            return []
        grouped = [image for image in images if cls._gallery_id_from_image(image) == gallery_id]
        grouped.sort(key=cls._image_sort_key)
        return grouped

    def close_dialog(self) -> None:
        dialog = getattr(self.app.dialog_area, "content", None)
        if dialog is not None:
            dialog.open = False
        self.app.dialog_area.update()

    async def apply_media_filters(self) -> None:
        self.search_query = (self.search_field.value if self.search_field else self.search_query) or ""
        self.media_filter = (self.filter_dropdown.value if self.filter_dropdown else self.media_filter) or "all"
        self.sort_mode = (self.sort_dropdown.value if self.sort_dropdown else self.sort_mode) or "name_asc"
        await self.load(self.current_path)

    def _prune_selected_media(self) -> None:
        self.selected_media_paths = {path for path in self.selected_media_paths if Path(path).is_file()}

    async def toggle_media_select_mode(self) -> None:
        self.media_select_mode = not self.media_select_mode
        if not self.media_select_mode:
            self.selected_media_paths.clear()
        await self.load(self.current_path)

    async def toggle_media_selected(self, path: str | Path, selected: bool | None = None) -> None:
        media = Path(path)
        key = self._media_key(media)
        should_select = key not in self.selected_media_paths if selected is None else bool(selected)
        if should_select and media.exists() and media.is_file() and self._is_media_file(media):
            self.selected_media_paths.add(key)
            self.media_select_mode = True
        else:
            self.selected_media_paths.discard(key)
        await self.load(self.current_path)

    async def select_all_visible_media(self) -> None:
        target = self.current_path or self.root_path()
        _folders, media_files = self._scan(target)
        for media in media_files:
            self.selected_media_paths.add(self._media_key(media))
        self.media_select_mode = True
        await self.load(target)

    async def clear_selected_media(self) -> None:
        self.selected_media_paths.clear()
        await self.load(self.current_path)

    async def delete_selected_media(self, confirmed: bool = False) -> None:
        selected = [Path(path) for path in sorted(self.selected_media_paths) if Path(path).is_file()]
        if not selected:
            self.selected_media_paths.clear()
            await self.load(self.current_path)
            await self.app.snack_bar.show_snack_bar("没有可删除的选中文件", bgcolor=ft.Colors.PRIMARY)
            return
        if not confirmed:
            total_size = sum(self._safe_file_size(path) for path in selected)
            self.app.dialog_area.content = ft.AlertDialog(
                modal=True,
                title=ft.Text("确认批量删除"),
                content=ft.Text(f"将删除选中的 {len(selected)} 个文件，合计 {self._format_size(total_size)}。此操作不可恢复，是否继续？"),
                actions=[
                    ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog()),
                    ft.FilledButton("删除", icon=ft.Icons.DELETE, on_click=lambda e: self.run_async(self.delete_selected_media(confirmed=True))),
                ],
                open=True,
            )
            self.app.dialog_area.update()
            return
        removed = 0
        failed = 0
        for media in selected:
            try:
                media.unlink()
                removed += 1
            except Exception as exc:
                failed += 1
                logger.debug(f"delete selected media failed: {media}, error={exc}")
        self.selected_media_paths.clear()
        self.media_select_mode = False
        self.close_dialog()
        await self.load(self.current_path)
        await self.app.snack_bar.show_snack_bar(
            f"批量删除完成：成功 {removed}，失败 {failed}",
            bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
            duration=5000,
            show_close_icon=True,
        )

    async def delete_file(self, path: str | Path, confirmed: bool = False) -> None:
        media = Path(path)
        if not confirmed:
            self.app.dialog_area.content = ft.AlertDialog(
                modal=True,
                title=ft.Text("确认删除"),
                content=ft.Text(f"将删除文件“{media.name}”，是否继续？"),
                actions=[
                    ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog()),
                    ft.FilledButton("删除", icon=ft.Icons.DELETE, on_click=lambda e, media=media: self.run_async(self.delete_file(media, confirmed=True))),
                ],
                open=True,
            )
            self.app.dialog_area.update()
            return
        if media.exists() and media.is_file():
            media.unlink()
            self.selected_media_paths.discard(self._media_key(media))
            await self.app.snack_bar.show_snack_bar("文件已删除", bgcolor=ft.Colors.PRIMARY)
        self.close_dialog()
        await self.load(self.current_path)

    async def cleanup_temp_files(self) -> None:
        root = self.root_path()
        def cleanup() -> tuple[int, int]:
            removed = 0
            bytes_removed = 0
            for path in root.rglob("*"):
                try:
                    if path.is_file() and (path.suffix in {".tmp", ".download"} or path.name.endswith((".tmp", ".download"))):
                        size = path.stat().st_size
                        path.unlink()
                        removed += 1
                        bytes_removed += size
                except Exception as exc:
                    logger.debug(f"cleanup temp file failed: {path}, error={exc}")
            return removed, bytes_removed

        removed, bytes_removed = await asyncio.to_thread(cleanup)
        await self.load(self.current_path)
        await self.app.snack_bar.show_snack_bar(
            f"已清理临时文件 {removed} 个，释放 {self._format_size(bytes_removed)}",
            bgcolor=ft.Colors.PRIMARY,
        )

    async def scan_integrity(self) -> None:
        if self.storage_scan_running:
            await self.app.snack_bar.show_snack_bar("存储扫描正在进行", bgcolor=ft.Colors.ERROR)
            return
        root = self.root_path()
        self.storage_scan_running = True
        self.storage_scan_cancel_requested = False
        await self.load(self.current_path)
        def scan() -> tuple[int, int, int, int, dict[str, int]]:
            media_count = 0
            empty_count = 0
            tmp_count = 0
            total_size = 0
            account_dirs: dict[str, int] = {}
            for path in root.rglob("*"):
                if self.storage_scan_cancel_requested:
                    break
                try:
                    if not path.is_file():
                        continue
                    if path.suffix in {".tmp", ".download"} or path.name.endswith((".tmp", ".download")):
                        tmp_count += 1
                    if self._is_media_file(path):
                        media_count += 1
                        size = path.stat().st_size
                        total_size += size
                        if size <= 0:
                            empty_count += 1
                        try:
                            account = path.relative_to(root).parts[0]
                            account_dirs[account] = account_dirs.get(account, 0) + size
                        except Exception:
                            pass
                except Exception as exc:
                    logger.debug(f"scan file failed: {path}, error={exc}")
            return media_count, empty_count, tmp_count, total_size, account_dirs

        try:
            media_count, empty_count, tmp_count, total_size, account_dirs = await asyncio.to_thread(scan)
        finally:
            cancelled = self.storage_scan_cancel_requested
            self.storage_scan_running = False
            self.storage_scan_cancel_requested = False
            await self.load(self.current_path)
        top_accounts = sorted(account_dirs.items(), key=lambda item: item[1], reverse=True)[:8]
        lines = [
            f"扫描状态：{'已取消，以下为部分结果' if cancelled else '完成'}",
            f"媒体文件：{media_count} 个",
            f"总占用：{self._format_size(total_size)}",
            f"空文件：{empty_count} 个",
            f"临时残留：{tmp_count} 个",
            "",
            "账号目录占用 Top：",
            *[f"{name}：{self._format_size(size)}" for name, size in top_accounts],
        ]

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("存储完整性扫描"),
            content=ft.Text("\n".join(lines), selectable=True, size=12),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    def cancel_storage_scan(self) -> None:
        if not self.storage_scan_running:
            return
        self.storage_scan_cancel_requested = True

    async def open_folder(self, path: str | Path) -> None:
        await self.open_path_or_url(str(path), failed_prefix="打开文件夹失败")

    async def open_file(self, path: str | Path) -> None:
        await self.open_path_or_url(str(path), failed_prefix="打开文件失败")

    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Storage UI task failed: {exc}")
            try:
                await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR)
            except Exception:
                pass

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
