from __future__ import annotations

import asyncio
import csv
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import flet as ft

from ...core.media.video_parser_service import ParseDownloadEvent, ParseFailure, ParseProgress, ParsedVideoResult, VideoParseBatchResult, VideoParserService, normalize_work_url
from ...core.ui_services.video_parse_workflow import VideoParseWorkflow
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
        self.input_summary_text: ft.Text | None = None
        self.input_preview_text: ft.Text | None = None
        self.result_area: ft.Column | None = None
        self.loading_indicator: ft.ProgressRing | None = None
        self.submit_button: ft.FilledButton | None = None
        self.reset_button: ft.OutlinedButton | None = None
        self.cancel_button: ft.OutlinedButton | None = None
        self.last_result: VideoParseBatchResult | None = None
        self.result_controls: list[ft.Control] = []
        self.result_render_limit = 80
        self.preview_image_limit = 36
        self.show_all_results = False
        self.result_filter = "all"
        self.result_sort = "input"
        self.result_select_mode = False
        self.selected_result_keys: set[str] = set()
        self._last_parse_render_at = 0.0
        self._parse_render_tick = 0
        self._batch_download_running = False
        self._batch_download_cancel_requested = False
        self.batch_download_total = 0
        self.batch_download_completed = 0
        self.batch_download_success = 0
        self.batch_download_skipped = 0
        self.batch_download_failed = 0
        self.parse_in_progress = False
        self.parse_cancel_requested = False
        self.parse_progress_text = ""
        self.show_result_section = False
        self.parse_workflow = VideoParseWorkflow(app)
        self.parse_history: list[dict[str, Any]] = self._load_parse_history()
        self.image_preview = ImagePreviewDialog(app, "解析图集")
        self.init()

    def init(self) -> None:
        self.input_field = ft.TextField(
            label="粘贴抖音或 TikTok 分享口令 / 作品链接",
            hint_text="支持作品链接、分享口令、短链接；多个链接可换行粘贴，也可直接粘贴整段分享文本。",
            multiline=True,
            min_lines=8,
            max_lines=12,
            border_color=ft.Colors.TEAL_100,
            focused_border_color=ft.Colors.TEAL_300,
            text_size=14,
        )
        self.input_summary_text = ft.Text(
            "粘贴后可先整理链接：自动分行、去重并移除跟踪参数。",
            size=12,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )
        self.input_preview_text = ft.Text(
            "",
            size=12,
            selectable=True,
            color=ft.Colors.ON_SURFACE_VARIANT,
            visible=False,
        )
        self.result_area = ft.Column(
            controls=[],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.loading_indicator = ft.ProgressRing(width=22, height=22, stroke_width=3, visible=False)
        self.submit_button = ft.FilledButton("开始解析", icon=ft.Icons.TRAVEL_EXPLORE, on_click=lambda e: self.run_async(self.submit()))
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
                    tooltip="查看解析资源库 / 历史",
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
                            ft.OutlinedButton("整理链接", icon=ft.Icons.FORMAT_LIST_BULLETED, on_click=lambda e: self.run_async(self.clean_input_links())),
                            ft.OutlinedButton("粘贴剪贴板", icon=ft.Icons.CONTENT_PASTE, on_click=lambda e: self.run_async(self.paste_clipboard_text())),
                            self.reset_button,
                            self.cancel_button,
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    self.input_preview_text,
                    self.input_summary_text,
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
        report = self.extract_url_report(text)
        urls = list(report.get("urls", []))
        cleaned_text = "\n".join(urls)
        if self.input_field and cleaned_text:
            self.input_field.value = cleaned_text
        self._update_input_summary(report)
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
            parse_text = cleaned_text or text
            result = VideoParseBatchResult(input_text=parse_text, urls=urls)
            self.last_result = result
            self.show_all_results = False
            self.result_filter = "all"
            self.result_sort = "input"
            self.result_select_mode = False
            self.selected_result_keys.clear()
            self._last_parse_render_at = 0.0
            self._parse_render_tick = 0
            total = len(urls)
            task_center = getattr(self.app.services, "task_center", None)
            if task_center is not None:
                task_id = task_center.start("批量解析作品链接", "视频解析", total=total)
            parser = self.app.services.video_parser
            settings = getattr(self.app.services, "settings_config", None)
            pipeline_enabled = bool(
                settings
                and getattr(settings, "user_config", {}).get("batch_parse_download_pipeline_enabled", False)
                and hasattr(parser, "parse_text_download_stream")
                and hasattr(self.app.services, "parsed_media_downloader")
            )
            if parser is not None and hasattr(parser, "clear_parse_cache"):
                try:
                    parser.clear_parse_cache(failures_only=True)
                except Exception:
                    pass
            if pipeline_enabled:
                download_concurrency = 3
                try:
                    download_concurrency = int(settings.user_config.get("batch_download_concurrency", settings.default_config.get("batch_download_concurrency", 3)))
                except (TypeError, ValueError):
                    download_concurrency = 3
                stream = parser.parse_text_download_stream(
                    parse_text,
                    self.app.services.parsed_media_downloader,
                    download_concurrency=max(1, min(32, download_concurrency)),
                )
            else:
                stream = parser.parse_text_stream(parse_text) if hasattr(parser, "parse_text_stream") else None
            if stream is None:
                stream = self._parse_text_stream_compat(parse_text)
            async for event in stream:
                if self.parse_cancel_requested:
                    if hasattr(stream, "aclose"):
                        try:
                            await stream.aclose()
                        except Exception:
                            pass
                    if hasattr(parser, "cancel_parse_tasks"):
                        parser.cancel_parse_tasks()
                    break
                if isinstance(event, ParsedVideoResult):
                    if event.item_id and not event.source_url:
                        event.source_url = f"https://www.douyin.com/video/{event.item_id}"
                    result.successes.append(event)
                elif isinstance(event, ParseFailure):
                    result.failures.append(event)
                elif isinstance(event, ParseDownloadEvent):
                    if event.status == "queued":
                        self.parse_progress_text = f"已加入下载队列：{event.item_id or event.source_url}"
                    elif event.success:
                        self.parse_progress_text = f"下载完成：{event.item_id or event.path}"
                    else:
                        self.parse_progress_text = f"下载失败：{event.item_id or event.reason}"
                    if task_center is not None and task_id:
                        task_center.progress(task_id, detail=self.parse_progress_text)
                elif isinstance(event, ParseProgress):
                    if event.message:
                        self.parse_progress_text = event.message
                    if task_center is not None and task_id:
                        task_center.progress(
                            task_id,
                            completed=event.completed,
                            success_count=event.success_count,
                            failed_count=event.failed_count,
                            detail=self.parse_progress_text,
                        )
                if self._should_render_progress(result):
                    self.render_result(result)
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

    async def _parse_text_stream_compat(self, text: str):
        urls = self.extract_urls(text)
        total = len(urls)
        success_count = 0
        failed_count = 0
        for index, url in enumerate(urls, start=1):
            try:
                data = await self.app.services.video_parser.parse_url(url)
                parsed = ParsedVideoResult.from_api_data(url, data)
                success_count += 1
                yield parsed
            except Exception as exc:
                reason = str(exc) or exc.__class__.__name__
                assessment = classify_parser_failure(reason)
                failed_count += 1
                yield ParseFailure(
                    source_url=url,
                    reason=reason,
                    category=assessment.category,
                    retryable=assessment.retryable,
                    user_action_required=assessment.user_action_required,
                    next_step=assessment.detail,
                )
            yield ParseProgress(total=total, completed=index, success_count=success_count, failed_count=failed_count, message=f"解析进度：{index}/{total}，成功 {success_count}，失败 {failed_count}")

    def extract_urls(self, text: str) -> list[str]:
        return self.parse_workflow.extract_urls(text)

    def extract_url_report(self, text: str) -> dict[str, Any]:
        return self.parse_workflow.extract_url_report(text)

    def _update_input_summary(self, report: dict[str, Any]) -> None:
        if not self.input_summary_text:
            return
        urls = list(report.get("urls", []) or [])
        raw_count = int(report.get("raw_count", len(urls)) or 0)
        duplicate_count = int(report.get("duplicate_count", 0) or 0)
        invalid_count = int(report.get("invalid_count", 0) or 0)
        self.input_summary_text.value = f"已识别 {len(urls)} 条有效链接"
        details = []
        if duplicate_count:
            details.append(f"重复 {duplicate_count} 条已移除")
        if invalid_count:
            details.append(f"无效 {invalid_count} 条")
        if raw_count and raw_count != len(urls):
            details.append(f"原始匹配 {raw_count} 条")
        if details:
            self.input_summary_text.value += "，" + "，".join(details)
        if not urls:
            self.input_summary_text.value = "未识别到有效链接。请粘贴抖音/TikTok 分享链接或分享口令。"
        self._update_input_preview(urls, duplicate_count, invalid_count)

    def _update_input_preview(self, urls: list[str], duplicate_count: int = 0, invalid_count: int = 0) -> None:
        if not self.input_preview_text:
            return
        if not urls:
            self.input_preview_text.value = ""
            self.input_preview_text.visible = False
            return
        lines = ["链接摘要："]
        for index, url in enumerate(urls[:8], start=1):
            lines.append(f"第 {index} 条  {self._short_url(url)}")
        if len(urls) > 8:
            lines.append(f"还有 {len(urls) - 8} 条，解析前已自动去重和清理跟踪参数。")
        if duplicate_count or invalid_count:
            lines.append(f"已移除重复 {duplicate_count} 条，无效 {invalid_count} 条。")
        self.input_preview_text.value = "\n".join(lines)
        self.input_preview_text.visible = True

    @staticmethod
    def _short_url(url: str, max_len: int = 96) -> str:
        text = str(url or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max_len - 16] + "..." + text[-12:]

    async def clean_input_links(self) -> None:
        text = (self.input_field.value or "").strip() if self.input_field else ""
        if not text:
            await self.app.snack_bar.show_snack_bar("请先粘贴分享口令或链接", bgcolor=ft.Colors.ERROR)
            return
        report = self.extract_url_report(text)
        urls = list(report.get("urls", []) or [])
        self._update_input_summary(report)
        if not urls:
            await self.app.snack_bar.show_snack_bar("未识别到有效链接", bgcolor=ft.Colors.ERROR)
            return
        if self.input_field:
            self.input_field.value = "\n".join(urls)
        self.safe_content_update()
        await self.app.snack_bar.show_snack_bar(
            f"已整理 {len(urls)} 条链接" + (f"，移除重复 {report.get('duplicate_count', 0)} 条" if report.get("duplicate_count") else ""),
            bgcolor=ft.Colors.PRIMARY,
        )

    async def paste_clipboard_text(self) -> None:
        getter = getattr(self.page, "get_clipboard", None)
        if not callable(getter):
            await self.app.snack_bar.show_snack_bar("当前运行环境不支持读取剪贴板", bgcolor=ft.Colors.ERROR)
            return
        try:
            value = getter()
            if hasattr(value, "__await__"):
                value = await value
        except Exception as exc:
            await self.app.snack_bar.show_snack_bar(f"读取剪贴板失败：{exc}", bgcolor=ft.Colors.ERROR)
            return
        text = str(value or "").strip()
        if not text:
            await self.app.snack_bar.show_snack_bar("剪贴板为空", bgcolor=ft.Colors.ERROR)
            return
        if self.input_field:
            existing = (self.input_field.value or "").strip()
            self.input_field.value = f"{existing}\n{text}".strip() if existing else text
        await self.clean_input_links()

    def _should_render_progress(self, result: VideoParseBatchResult, *, force: bool = False) -> bool:
        if force:
            return True
        self._parse_render_tick += 1
        now = time.monotonic()
        completed = result.success_count + result.failed_count
        if completed >= result.total_count:
            return True
        if self._parse_render_tick <= 2:
            self._last_parse_render_at = now
            return True
        if now - self._last_parse_render_at >= 0.35:
            self._last_parse_render_at = now
            return True
        return False

    async def cancel_parse(self) -> None:
        if not self.parse_in_progress:
            return
        self.parse_cancel_requested = True
        parser = getattr(self.app.services, "video_parser", None)
        if parser is not None and hasattr(parser, "cancel_parse_tasks"):
            try:
                parser.cancel_parse_tasks()
            except Exception:
                pass
        self.parse_progress_text = "正在取消解析，当前请求会立即中断或在超时前结束..."
        self.render_result(self.last_result or VideoParseBatchResult(input_text="", urls=[]))

    async def reset(self) -> None:
        if self.input_field:
            self.input_field.value = ""
        self.last_result = None
        self.parse_progress_text = ""
        self.parse_cancel_requested = False
        self.show_result_section = False
        self.show_all_results = False
        self.clear_video_preview()
        self.result_controls.clear()
        if self.result_area:
            self.result_area.controls.clear()
        if self.input_summary_text:
            self.input_summary_text.value = "粘贴后可先整理链接：自动分行、去重并移除跟踪参数。"
        if self.input_preview_text:
            self.input_preview_text.value = ""
            self.input_preview_text.visible = False
        self.render_layout()
        self.safe_content_update()

    def render_result(self, result: VideoParseBatchResult) -> None:
        if not self.result_area:
            return
        self.show_result_section = True
        self.result_area.controls.clear()
        self.result_controls.clear()
        filtered_successes, filtered_failures = self._filtered_parse_items(result)
        total_visible_items = len(filtered_successes) + len(filtered_failures)
        header_controls: list[ft.Control] = [
            ft.Text(
                self.parse_progress_text or f"解析结果：成功 {result.success_count} / 失败 {result.failed_count} / 总数 {result.total_count}",
                size=13,
                color=ft.Colors.PRIMARY,
            )
        ]
        if result.successes:
            header_controls.append(ft.OutlinedButton("复制作品链接", icon=ft.Icons.LINK, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.copy_all_work_links())))
            header_controls.append(ft.OutlinedButton("复制直链", icon=ft.Icons.COPY_ALL, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.copy_all_results())))
            header_controls.append(ft.FilledButton("下载全部", icon=ft.Icons.DOWNLOAD, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.batch_download_results("all"))))
            header_controls.append(ft.OutlinedButton("只下载视频", icon=ft.Icons.SMART_DISPLAY, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.batch_download_results("video"))))
            header_controls.append(ft.OutlinedButton("只下载图集", icon=ft.Icons.IMAGE, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.batch_download_results("image"))))
            header_controls.append(ft.OutlinedButton("选择模式" if not self.result_select_mode else "退出选择", icon=ft.Icons.CHECK_BOX if not self.result_select_mode else ft.Icons.CHECK_BOX_OUTLINE_BLANK, disabled=self._batch_download_running, on_click=lambda e: self.toggle_result_select_mode()))
            if self.result_select_mode:
                header_controls.append(ft.FilledButton("下载选中", icon=ft.Icons.DOWNLOAD_DONE, disabled=self._batch_download_running or not self.selected_result_keys, on_click=lambda e: self.run_async(self.batch_download_selected_results())))
                header_controls.append(ft.OutlinedButton("选视频", icon=ft.Icons.SMART_DISPLAY, disabled=self._batch_download_running, on_click=lambda e: self.select_results_by_type("video")))
                header_controls.append(ft.OutlinedButton("选图集", icon=ft.Icons.IMAGE, disabled=self._batch_download_running, on_click=lambda e: self.select_results_by_type("image")))
                header_controls.append(ft.OutlinedButton("选可下载", icon=ft.Icons.SELECT_ALL, disabled=self._batch_download_running, on_click=lambda e: self.select_results_by_type("downloadable")))
                header_controls.append(ft.OutlinedButton("清空选择", icon=ft.Icons.CLEAR, disabled=self._batch_download_running or not self.selected_result_keys, on_click=lambda e: self.clear_selected_results()))
            header_controls.append(ft.OutlinedButton("导出 CSV", icon=ft.Icons.FILE_DOWNLOAD, disabled=self._batch_download_running, on_click=lambda e: self.run_async(self.export_results_csv())))
            header_controls.append(ft.OutlinedButton("打开导出目录", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: self.run_async(self.open_export_dir())))
        if result.failures:
            header_controls.append(ft.OutlinedButton("重试失败", icon=ft.Icons.REPLAY, disabled=self.parse_in_progress or self._batch_download_running, on_click=lambda e: self.run_async(self.retry_failures())))
            header_controls.append(ft.OutlinedButton("复制失败链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.run_async(self.copy_failed_links())))
        if self._batch_download_running:
            header_controls.append(ft.OutlinedButton("停止下载", icon=ft.Icons.STOP_CIRCLE, on_click=lambda e: self.run_async(self.cancel_batch_download())))
        self.result_controls.append(ft.Row(controls=header_controls, wrap=True, spacing=8))
        self.result_controls.append(
            ft.Row(
                controls=[
                    self._stat_chip("总数", result.total_count, ft.Colors.PRIMARY),
                    self._stat_chip("成功", result.success_count, ft.Colors.GREEN),
                    self._stat_chip("失败", result.failed_count, ft.Colors.ERROR),
                    self._stat_chip("待解析", max(result.total_count - result.success_count - result.failed_count, 0), ft.Colors.ON_SURFACE_VARIANT),
                    ft.Container(expand=True),
                    ft.Text("显示：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    *self._result_filter_buttons(),
                    ft.Text("排序：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    *self._result_sort_buttons(),
                ],
                wrap=True,
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            )
        )
        if result.successes:
            self.result_controls.append(self._download_rules_panel())
        if result.failures:
            self.result_controls.append(self._failure_summary_panel(result.failures))
        if self.result_select_mode:
            self.result_controls.append(self._selection_summary_panel())
        if self._batch_download_running or self.batch_download_total:
            self.result_controls.append(self._batch_download_progress_panel())
        display_successes = filtered_successes if self.show_all_results else filtered_successes[: self.result_render_limit]
        remaining_limit = max(0, self.result_render_limit - len(display_successes))
        display_failures = filtered_failures if self.show_all_results else filtered_failures[:remaining_limit]
        hidden_count = max(0, total_visible_items - len(display_successes) - len(display_failures))
        if hidden_count:
            self.result_controls.append(
                ft.Container(
                    bgcolor=ft.Colors.SURFACE_VARIANT,
                    border_radius=8,
                    padding=10,
                    content=ft.Row(
                        controls=[
                            ft.Text(f"当前为避免卡顿，仅渲染前 {len(display_successes) + len(display_failures)} 条；还有 {hidden_count} 条未显示。", size=12, expand=True),
                            ft.OutlinedButton("显示全部", icon=ft.Icons.UNFOLD_MORE, on_click=lambda e: self.show_all_parse_results()),
                        ],
                        wrap=True,
                    ),
                )
            )
        if total_visible_items == 0 and (result.successes or result.failures):
            self.result_controls.append(
                ft.Container(
                    padding=16,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    content=ft.Text("当前筛选条件下没有结果。", color=ft.Colors.ON_SURFACE_VARIANT),
                )
            )
        for display_index, item in enumerate(display_successes, start=1):
            self.result_controls.append(self.create_result_card(item, self._source_order_label(result, item.source_url), display_index=display_index))
        for failure in display_failures:
            self.result_controls.append(self.create_failure_card(result, failure))
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

    def _filtered_parse_items(self, result: VideoParseBatchResult) -> tuple[list[ParsedVideoResult], list[ParseFailure]]:
        successes = list(result.successes or [])
        failures = list(result.failures or [])
        if self.result_sort == "input":
            order = self._source_order_map(result)
            successes.sort(key=lambda item: order.get(self._source_key(item.source_url), 10**9))
            failures.sort(key=lambda item: order.get(self._source_key(item.source_url), 10**9))
        if self.result_filter == "video":
            successes = [item for item in successes if item.media_type == "video"]
            failures = []
        elif self.result_filter == "image":
            successes = [item for item in successes if item.media_type == "image" or bool(item.image_urls or item.watermark_image_urls)]
            failures = []
        elif self.result_filter == "failed":
            successes = []
        elif self.result_filter == "downloadable":
            successes = [item for item in successes if item.primary_media_url or item.image_urls or item.watermark_image_urls]
            failures = []
        return successes, failures

    def _result_filter_buttons(self) -> list[ft.Control]:
        options = [
            ("all", "全部"),
            ("downloadable", "可下载"),
            ("video", "视频"),
            ("image", "图集"),
            ("failed", "失败"),
        ]
        return [
            ft.TextButton(
                label,
                icon=ft.Icons.CHECK if self.result_filter == key else None,
                disabled=self.result_filter == key,
                on_click=lambda e, mode=key: self.set_result_filter(mode),
            )
            for key, label in options
        ]

    def _result_sort_buttons(self) -> list[ft.Control]:
        options = [("input", "输入顺序"), ("finish", "完成顺序")]
        return [
            ft.TextButton(
                label,
                icon=ft.Icons.CHECK if self.result_sort == key else None,
                disabled=self.result_sort == key,
                on_click=lambda e, mode=key: self.set_result_sort(mode),
            )
            for key, label in options
        ]

    def set_result_filter(self, mode: str) -> None:
        self.result_filter = str(mode or "all")
        self.show_all_results = False
        if self.last_result:
            self.render_result(self.last_result)

    def set_result_sort(self, mode: str) -> None:
        self.result_sort = str(mode or "input")
        if self.last_result:
            self.render_result(self.last_result)

    def _download_rules_panel(self) -> ft.Container:
        settings = getattr(self.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        base = str(config.get("douyin_content_download_path") or "").strip() or os.path.join(self.app.run_path, "downloads")
        image_format = str(config.get("gallery_image_save_format") or "original")
        image_label = "保留原格式" if image_format == "original" else "统一转 PNG"
        return ft.Container(
            padding=10,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SAVE_ALT, size=18, color=ft.Colors.PRIMARY),
                    ft.Text(f"保存规则：保存到 {base}；图集格式：{image_label}；下载时自动跳过已存在文件。", size=12, color=ft.Colors.ON_SURFACE_VARIANT, expand=True, selectable=True),
                    ft.TextButton("打开保存目录", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: self.run_async(self.open_download_location(base))),
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _failure_summary_panel(self, failures: list[ParseFailure]) -> ft.Container:
        buckets: dict[str, int] = {}
        retryable = 0
        for failure in failures:
            failure_meta = classify_failure(failure.reason)
            category = failure.category or failure_meta.get("category") or "parser_error"
            buckets[category] = buckets.get(category, 0) + 1
            if failure.retryable:
                retryable += 1
        parts = [f"{self._failure_category_label(category)} {count}" for category, count in sorted(buckets.items(), key=lambda item: item[1], reverse=True)]
        return ft.Container(
            padding=10,
            bgcolor=ft.Colors.ERROR_CONTAINER,
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.ERROR_OUTLINE, size=18, color=ft.Colors.ERROR),
                    ft.Text(f"失败集中处理：失败 {len(failures)} 条，可重试 {retryable} 条；" + "，".join(parts), size=12, color=ft.Colors.ERROR, expand=True),
                    ft.TextButton("只看失败", icon=ft.Icons.FILTER_ALT, on_click=lambda e: self.set_result_filter("failed")),
                    ft.TextButton("重试失败", icon=ft.Icons.REPLAY, disabled=self.parse_in_progress or self._batch_download_running, on_click=lambda e: self.run_async(self.retry_failures())),
                    ft.TextButton("复制失败链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.run_async(self.copy_failed_links())),
                ],
                spacing=8,
                wrap=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    def _selection_summary_panel(self) -> ft.Container:
        selected = len(self.selected_result_keys)
        total = len(self.last_result.successes) if self.last_result else 0
        return ft.Container(
            padding=10,
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=8,
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHECK_BOX, size=18, color=ft.Colors.PRIMARY),
                    ft.Text(f"选择模式：已选 {selected}/{total} 个结果。可先筛选视频/图集，再下载选中。", size=12, color=ft.Colors.PRIMARY, expand=True),
                    ft.TextButton("下载选中", icon=ft.Icons.DOWNLOAD_DONE, disabled=selected <= 0, on_click=lambda e: self.run_async(self.batch_download_selected_results())),
                    ft.TextButton("清空", icon=ft.Icons.CLEAR, disabled=selected <= 0, on_click=lambda e: self.clear_selected_results()),
                ],
                wrap=True,
                spacing=8,
            ),
        )

    def toggle_result_select_mode(self) -> None:
        self.result_select_mode = not self.result_select_mode
        if not self.result_select_mode:
            self.selected_result_keys.clear()
        if self.last_result:
            self.render_result(self.last_result)

    def toggle_result_selection(self, key: str, selected: bool) -> None:
        if selected:
            self.selected_result_keys.add(key)
        else:
            self.selected_result_keys.discard(key)
        # Keep this update lightweight: only refresh the header/panel, not the whole page.
        if self.last_result:
            self.render_result(self.last_result)

    def select_results_by_type(self, mode: str) -> None:
        if not self.last_result:
            return
        items = self._filter_download_items(self.last_result.successes, mode)
        self.selected_result_keys = {self._result_key(item) for item in items}
        self.result_select_mode = True
        self.render_result(self.last_result)

    def clear_selected_results(self) -> None:
        self.selected_result_keys.clear()
        if self.last_result:
            self.render_result(self.last_result)

    def _selected_download_items(self) -> list[ParsedVideoResult]:
        if not self.last_result or not self.selected_result_keys:
            return []
        return [item for item in self.last_result.successes if self._result_key(item) in self.selected_result_keys and (item.primary_media_url or item.image_urls or item.watermark_image_urls)]

    @staticmethod
    def _result_key(item: ParsedVideoResult) -> str:
        return normalize_work_url(item.source_url or "") or item.item_id or item.primary_media_url or str(id(item))

    def _batch_download_progress_panel(self) -> ft.Container:
        total = max(0, int(self.batch_download_total or 0))
        completed = max(0, int(self.batch_download_completed or 0))
        value = (completed / total) if total else 0
        status = "正在下载" if self._batch_download_running else "最近下载结果"
        return ft.Container(
            padding=10,
            border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
            border_radius=8,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(f"{status}：{completed}/{total}，成功 {self.batch_download_success}，已存在 {self.batch_download_skipped}，失败 {self.batch_download_failed}", size=12, color=ft.Colors.PRIMARY, expand=True),
                            ft.OutlinedButton("停止下载", icon=ft.Icons.STOP_CIRCLE, visible=self._batch_download_running, on_click=lambda e: self.run_async(self.cancel_batch_download())),
                        ],
                        wrap=True,
                    ),
                    ft.ProgressBar(value=value),
                ],
                spacing=6,
            ),
        )

    def _stat_chip(self, label: str, value: int, color: Any) -> ft.Container:
        return ft.Container(
            content=ft.Text(f"{label}：{value}", size=12, color=ft.Colors.WHITE),
            bgcolor=color,
            border_radius=12,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        )

    def _source_order_label(self, result: VideoParseBatchResult, source_url: str) -> str:
        order = self._source_order_map(result).get(self._source_key(source_url), 0)
        return f"第 {order} 条" if order > 0 else ""

    def _source_order_map(self, result: VideoParseBatchResult) -> dict[str, int]:
        mapping: dict[str, int] = {}
        for index, url in enumerate(result.urls or [], start=1):
            for key in {self._source_key(url), self._source_key(normalize_work_url(url))}:
                if key and key not in mapping:
                    mapping[key] = index
        return mapping

    @staticmethod
    def _source_key(url: str) -> str:
        return normalize_work_url(str(url or "").strip()) or str(url or "").strip()

    def create_failure_card(self, result: VideoParseBatchResult, failure: ParseFailure) -> ft.Container:
        failure_meta = classify_failure(failure.reason)
        category = failure.category or failure_meta.get("category") or "parser_error"
        next_step = failure.next_step or failure_meta.get("next_step") or "可稍后重试；若持续失败请导出诊断报告。"
        order_label = self._source_order_label(result, failure.source_url)
        category_label = self._failure_category_label(category)
        retry_text = "可重试" if failure.retryable else "不建议立即重试"
        action_text = "需要处理" if failure.user_action_required else "无需手动处理"
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.ERROR_CONTAINER),
            border_radius=8,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(f"{order_label + ' · ' if order_label else ''}解析失败", weight=ft.FontWeight.BOLD, color=ft.Colors.ERROR, expand=True),
                            ft.Container(
                                bgcolor=ft.Colors.ERROR_CONTAINER,
                                border_radius=10,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                                content=ft.Text(category_label, size=11, color=ft.Colors.ERROR),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text(failure.source_url, selectable=True, size=12),
                    ft.Text(f"原因：{failure.reason}", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"建议：{next_step}", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Text(f"重试判断：{retry_text} / {action_text}", selectable=True, size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Row(
                        controls=[
                            ft.OutlinedButton("重试此条", icon=ft.Icons.REPLAY, on_click=lambda e, failed=failure: self.run_async(self.retry_failure(failed))),
                            ft.OutlinedButton("复制失败链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=failure.source_url: self.run_async(self.copy_text(url))),
                        ],
                        spacing=4,
                        wrap=True,
                    ),
                ],
                spacing=6,
            ),
        )

    @staticmethod
    def _failure_category_label(category: str) -> str:
        return {
            "risk_control": "平台风控/限流",
            "auth_required": "Cookie/登录异常",
            "not_found_or_private": "作品不可访问",
            "network": "网络/代理异常",
            "parser_error": "解析器错误",
            "unknown": "未知错误",
        }.get(str(category or ""), str(category or "解析失败"))

    @staticmethod
    def _media_type_label(item: ParsedVideoResult) -> str:
        platform = item.platform or "-"
        if item.media_type == "image" or item.image_urls:
            return f"{platform} / 图集"
        if item.media_type == "video":
            return f"{platform} / 视频"
        return f"{platform} / {item.media_type or '-'}"

    def show_all_parse_results(self) -> None:
        self.show_all_results = True
        if self.last_result:
            self.render_result(self.last_result)

    def create_result_card(self, item: ParsedVideoResult, order_label: str = "", display_index: int = 0) -> ft.Container:
        item_key = self._result_key(item)
        media_preview = self.create_media_preview(item, load_remote=display_index <= self.preview_image_limit)
        direct_url = item.primary_media_url
        work_url = item.source_url
        actions = [
            ft.OutlinedButton("打开原作品", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e, url=work_url: self.run_async(self.open_url(url))),
        ]
        if direct_url:
            actions.extend(
                [
                    ft.OutlinedButton("复制直链", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=direct_url: self.run_async(self.copy_text(url))),
                    ft.FilledButton("下载", icon=ft.Icons.DOWNLOAD, on_click=lambda e, parsed_item=item: self.run_async(self.download_result(parsed_item))),
                ]
            )
        if item.media_type == "video" and direct_url:
            actions.append(
                ft.OutlinedButton(
                    "预览视频",
                    icon=ft.Icons.PLAY_CIRCLE,
                    on_click=lambda e, url=direct_url, source=item.source_url: self.run_async(self.preview_video(url, source)),
                )
            )
        if item.media_type == "image" and item.image_urls:
            actions.append(
                ft.OutlinedButton(
                    "预览图集",
                    icon=ft.Icons.IMAGE_SEARCH,
                    on_click=lambda e, parsed_item=item: self.run_async(self.preview_images(parsed_item)),
                )
            )
        details = [
            ft.Text(f"作品 ID：{item.item_id or '-'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"作者：{item.author_nickname or '-'}  {item.author_id or ''}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if item.media_type == "image" or item.image_urls:
            image_count = len(item.image_urls or item.watermark_image_urls or [])
            details.append(ft.Text(f"图集图片：{image_count} 张", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        elif item.media_type == "video":
            quality_hint = "无水印" if item.no_watermark_url else ("有水印" if item.watermark_url else "未获取到直链")
            details.append(ft.Text(f"视频状态：{quality_hint}", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=12,
            content=ft.Container(
                content=ft.Row(
                    controls=[
                        *([ft.Checkbox(value=item_key in self.selected_result_keys, tooltip="选择此结果", on_change=lambda e, key=item_key: self.toggle_result_selection(key, bool(e.control.value)))] if self.result_select_mode else []),
                        media_preview,
                        ft.Column(
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Text(f"{order_label + ' · ' if order_label else ''}{item.description or item.item_id or '未命名作品'}", weight=ft.FontWeight.BOLD, expand=True),
                                        ft.Container(
                                            bgcolor=ft.Colors.TEAL_50,
                                            border_radius=6,
                                            padding=ft.Padding.only(left=8, top=3, right=8, bottom=3),
                                            content=ft.Text(self._media_type_label(item), size=11, color=ft.Colors.TEAL_700),
                                        ),
                                    ],
                                ),
                                *details,
                                ft.Text(
                                    work_url or "未获取到作品链接",
                                    size=12,
                                    selectable=True,
                                    color=ft.Colors.ON_SURFACE_VARIANT,
                                    max_lines=3,
                                    overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                                ft.Row(controls=actions, wrap=True, spacing=8),
                            ],
                            spacing=6,
                        ),
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
            ),
        )

    def create_media_preview(self, item: ParsedVideoResult, *, load_remote: bool = True) -> ft.Container:
        image_url = item.image_urls[0] if item.image_urls else ""
        if image_url and load_remote:
            content: ft.Control = ft.Image(src=image_url, width=120, height=150, fit=ft.BoxFit.COVER)
        elif image_url:
            content = ft.Column(
                controls=[
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, size=36, color=ft.Colors.TEAL_400),
                    ft.Text("缩略图延迟加载", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            )
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
            path = result.get("path")
            await self.app.snack_bar.show_snack_bar(
                result.get("reason") or ("下载完成" if result.get("success") else "下载失败"),
                bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )
            if path and result.get("success"):
                logger.info(f"Parsed media downloaded: {path}")
                self.show_download_complete_dialog(str(path), str(result.get("reason") or "下载完成"), result.get("files") or [])
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

    def show_download_complete_dialog(self, path: str, reason: str = "下载完成", files: list[str] | None = None) -> None:
        target_path = str(path or "").strip()
        file_count_text = f"\n文件数：{len(files)}" if files else ""
        dialog_ref: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def close_dialog(_=None):
            dialog = dialog_ref.get("dialog")
            if dialog is not None:
                dialog.open = False
            self.app.dialog_area.update()

        async def copy_path(_=None):
            close_dialog()
            await self.copy_text(target_path)

        async def open_folder(_=None):
            close_dialog()
            await self.open_download_location(target_path)

        dialog = ft.AlertDialog(
            modal=False,
            title=ft.Text("下载完成"),
            content=ft.Column(
                controls=[
                    ft.Text(reason, size=13),
                    ft.Text(f"保存位置：{target_path}{file_count_text}", selectable=True, size=12),
                ],
                tight=True,
                width=680,
            ),
            actions=[
                ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog),
                ft.TextButton("复制路径", icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.run_async(copy_path())),
                ft.FilledButton("打开文件夹", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: self.run_async(open_folder())),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def open_download_location(self, path: str) -> None:
        target = self._download_location(path)
        await self.open_path_or_url(target, success=f"已打开：{target}", failed_prefix="打开下载位置失败")

    @staticmethod
    def _download_location(path: str) -> str:
        text = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if os.path.isfile(text):
            return os.path.dirname(text)
        return text

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

    async def copy_failed_links(self) -> None:
        if not self.last_result or not self.last_result.failures:
            await self.app.snack_bar.show_snack_bar("没有失败链接可复制", bgcolor=ft.Colors.ERROR)
            return
        await self.copy_text("\n".join(failure.source_url for failure in self.last_result.failures if failure.source_url))

    async def batch_download_selected_results(self) -> None:
        if not self.selected_result_keys:
            await self.app.snack_bar.show_snack_bar("请先选择要下载的结果", bgcolor=ft.Colors.ERROR)
            return
        items = self._selected_download_items()
        if not items:
            await self.app.snack_bar.show_snack_bar("选中的结果里没有可下载媒体", bgcolor=ft.Colors.ERROR)
            return
        await self._batch_download_items(items, title_prefix="下载选中")

    async def batch_download_results(self, media_filter: str = "all") -> None:
        if self._batch_download_running:
            await self.app.snack_bar.show_snack_bar("批量下载正在执行，请等待完成", bgcolor=ft.Colors.ERROR)
            return
        if not self.last_result or not self.last_result.successes:
            await self.app.snack_bar.show_snack_bar("没有可下载的解析结果", bgcolor=ft.Colors.ERROR)
            return
        items = self._filter_download_items(self.last_result.successes, media_filter)
        if not items:
            label = "视频" if media_filter == "video" else "图集" if media_filter == "image" else "结果"
            await self.app.snack_bar.show_snack_bar(f"没有可下载的{label}", bgcolor=ft.Colors.ERROR)
            return
        self._batch_download_running = True
        self._batch_download_cancel_requested = False
        await self.set_loading(True)
        total = len(items)
        self.batch_download_total = total
        self.batch_download_completed = 0
        self.batch_download_success = 0
        self.batch_download_failed = 0
        self.batch_download_skipped = 0
        success_count = 0
        failed_count = 0
        skipped_count = 0
        paths: list[str] = []
        files: list[str] = []
        errors: list[str] = []
        last_render = 0.0
        try:
            for index, item in enumerate(items, start=1):
                if self._batch_download_cancel_requested:
                    self.parse_progress_text = f"批量下载已停止：已处理 {self.batch_download_completed}/{total}"
                    break
                title = item.description or item.item_id or item.source_url
                self.parse_progress_text = f"批量下载：{index}/{total} · {title}"
                now = time.monotonic()
                if now - last_render >= 0.5 or index == 1:
                    last_render = now
                    if self.last_result:
                        self.render_result(self.last_result)
                try:
                    result = await self.app.services.parsed_media_downloader.download(item)
                except Exception as exc:
                    failed_count += 1
                    self.batch_download_failed = failed_count
                    errors.append(f"{title}: {exc}")
                    self.batch_download_completed = success_count + skipped_count + failed_count
                    continue
                if result.get("success"):
                    reason = str(result.get("reason") or "")
                    if "已存在" in reason:
                        skipped_count += 1
                    else:
                        success_count += 1
                    self.batch_download_success = success_count
                    self.batch_download_skipped = skipped_count
                    path = str(result.get("path") or "")
                    if path:
                        paths.append(path)
                    files.extend(str(path) for path in (result.get("files") or []) if path)
                else:
                    failed_count += 1
                    self.batch_download_failed = failed_count
                    errors.append(f"{title}: {result.get('reason') or '下载失败'}")
                self.batch_download_completed = success_count + skipped_count + failed_count
            stopped_prefix = "批量下载已停止" if self._batch_download_cancel_requested else "批量下载完成"
            self.parse_progress_text = f"{stopped_prefix}：成功 {success_count}，已存在 {skipped_count}，失败 {failed_count}"
            if self.last_result:
                self.render_result(self.last_result)
            if paths:
                location = self._common_download_location(paths)
                summary = self.parse_progress_text
                if errors:
                    summary += "\n" + "\n".join(errors[:5])
                self.show_download_complete_dialog(location, summary, files)
            await self.app.snack_bar.show_snack_bar(
                self.parse_progress_text,
                bgcolor=ft.Colors.PRIMARY if failed_count == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            self._batch_download_running = False
            self._batch_download_cancel_requested = False
            await self.set_loading(False)

    async def _batch_download_items(self, items: list[ParsedVideoResult], *, title_prefix: str = "批量下载") -> None:
        self._batch_download_running = True
        self._batch_download_cancel_requested = False
        await self.set_loading(True)
        total = len(items)
        self.batch_download_total = total
        self.batch_download_completed = 0
        self.batch_download_success = 0
        self.batch_download_failed = 0
        self.batch_download_skipped = 0
        success_count = 0
        failed_count = 0
        skipped_count = 0
        paths: list[str] = []
        files: list[str] = []
        errors: list[str] = []
        last_render = 0.0
        try:
            for index, item in enumerate(items, start=1):
                if self._batch_download_cancel_requested:
                    self.parse_progress_text = f"{title_prefix}已停止：已处理 {self.batch_download_completed}/{total}"
                    break
                title = item.description or item.item_id or item.source_url
                self.parse_progress_text = f"{title_prefix}：{index}/{total} · {title}"
                now = time.monotonic()
                if now - last_render >= 0.5 or index == 1:
                    last_render = now
                    if self.last_result:
                        self.render_result(self.last_result)
                try:
                    result = await self.app.services.parsed_media_downloader.download(item)
                except Exception as exc:
                    failed_count += 1
                    self.batch_download_failed = failed_count
                    errors.append(f"{title}: {exc}")
                    self.batch_download_completed = success_count + skipped_count + failed_count
                    continue
                if result.get("success"):
                    reason = str(result.get("reason") or "")
                    if "已存在" in reason:
                        skipped_count += 1
                    else:
                        success_count += 1
                    self.batch_download_success = success_count
                    self.batch_download_skipped = skipped_count
                    path = str(result.get("path") or "")
                    if path:
                        paths.append(path)
                    files.extend(str(path) for path in (result.get("files") or []) if path)
                else:
                    failed_count += 1
                    self.batch_download_failed = failed_count
                    errors.append(f"{title}: {result.get('reason') or '下载失败'}")
                self.batch_download_completed = success_count + skipped_count + failed_count
            stopped_prefix = f"{title_prefix}已停止" if self._batch_download_cancel_requested else f"{title_prefix}完成"
            self.parse_progress_text = f"{stopped_prefix}：成功 {success_count}，已存在 {skipped_count}，失败 {failed_count}"
            if self.last_result:
                self.render_result(self.last_result)
            if paths:
                location = self._common_download_location(paths)
                summary = self.parse_progress_text
                if errors:
                    summary += "\n" + "\n".join(errors[:5])
                self.show_download_complete_dialog(location, summary, files)
            await self.app.snack_bar.show_snack_bar(
                self.parse_progress_text,
                bgcolor=ft.Colors.PRIMARY if failed_count == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        finally:
            self._batch_download_running = False
            self._batch_download_cancel_requested = False
            await self.set_loading(False)

    async def cancel_batch_download(self) -> None:
        if not self._batch_download_running:
            await self.app.snack_bar.show_snack_bar("当前没有正在执行的批量下载", bgcolor=ft.Colors.ERROR)
            return
        self._batch_download_cancel_requested = True
        self.parse_progress_text = "正在停止批量下载，当前文件处理完成后结束..."
        if self.last_result:
            self.render_result(self.last_result)
        await self.app.snack_bar.show_snack_bar("已请求停止批量下载", bgcolor=ft.Colors.PRIMARY)

    @staticmethod
    def _filter_download_items(items: list[ParsedVideoResult], media_filter: str) -> list[ParsedVideoResult]:
        if media_filter == "video":
            return [item for item in items if item.media_type == "video" and (item.no_watermark_url or item.watermark_url)]
        if media_filter == "image":
            return [item for item in items if item.media_type == "image" or bool(item.image_urls or item.watermark_image_urls)]
        return [item for item in items if item.primary_media_url or item.image_urls or item.watermark_image_urls]

    def _common_download_location(self, paths: list[str]) -> str:
        folders = [self._download_location(path) for path in paths if path]
        if not folders:
            return self._export_dir()
        try:
            return os.path.commonpath(folders)
        except ValueError:
            return folders[0]

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
        return self.parse_workflow.history_path()

    def _load_parse_history(self) -> list[dict[str, Any]]:
        return self.parse_workflow.load_history()

    def _save_parse_history(self) -> None:
        self.parse_workflow.save_history(self.parse_history)

    def _append_parse_history(self, result: VideoParseBatchResult, cancelled: bool) -> None:
        self.parse_history = self.parse_workflow.append_history(self.parse_history, result, cancelled)

    def show_parse_history_dialog(self) -> None:
        records = self.parse_history[:80]
        summary = self.parse_workflow.resource_summary(records)
        filtered = self.parse_workflow.filter_history(records)[:40]
        lines: list[str] = [
            "解析资源库",
            f"批次 {summary.get('batches', 0)} 个，资源 {summary.get('resources', 0)} 条，成功 {summary.get('success', 0)}，失败 {summary.get('failed', 0)}",
            "",
        ]
        for record in filtered:
            lines.append(f"{record.get('time')}  {record.get('status')}  成功 {record.get('success')} / 失败 {record.get('failed')} / 总数 {record.get('total')}")
            resources = record.get("resources") if isinstance(record.get("resources"), list) else []
            for item in resources[:6]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title") or "无标题").strip().replace("\n", " ")[:60]
                author = str(item.get("author") or "未知作者")
                media_type = str(item.get("media_type") or "资源")
                extra = f"，图片 {item.get('image_count')} 张" if int(item.get("image_count") or 0) else ""
                lines.append(f"  [{media_type}] {title} · {author}{extra}")
                if item.get("source_url"):
                    lines.append(f"    {item.get('source_url')}")
            failed = record.get("failure_details") if isinstance(record.get("failure_details"), list) else []
            if failed:
                lines.append("  失败项：")
                for failure in failed[:4]:
                    if not isinstance(failure, dict):
                        continue
                    lines.append(f"    {failure.get('category') or 'unknown'} · {failure.get('reason') or '-'}")
                    if failure.get("source_url"):
                        lines.append(f"    {failure.get('source_url')}")
            lines.append("")
        if len(records) > len(filtered):
            lines.append(f"仅展示最近 {len(filtered)} 个批次；历史总批次 {len(records)}。")
        if not records:
            lines = ["暂无解析资源。解析成功或失败后会自动进入资源库。"]

        def close_dialog(_=None):
            dialog.open = False
            self.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("解析资源库"),
            content=ft.Column(
                controls=[ft.Text("\n".join(lines), selectable=True, size=12)],
                tight=True,
                width=820,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[
                ft.TextButton("复制失败链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e: self.run_async(self.copy_history_failed_links())),
                ft.TextButton("清空资源库", icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e: self.run_async(self.confirm_clear_parse_history())),
                ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog),
            ],
        )
        dialog.open = True
        self.app.dialog_area.content = dialog
        self.app.dialog_area.update()

    async def copy_history_failed_links(self) -> None:
        links = self.parse_workflow.collect_failed_links(self.parse_history)
        if not links:
            await self.app.snack_bar.show_snack_bar("资源库里没有失败链接", bgcolor=ft.Colors.ERROR)
            return
        await self.copy_text("\n".join(links))

    async def confirm_clear_parse_history(self) -> None:
        if not self.parse_history:
            await self.app.snack_bar.show_snack_bar("解析资源库已经为空", bgcolor=ft.Colors.PRIMARY)
            return
        self.show_confirm_dialog(
            "清空解析资源库",
            f"将清空 {len(self.parse_history)} 条解析历史记录，不会删除已下载文件。是否继续？",
            self.clear_parse_history,
        )

    async def clear_parse_history(self) -> None:
        self.parse_history = self.parse_workflow.clear_history()
        await self.app.snack_bar.show_snack_bar("解析资源库已清空，已下载文件不受影响", bgcolor=ft.Colors.PRIMARY)
        try:
            if getattr(self.app, "dialog_area", None) is not None:
                self.app.dialog_area.content = None
                self.app.dialog_area.update()
        except Exception:
            pass

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
