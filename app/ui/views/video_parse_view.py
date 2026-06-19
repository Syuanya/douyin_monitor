from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

from ...core.media.video_parser_service import ParseFailure, ParsedVideoResult, VideoParseBatchResult, VideoParserService
from ...core.parser.risk_model import classify_parser_failure
from ...core.runtime.task_center import classify_failure
from ...utils.logger import logger
from ..base_page import PageBase
from ..components.business.image_preview_dialog import ImagePreviewDialog
from ..components.business.video_player import VideoPlayer


class VideoParsePage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "video_parse"
        self.input_field: ft.TextField | None = None
        self.result_area: ft.Column | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.submit_button: ft.FilledButton | None = None
        self.reset_button: ft.OutlinedButton | None = None
        self.cancel_button: ft.OutlinedButton | None = None
        self.last_result: VideoParseBatchResult | None = None
        self.result_controls: list[ft.Control] = []
        self.parse_in_progress = False
        self.parse_cancel_requested = False
        self.parse_progress_text = ""
        self.show_result_section = False
        self.parse_history: list[dict[str, Any]] = self._load_parse_history()
        self.image_preview = ImagePreviewDialog(app, "解析图集")
        self.init()

    def init(self) -> None:
        self.input_field = ft.TextField(
            label="请将抖音或 TikTok 的分享口令或网址粘贴于此",
            hint_text="批量解析请直接粘贴多个口令或链接，无需使用符号分开，支持抖音和 TikTok 链接混合。",
            multiline=True,
            min_lines=8,
            max_lines=12,
            border_color=ft.Colors.TEAL_100,
            focused_border_color=ft.Colors.TEAL_300,
            text_size=14,
        )
        self.result_area = ft.Column(
            controls=[],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.loading_indicator = ft.ProgressRing(width=22, height=22, stroke_width=3, visible=False)
        self.submit_button = ft.FilledButton("提交", icon=ft.Icons.SEND, on_click=lambda e: self.run_async(self.submit()))
        self.reset_button = ft.OutlinedButton("重置", icon=ft.Icons.RESTART_ALT, on_click=lambda e: self.run_async(self.reset()))
        self.cancel_button = ft.OutlinedButton("取消", icon=ft.Icons.CANCEL, disabled=True, on_click=lambda e: self.run_async(self.cancel_parse()))

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.content_area.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
        self.clear_video_preview()
        self.render_layout()
        self.safe_content_update()

    def _is_active_page(self) -> bool:
        return self.is_active_page()

    def render_layout(self) -> None:
        self.content_area.controls.clear()
        controls: list[ft.Control] = [
            self.create_title_area(),
            self.create_input_area(),
        ]
        if self.show_result_section and self.result_area is not None:
            controls.append(self.result_area)
        self.content_area.controls.extend(controls)

    def create_title_area(self) -> ft.Row:
        return ft.Row(
            controls=[
                ft.Column(
                    controls=[
                        ft.Text("TikTok/抖音无水印在线解析下载", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                    ],
                    spacing=2,
                ),
                ft.IconButton(
                    icon=ft.Icons.INFO_OUTLINE,
                    tooltip="粘贴分享口令或链接，批量解析视频和图集直链。",
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                ),
                ft.IconButton(
                    icon=ft.Icons.HISTORY,
                    tooltip="查看解析历史",
                    on_click=lambda e: self.show_parse_history_dialog(),
                    icon_color=ft.Colors.PRIMARY,
                ),
                ft.Container(expand=True),
                self.loading_indicator,
            ],
            alignment=ft.MainAxisAlignment.START,
        )

    def create_input_area(self) -> ft.Container:
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=ft.Padding.only(left=16, top=14, right=16, bottom=14),
            content=ft.Column(
                controls=[
                    self.input_field,
                    ft.Row(
                        controls=[
                            self.submit_button,
                            self.reset_button,
                            self.cancel_button,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                ],
                spacing=10,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
        )

    async def submit(self) -> None:
        text = (self.input_field.value or "").strip() if self.input_field else ""
        if not text:
            await self.app.snack_bar.show_snack_bar("请先粘贴分享口令或链接", bgcolor=ft.Colors.ERROR)
            return
        urls = self.extract_urls(text)
        if not urls:
            self.last_result = VideoParseBatchResult(input_text=text, urls=[])
            self.parse_progress_text = "未识别到有效链接"
            self.render_result(self.last_result)
            await self.app.snack_bar.show_snack_bar("未识别到有效链接", bgcolor=ft.Colors.ERROR)
            return
        await self.set_loading(True, can_cancel=True)
        self.parse_in_progress = True
        self.parse_cancel_requested = False
        task_id = None
        try:
            result = VideoParseBatchResult(input_text=text, urls=urls)
            self.last_result = result
            total = len(urls)
            task_center = getattr(self.app.services, "task_center", None)
            if task_center is not None:
                task_id = task_center.start("批量解析作品链接", "视频解析", total=total)
            for index, url in enumerate(urls, start=1):
                if self.parse_cancel_requested:
                    break
                self.parse_progress_text = f"解析进度：{index}/{total}，成功 {result.success_count}，失败 {result.failed_count}"
                self.render_result(result)
                try:
                    data = await self.app.services.video_parser.parse_url(url)
                    parsed = ParsedVideoResult.from_api_data(url, data)
                    if parsed.item_id and not parsed.source_url:
                        parsed.source_url = f"https://www.douyin.com/video/{parsed.item_id}"
                    result.successes.append(parsed)
                except Exception as exc:
                    reason = str(exc) or exc.__class__.__name__
                    assessment = classify_parser_failure(reason)
                    result.failures.append(
                        ParseFailure(
                            source_url=url,
                            reason=reason,
                            category=assessment.category,
                            retryable=assessment.retryable,
                            user_action_required=assessment.user_action_required,
                            next_step=assessment.detail,
                        )
                    )
                self.parse_progress_text = f"解析进度：{index}/{total}，成功 {result.success_count}，失败 {result.failed_count}"
                if task_center is not None and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=result.success_count,
                        failed_count=result.failed_count,
                        detail=self.parse_progress_text,
                    )
                self.render_result(result)
            cancelled = self.parse_cancel_requested
            if task_center is not None and task_id:
                if cancelled and hasattr(task_center, "cancel"):
                    task_center.cancel(task_id, "解析已取消")
                else:
                    task_center.finish(
                        task_id,
                        success=(result.failed_count == 0 and not cancelled),
                        detail=("解析已取消" if cancelled else self.parse_progress_text),
                    )
            await self.app.snack_bar.show_snack_bar(
                f"{'解析已取消' if cancelled else '解析完成'}：成功 {result.success_count}，失败 {result.failed_count}",
                bgcolor=ft.Colors.PRIMARY if result.failed_count == 0 else ft.Colors.ERROR,
                duration=4000,
                show_close_icon=True,
            )
            self._append_parse_history(result, cancelled)
        finally:
            self.parse_in_progress = False
            self.parse_cancel_requested = False
            await self.set_loading(False)

    def extract_urls(self, text: str) -> list[str]:
        parser = getattr(self.app.services, "video_parser", None)
        extractor = getattr(parser, "extract_urls", None)
        if callable(extractor):
            return list(dict.fromkeys(extractor(text)))
        return list(dict.fromkeys(VideoParserService.extract_urls(text)))

    async def cancel_parse(self) -> None:
        if not self.parse_in_progress:
            return
        self.parse_cancel_requested = True
        self.parse_progress_text = "正在取消解析..."
        self.render_result(self.last_result or VideoParseBatchResult(input_text="", urls=[]))

    async def reset(self) -> None:
        if self.input_field:
            self.input_field.value = ""
        self.last_result = None
        self.parse_progress_text = ""
        self.parse_cancel_requested = False
        self.show_result_section = False
        self.clear_video_preview()
        self.result_controls.clear()
        if self.result_area:
            self.result_area.controls.clear()
        self.render_layout()
        self.safe_content_update()

    def render_result(self, result: VideoParseBatchResult) -> None:
        if not self.result_area:
            return
        self.show_result_section = True
        self.result_area.controls.clear()
        self.result_controls.clear()
        header_controls: list[ft.Control] = [
            ft.Text(
                self.parse_progress_text or f"解析结果：成功 {result.success_count} / 失败 {result.failed_count} / 总数 {result.total_count}",
                size=13,
                color=ft.Colors.PRIMARY,
            )
        ]
        if result.successes:
            header_controls.append(ft.IconButton(icon=ft.Icons.LINK, tooltip="复制作品链接", on_click=lambda e: self.run_async(self.copy_all_work_links()), icon_color=ft.Colors.PRIMARY))
            header_controls.append(ft.IconButton(icon=ft.Icons.COPY_ALL, tooltip="复制直链", on_click=lambda e: self.run_async(self.copy_all_results()), icon_color=ft.Colors.PRIMARY))
            header_controls.append(ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="导出CSV", on_click=lambda e: self.run_async(self.export_results_csv()), icon_color=ft.Colors.PRIMARY))
            header_controls.append(ft.IconButton(icon=ft.Icons.FOLDER_OPEN, tooltip="打开导出目录", on_click=lambda e: self.run_async(self.open_export_dir()), icon_color=ft.Colors.PRIMARY))
        if result.failures:
            header_controls.append(ft.IconButton(icon=ft.Icons.REPLAY, tooltip="重试失败", on_click=lambda e: self.run_async(self.retry_failures()), icon_color=ft.Colors.PRIMARY))
        self.result_controls.append(ft.Row(controls=header_controls, wrap=True, spacing=8))
        for item in result.successes:
            self.result_controls.append(self.create_result_card(item))
        for failure in result.failures:
            failure_meta = classify_failure(failure.reason)
            self.result_controls.append(
                ft.Container(
                    border=ft.Border.all(1, ft.Colors.ERROR_CONTAINER),
                    border_radius=8,
                    padding=12,
                    content=ft.Column(
                        controls=[
                            ft.Text("解析失败", weight=ft.FontWeight.BOLD, color=ft.Colors.ERROR),
                            ft.Text(failure.source_url, selectable=True, size=12),
                            ft.Text(failure.reason, selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                            ft.Text(
                                f"{failure_meta.get('category')}：{failure_meta.get('next_step')}",
                                selectable=True,
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Row(
                                controls=[
                                    ft.IconButton(
                                        icon=ft.Icons.REPLAY,
                                        tooltip="重试",
                                        on_click=lambda e, failed=failure: self.run_async(self.retry_failure(failed)),
                                        icon_color=ft.Colors.PRIMARY,
                                    )
                                ],
                                spacing=4,
                            ),
                        ],
                        spacing=6,
                    ),
                )
            )
        self.result_area.controls = list(self.result_controls)
        if not self._is_active_page():
            return
        try:
            if self.result_area not in self.content_area.controls:
                self.render_layout()
                self.safe_content_update()
            else:
                self.result_area.update()
        except Exception as exc:
            logger.debug(f"update video parse results failed: {exc}")
            self.safe_content_update()

    def create_result_card(self, item: ParsedVideoResult) -> ft.Container:
        media_preview = self.create_media_preview(item)
        direct_url = item.primary_media_url
        work_url = item.source_url
        actions = [
            ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="打开原链接", on_click=lambda e, url=work_url: self.run_async(self.open_url(url)), icon_color=ft.Colors.PRIMARY),
        ]
        if direct_url:
            actions.extend(
                [
                    ft.IconButton(icon=ft.Icons.CONTENT_COPY, tooltip="复制直链", on_click=lambda e, url=direct_url: self.run_async(self.copy_text(url)), icon_color=ft.Colors.PRIMARY),
                    ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="下载", on_click=lambda e, parsed_item=item: self.run_async(self.download_result(parsed_item)), icon_color=ft.Colors.PRIMARY),
                ]
            )
        if item.media_type == "video" and direct_url:
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.PLAY_CIRCLE,
                    tooltip="预览视频",
                    on_click=lambda e, url=direct_url, source=item.source_url: self.run_async(self.preview_video(url, source)),
                    icon_color=ft.Colors.PRIMARY,
                )
            )
        if item.media_type == "image" and item.image_urls:
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.IMAGE_SEARCH,
                    tooltip="预览图片",
                    on_click=lambda e, parsed_item=item: self.run_async(self.preview_images(parsed_item)),
                    icon_color=ft.Colors.PRIMARY,
                )
            )
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=12,
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        media_preview,
                        ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(item.description or item.item_id or "未命名作品", weight=ft.FontWeight.BOLD, expand=True),
                                        ft.Container(
                                            bgcolor=ft.Colors.TEAL_50,
                                            border_radius=6,
                                            padding=ft.Padding.only(left=8, top=3, right=8, bottom=3),
                                            content=ft.Text(f"{item.platform or '-'} / {item.media_type}", size=11, color=ft.Colors.TEAL_700),
                                        ),
                                    ],
                                ),
                                ft.Text(f"作品 ID：{item.item_id or '-'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                                ft.Text(f"作者：{item.author_nickname or '-'}  {item.author_id or ''}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                                ft.Text(
                                    work_url or "未获取到作品链接",
                                    size=12,
                                    selectable=True,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=3,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Row(controls=actions, wrap=True, spacing=4),
                            ],
                            spacing=6,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ),
        )

    def create_media_preview(self, item: ParsedVideoResult) -> ft.Container:
        image_url = item.image_urls[0] if item.image_urls else ""
        if image_url:
            content: ft.Control = ft.Image(src=image_url, width=120, height=150, fit=ft.BoxFit.COVER)
        else:
            content = ft.Icon(ft.Icons.SMART_DISPLAY, size=42, color=ft.Colors.TEAL_400)
        return ft.Container(
            width=120,
            height=150,
            border_radius=8,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            alignment=ft.Alignment.CENTER,
            content=content,
        )

    async def set_loading(self, value: bool, can_cancel: bool = False) -> None:
        if self.loading_indicator:
            self.loading_indicator.visible = value
        if self.submit_button:
            self.submit_button.disabled = value
        if self.reset_button:
            self.reset_button.disabled = value
        if self.cancel_button:
            self.cancel_button.disabled = not (value and can_cancel)
        self.safe_content_update()

    def _parse_concurrency(self) -> int:
        settings = getattr(self.app.services, "settings_config", None)
        value = 4
        try:
            if settings:
                value = int(settings.user_config.get("video_parse_concurrency", settings.default_config.get("video_parse_concurrency", 4)))
        except (TypeError, ValueError):
            value = 4
        return max(1, min(16, value))

    async def preview_video(self, url: str, source_url: str) -> None:
        preview_source = url
        is_file_path = False
        try:
            cache = await self.app.services.parsed_media_downloader.cache_video_preview(
                url,
                source_url or url,
                title="视频预览",
                priority="foreground",
            )
            if cache.get("success") and cache.get("path"):
                preview_source = str(cache["path"])
                is_file_path = True
        except Exception as exc:
            logger.debug(f"cache parsed video preview failed: {exc}")
        try:
            await VideoPlayer(self.app).preview_video(
                preview_source,
                is_file_path=is_file_path,
                room_url=source_url,
                copy_source_url=url,
            )
        except Exception as exc:
            logger.debug(f"preview parsed video failed: {exc}")
            await self.open_url(url)

    async def preview_images(self, item: ParsedVideoResult, selected_index: int = 0) -> None:
        urls = item.image_urls or item.watermark_image_urls
        if not urls:
            await self.app.snack_bar.show_snack_bar("未获取到图片预览地址", bgcolor=ft.Colors.ERROR)
            return
        title = item.description or item.item_id or "解析图集"
        self.image_preview.show(urls, [title for _ in urls], selected_index)

    def clear_video_preview(self) -> None:
        dialog_area = getattr(self.app, "dialog_area", None)
        dialog = getattr(self.app, "current_video_dialog", None)
        try:
            if dialog_area and dialog is not None and getattr(dialog_area, "content", None) is dialog:
                dialog_area.content = None
                dialog_area.update()
            self.app.current_video_dialog = None
            self.app.current_video_control = None
        except Exception as exc:
            logger.debug(f"clear parsed video preview failed: {exc}")

    async def download_result(self, item: ParsedVideoResult) -> None:
        await self.set_loading(True)
        try:
            result = await self.app.services.parsed_media_downloader.download(item)
            await self.app.snack_bar.show_snack_bar(
                result.get("reason") or ("下载完成" if result.get("success") else "下载失败"),
                bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
            path = result.get("path")
            if path and result.get("success"):
                logger.info(f"Parsed media downloaded: {path}")
        except asyncio.CancelledError:
            await self.app.snack_bar.show_snack_bar(
                "下载已取消",
                bgcolor=ft.Colors.PRIMARY,
                duration=4000,
                show_close_icon=True,
            )
        except Exception as exc:
            logger.exception(f"download parsed result failed: {exc}")
            await self.app.snack_bar.show_snack_bar(
                f"下载失败：{exc}",
                bgcolor=ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            await self.set_loading(False)

    async def retry_failure(self, failure: ParseFailure) -> None:
        if self.input_field:
            self.input_field.value = failure.source_url
        await self.submit()

    async def retry_failures(self) -> None:
        if not self.last_result or not self.last_result.failures:
            await self.app.snack_bar.show_snack_bar("没有失败项可重试", bgcolor=ft.Colors.PRIMARY)
            return
        if self.input_field:
            self.input_field.value = "\n".join(failure.source_url for failure in self.last_result.failures)
        await self.submit()

    async def copy_all_results(self) -> None:
        if not self.last_result:
            await self.app.snack_bar.show_snack_bar("没有可复制的解析结果", bgcolor=ft.Colors.ERROR)
            return
        lines = []
        for item in self.last_result.successes:
            media_url = item.primary_media_url
            if media_url:
                lines.append(media_url)
        if not lines:
            await self.app.snack_bar.show_snack_bar("没有可复制的解析结果", bgcolor=ft.Colors.ERROR)
            return
        await self.copy_text("\n".join(lines))

    async def copy_all_work_links(self) -> None:
        if not self.last_result:
            await self.app.snack_bar.show_snack_bar("没有可复制的作品链接", bgcolor=ft.Colors.ERROR)
            return
        lines = [item.source_url for item in self.last_result.successes if item.source_url]
        if not lines:
            await self.app.snack_bar.show_snack_bar("没有可复制的作品链接", bgcolor=ft.Colors.ERROR)
            return
        await self.copy_text("\n".join(lines))

    def _history_path(self) -> Path:
        return Path(self.app.run_path, "config", "parse_history.json")

    def _load_parse_history(self) -> list[dict[str, Any]]:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                if store.parse_history_count() > 0:
                    return store.load_parse_history(limit=50)
            except Exception as exc:
                logger.debug(f"load parse history from sqlite failed: {exc}")
        path = self._history_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = data.get("records", data) if isinstance(data, dict) else data
            history = [record for record in records if isinstance(record, dict)][:50]
            if store is not None and history:
                try:
                    store.save_parse_history(history, max_records=50)
                except Exception as exc:
                    logger.debug(f"migrate parse history to sqlite failed: {exc}")
            return history
        except Exception:
            return []

    def _save_parse_history(self) -> None:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                store.save_parse_history(self.parse_history[:50], max_records=50)
            except Exception as exc:
                logger.debug(f"save parse history to sqlite failed: {exc}")
        try:
            path = self._history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"records": self.parse_history[:50]}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"save parse history failed: {exc}")

    def _append_parse_history(self, result: VideoParseBatchResult, cancelled: bool) -> None:
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已取消" if cancelled else ("完成" if result.failed_count == 0 else "有失败"),
            "total": result.total_count,
            "success": result.success_count,
            "failed": result.failed_count,
            "work_links": [item.source_url for item in result.successes if item.source_url][:100],
            "failed_links": [failure.source_url for failure in result.failures][:100],
        }
        self.parse_history.insert(0, record)
        self.parse_history = self.parse_history[:50]
        self._save_parse_history()

    def show_parse_history_dialog(self) -> None:
        records = self.parse_history[:30]
        lines: list[str] = []
        for record in records:
            lines.append(f"{record.get('time')}  {record.get('status')}  成功 {record.get('success')} / 失败 {record.get('failed')} / 总数 {record.get('total')}")
            links = record.get("work_links") or []
            if links:
                lines.extend(f"  {link}" for link in links[:5])
            failed = record.get("failed_links") or []
            if failed:
                lines.append("  失败链接：" + "；".join(str(link) for link in failed[:3]))
        if not lines:
            lines = ["暂无解析历史。"]

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("解析历史"),
            content=ft.Column(
                controls=[ft.Text("\n".join(lines), selectable=True, size=12)],
                tight=True,
                width=760,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def export_results_csv(self) -> None:
        if not self.last_result or not self.last_result.successes:
            await self.app.snack_bar.show_snack_bar("没有可导出的解析结果", bgcolor=ft.Colors.ERROR)
            return
        export_dir = self._export_dir()
        filename = f"parse_results_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        path = os.path.join(export_dir, filename)
        try:
            self._write_results_csv(path)
        except OSError as exc:
            fallback_dir = os.path.join(os.path.expanduser("~"), "Downloads", "DouyinMonitor", "parse_results")
            fallback_path = os.path.join(fallback_dir, filename)
            if os.path.abspath(fallback_path) == os.path.abspath(path):
                raise
            logger.debug(f"export csv failed at configured dir, fallback to user downloads: {exc}")
            self._write_results_csv(fallback_path)
            path = fallback_path
        await self.app.snack_bar.show_snack_bar(
            f"CSV 已导出：{path}",
            bgcolor=ft.Colors.PRIMARY,
            duration=7000,
            show_close_icon=True,
        )

    def _write_results_csv(self, path: str) -> None:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["作品ID", "作者", "作者ID", "类型", "作品链接", "媒体直链", "图片链接", "图片数量", "标题"])
            for item in (self.last_result.successes if self.last_result else []):
                image_urls = item.image_urls or item.watermark_image_urls or []
                writer.writerow(
                    [
                        item.item_id,
                        item.author_nickname,
                        item.author_id,
                        item.media_type,
                        item.source_url,
                        item.primary_media_url,
                        "\n".join(image_urls),
                        len(image_urls),
                        item.description,
                    ]
                )

    def _export_dir(self) -> str:
        settings = getattr(self.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        base = str(config.get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.app.run_path, "downloads")
        return os.path.join(base, "parse_results")

    async def open_export_dir(self) -> None:
        export_dir = self._export_dir()
        os.makedirs(export_dir, exist_ok=True)
        await self.open_path_or_url(export_dir, success=f"已打开：{export_dir}", failed_prefix="打开导出目录失败")

    async def copy_text(self, text: str) -> None:
        await self.copy_to_clipboard(text, success="已复制", failed="复制失败")

    async def open_url(self, url: str) -> None:
        await self.open_path_or_url(url, failed_prefix="打开失败")

    async def _await_coro(self, coro: Any) -> None:
        try:
            await coro
        except Exception as exc:
            logger.exception(f"Video parse UI task failed: {exc}")
            try:
                await self.app.snack_bar.show_snack_bar(str(exc), bgcolor=ft.Colors.ERROR, duration=3500, show_close_icon=True)
            except Exception:
                pass

    def run_async(self, coro: Any) -> None:
        self.page.run_task(self._await_coro, coro)
