from __future__ import annotations

import asyncio
import csv
import json
import os
from datetime import datetime
from typing import Any

import flet as ft

from ...core.runtime.task_center import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING,
    classify_failure,
)
from ..base_page import PageBase


class TaskCenterPage(PageBase):
    def __init__(self, app):
        super().__init__(app)
        self.page_name = "task_center"
        self.records_area: ft.Column | None = None
        self.status_filter = "all"
        self.category_filter = "all"
        self.search_query = ""
        self.search_field: ft.TextField | None = None

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.search_field = ft.TextField(
            label="搜索任务",
            hint_text="任务标题、说明、类型、状态、作品ID",
            value=self.search_query,
            prefix_icon=ft.Icons.SEARCH,
            dense=True,
            width=360,
            on_change=lambda e: self.run_async(self.set_search_query(str(e.control.value or ""))),
            on_submit=lambda e: self.run_async(self.refresh()),
        )
        self.records_area = ft.Column(
            controls=[],
            spacing=8,
            expand=False,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self._title_area(),
                self._filter_area(),
                self.records_area,
            ]
        )
        await self.refresh()
        self.content_area.update()

    def _title_area(self) -> ft.Column:
        queue = getattr(self.app.services, "media_task_queue", None)
        paused = bool(queue.is_paused()) if queue is not None and hasattr(queue, "is_paused") else False
        records = self._all_records(500)
        counts = self._record_counts(records)
        queue_active = self._queue_has_active_downloads()
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("任务中心", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            tooltip="查看解析、下载和内容监控任务的执行状态；任务历史会保存到本地。",
                            icon_color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        ft.Container(expand=True),
                        self._stat_chip("全部", counts["total"], ft.Colors.PRIMARY),
                        self._stat_chip("运行", counts["running"], ft.Colors.PRIMARY),
                        self._stat_chip("失败", counts["failed"], ft.Colors.ERROR),
                        self._stat_chip("已取消", counts["cancelled"], ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        self._toolbar_icon_button(ft.Icons.REPLAY, "重试所有失败且支持重试的任务", self.retry_all_failed_tasks, disabled=counts["retryable"] == 0),
                        self._toolbar_icon_button(ft.Icons.PLAY_ARROW if paused else ft.Icons.PAUSE_CIRCLE, "继续下载队列" if paused else "暂停下载队列", self.toggle_download_queue),
                        self._toolbar_icon_button(ft.Icons.STOP_CIRCLE, "取消当前运行或等待中的下载任务", self.cancel_download_queue, disabled=not queue_active, danger=True),
                        self._toolbar_icon_button(ft.Icons.DOWNLOAD, "导出全部任务记录 CSV", self.export_tasks_csv, disabled=counts["total"] == 0),
                        self._toolbar_icon_button(ft.Icons.FOLDER_OPEN, "打开任务导出目录", self.open_task_export_dir),
                        self._toolbar_icon_button(ft.Icons.CLEANING_SERVICES, "清除已完成任务记录", self.clear_completed, disabled=counts["completed"] == 0),
                        self._toolbar_icon_button(ft.Icons.DELETE_SWEEP, "清除失败任务记录", self.clear_failed, disabled=counts["failed"] == 0),
                        self._toolbar_icon_button(ft.Icons.BLOCK, "清除已取消任务记录", self.clear_cancelled, disabled=counts["cancelled"] == 0),
                        self._toolbar_icon_button(ft.Icons.DELETE_FOREVER, "清空全部任务记录", self.confirm_clear_all_tasks, disabled=counts["total"] == 0, danger=True),
                        self._toolbar_icon_button(ft.Icons.REFRESH, "刷新任务列表", self.reload),
                    ],
                    spacing=6,
                    wrap=True,
                ),
                self._queue_summary_card(),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _queue_summary_card(self) -> ft.Control:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return ft.Container(
                padding=10,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
                content=ft.Text("下载队列未初始化", color=ft.Colors.ON_SURFACE_VARIANT),
            )
        try:
            snapshot = queue.snapshot()
        except Exception as exc:
            return ft.Container(
                padding=10,
                border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                border_radius=8,
                content=ft.Text(f"下载队列状态读取失败：{exc}", color=ft.Colors.ERROR),
            )

        global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
        paused = bool(global_state.get("paused"))
        running = 0
        waiting = 0
        completed = 0
        failed = 0
        for kind, stats in snapshot.items() if isinstance(snapshot, dict) else []:
            if kind == "__global__" or not isinstance(stats, dict):
                continue
            running += int(stats.get("running", 0) or 0)
            waiting += int(stats.get("waiting", 0) or 0)
            completed += int(stats.get("completed", 0) or 0)
            failed += int(stats.get("failed", 0) or 0)
        running_labels = [str(label) for label in global_state.get("running_labels", []) if label]
        waiting_labels = [str(label) for label in global_state.get("waiting_labels", []) if label]
        active_text = "、".join(running_labels[:3]) if running_labels else "暂无运行任务"
        waiting_text = "、".join(waiting_labels[:3]) if waiting_labels else "暂无等待任务"
        status_text = "已暂停" if paused else "运行中"
        status_color = ft.Colors.ORANGE if paused else ft.Colors.GREEN
        return ft.Container(
            padding=12,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.DOWNLOAD, color=ft.Colors.PRIMARY),
                            ft.Text("下载队列", weight=ft.FontWeight.BOLD),
                            ft.Container(
                                content=ft.Text(status_text, size=11, color=ft.Colors.WHITE),
                                bgcolor=status_color,
                                border_radius=10,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                            ),
                            ft.Text(
                                f"并发上限 {global_state.get('limit', 0) or 0} / 运行 {running} / 等待 {waiting} / 完成 {completed} / 失败 {failed}",
                                color=ft.Colors.ON_SURFACE_VARIANT,
                                size=12,
                            ),
                        ],
                        spacing=8,
                        wrap=True,
                    ),
                    ft.Text(f"当前：{active_text}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(f"等待：{waiting_text}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, overflow=ft.TextOverflow.ELLIPSIS),
                ],
                spacing=4,
            ),
        )

    def _filter_area(self) -> ft.Column:
        status_options = [
            ("all", "全部"),
            ("running", "运行中"),
            ("failed", "失败"),
            ("cancelled", "已取消"),
            ("completed", "完成"),
            ("waiting", "等待中"),
        ]
        quick_options = [
            ("retryable", "可重试"),
            ("today", "今天"),
            ("downloading", "下载中"),
        ]
        category_options = [
            ("all", "全部类型"),
            ("视频解析", "视频解析"),
            ("内容监控", "内容监控"),
            ("作品监控", "作品监控"),
            ("内容监控下载", "内容下载"),
            ("视频下载", "视频下载"),
            ("图片下载", "图片下载"),
        ]
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        self.search_field,
                        ft.IconButton(icon=ft.Icons.CLEAR, tooltip="清空搜索", on_click=lambda e: self.run_async(self.clear_search()), icon_color=ft.Colors.PRIMARY),
                        ft.Text(
                            f"当前：{self._status_filter_label(self.status_filter)} / {self._category_filter_label(self.category_filter)}",
                            size=12,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                self._filter_group("状态", status_options, self.status_filter, self.set_status_filter),
                self._filter_group("类型", category_options, self.category_filter, self.set_category_filter),
                self._filter_group("快捷", quick_options, self.status_filter, self.set_status_filter),
            ],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    def _filter_group(self, title: str, options: list[tuple[str, str]], current: str, setter) -> ft.Row:
        return ft.Row(
            controls=[
                ft.Container(
                    width=44,
                    content=ft.Text(f"{title}：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ),
                *[self._filter_button(label, str(current) == key, lambda mode=key: setter(mode)) for key, label in options],
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _filtered_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        mode = str(self.status_filter or "all")
        if mode == "running":
            records = [record for record in records if record.get("status") == TASK_STATUS_RUNNING]
        elif mode == "failed":
            records = [record for record in records if record.get("status") == TASK_STATUS_FAILED]
        elif mode == "cancelled":
            records = [record for record in records if record.get("status") == TASK_STATUS_CANCELLED]
        elif mode == "completed":
            records = [record for record in records if record.get("status") == TASK_STATUS_COMPLETED]
        elif mode == "waiting":
            records = [record for record in records if record.get("status") == TASK_STATUS_WAITING]
        elif mode == "retryable":
            records = [record for record in records if record.get("status") == TASK_STATUS_FAILED and record.get("retry_action")]
        elif mode == "today":
            today = datetime.now().strftime("%Y-%m-%d")
            records = [record for record in records if self._record_time(record).startswith(today)]
        elif mode == "downloading":
            download_categories = {"内容监控下载", "视频下载", "图片下载"}
            active_statuses = {TASK_STATUS_RUNNING, TASK_STATUS_WAITING}
            records = [record for record in records if record.get("category") in download_categories and record.get("status") in active_statuses]
        category = str(self.category_filter or "all")
        if category != "all":
            records = [record for record in records if record.get("category") == category]
        query = str(self.search_query or "").strip().lower()
        if query:
            records = [record for record in records if query in self._record_search_text(record)]
        return records

    def _all_records(self, limit: int = 500) -> list[dict[str, Any]]:
        center = getattr(self.app.services, "task_center", None)
        return center.snapshot(limit) if center is not None and hasattr(center, "snapshot") else []

    @staticmethod
    def _record_counts(records: list[dict[str, Any]]) -> dict[str, int]:
        return {
            "total": len(records),
            "running": len([record for record in records if record.get("status") == TASK_STATUS_RUNNING]),
            "waiting": len([record for record in records if record.get("status") == TASK_STATUS_WAITING]),
            "failed": len([record for record in records if record.get("status") == TASK_STATUS_FAILED]),
            "cancelled": len([record for record in records if record.get("status") == TASK_STATUS_CANCELLED]),
            "completed": len([record for record in records if record.get("status") == TASK_STATUS_COMPLETED]),
            "retryable": len([record for record in records if record.get("status") == TASK_STATUS_FAILED and record.get("retry_action")]),
        }

    @staticmethod
    def _record_time(record: dict[str, Any]) -> str:
        return str(record.get("updated_at") or record.get("started_at") or record.get("finished_at") or "")

    def _queue_has_active_downloads(self) -> bool:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return False
        try:
            snapshot = queue.snapshot()
        except Exception:
            return False
        global_state = snapshot.get("__global__", {}) if isinstance(snapshot, dict) else {}
        if int(global_state.get("inflight", 0) or 0) > 0:
            return True
        for kind, stats in snapshot.items() if isinstance(snapshot, dict) else []:
            if kind == "__global__" or not isinstance(stats, dict):
                continue
            if int(stats.get("running", 0) or 0) > 0 or int(stats.get("waiting", 0) or 0) > 0:
                return True
        return False

    @staticmethod
    def _stat_chip(label: str, count: int, color: str) -> ft.Container:
        return ft.Container(
            content=ft.Text(f"{label} {count}", size=12, color=color),
            padding=ft.Padding.symmetric(horizontal=10, vertical=5),
            border=ft.Border.all(1, color),
            border_radius=16,
        )

    def _toolbar_icon_button(self, icon: str, tooltip: str, action, disabled: bool = False, danger: bool = False) -> ft.Control:
        return ft.IconButton(
            icon=icon,
            tooltip=tooltip,
            disabled=disabled,
            on_click=lambda e: self.run_async(action()),
            icon_color=ft.Colors.ERROR if danger else ft.Colors.PRIMARY,
            icon_size=22,
        )

    def _filter_button(self, label: str, selected: bool, action) -> ft.Control:
        text_color = ft.Colors.WHITE if selected else ft.Colors.PRIMARY
        border_color = ft.Colors.PRIMARY if selected else ft.Colors.OUTLINE_VARIANT
        return ft.Container(
            height=30,
            padding=ft.Padding.symmetric(horizontal=12, vertical=3),
            border=ft.Border.all(1, border_color),
            border_radius=15,
            bgcolor=ft.Colors.PRIMARY if selected else None,
            on_click=lambda e: self.run_async(action()),
            content=ft.Row(
                controls=[
                    *([ft.Icon(ft.Icons.CHECK, size=14, color=text_color)] if selected else []),
                    ft.Text(label, size=12, color=text_color),
                ],
                spacing=4,
                tight=True,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        )

    @staticmethod
    def _record_search_text(record: dict[str, Any]) -> str:
        parts = [
            record.get("title"),
            record.get("category"),
            record.get("status"),
            record.get("detail"),
            record.get("retry_action"),
            json.dumps(record.get("retry_payload") or {}, ensure_ascii=False),
        ]
        return " ".join(str(part or "") for part in parts).lower()

    async def refresh(self) -> None:
        if self.records_area is None:
            return
        records = self._filtered_records(self._all_records(200))
        self.records_area.controls.clear()
        if not records:
            self.records_area.controls.append(
                ft.Container(
                    padding=16,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                    content=ft.Text("暂无匹配任务记录。开始解析或下载后会在这里显示。", color=ft.Colors.ON_SURFACE_VARIANT),
                )
            )
        else:
            for record in records:
                self.records_area.controls.append(self._record_card(record))
        try:
            self.records_area.update()
        except Exception:
            pass

    async def set_status_filter(self, mode: str) -> None:
        self.status_filter = str(mode or "all")
        count = len(self._filtered_records(self._all_records(500)))
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已切换状态筛选：{self._status_filter_label(self.status_filter)}，匹配 {count} 条", bgcolor=ft.Colors.PRIMARY)

    async def set_category_filter(self, mode: str) -> None:
        self.category_filter = str(mode or "all")
        count = len(self._filtered_records(self._all_records(500)))
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已切换类型筛选：{self._category_filter_label(self.category_filter)}，匹配 {count} 条", bgcolor=ft.Colors.PRIMARY)

    async def set_search_query(self, value: str) -> None:
        self.search_query = str(value or "")
        await self.refresh()

    async def clear_search(self) -> None:
        self.search_query = ""
        if self.search_field is not None:
            self.search_field.value = ""
        await self.refresh()
        await self.app.snack_bar.show_snack_bar("已清空搜索", bgcolor=ft.Colors.PRIMARY)

    async def reload(self) -> None:
        await self.load()
        await self.app.snack_bar.show_snack_bar("任务中心已刷新", bgcolor=ft.Colors.PRIMARY)

    @staticmethod
    def _status_filter_label(mode: str) -> str:
        return {
            "all": "全部",
            "running": "运行中",
            "failed": "失败",
            "cancelled": "已取消",
            "completed": "完成",
            "waiting": "等待中",
            "retryable": "可重试",
            "today": "今天",
            "downloading": "下载中",
        }.get(str(mode or "all"), "全部")

    @staticmethod
    def _category_filter_label(mode: str) -> str:
        return {
            "all": "全部类型",
            "视频解析": "视频解析",
            "内容监控": "内容监控",
            "作品监控": "作品监控",
            "内容监控下载": "内容下载",
            "视频下载": "视频下载",
            "图片下载": "图片下载",
        }.get(str(mode or "all"), "全部类型")

    async def clear_completed(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        before = self._record_counts(self._all_records()).get("completed", 0)
        if center is not None:
            center.clear_completed()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清除完成任务 {before} 条", bgcolor=ft.Colors.PRIMARY)

    async def clear_failed(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        before = self._record_counts(self._all_records()).get("failed", 0)
        if center is not None and hasattr(center, "clear_failed"):
            center.clear_failed()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清除失败任务 {before} 条", bgcolor=ft.Colors.PRIMARY)

    async def clear_cancelled(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        before = self._record_counts(self._all_records()).get("cancelled", 0)
        if center is not None and hasattr(center, "clear_cancelled"):
            center.clear_cancelled()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清除已取消任务 {before} 条", bgcolor=ft.Colors.PRIMARY)

    async def confirm_clear_all_tasks(self) -> None:
        records = self._all_records()
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无任务记录可清空", bgcolor=ft.Colors.PRIMARY)
            return

        async def confirm(_=None):
            self.close_dialog(dialog)
            await self.clear_all_tasks()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("清空全部任务记录"),
            content=ft.Text(f"将清空全部 {len(records)} 条任务记录。此操作不会删除已下载文件，是否继续？"),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.FilledButton("清空", icon=ft.Icons.DELETE_FOREVER, on_click=lambda e: self.run_async(confirm())),
            ],
        )
        self.show_dialog(dialog)

    async def clear_all_tasks(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        before = len(self._all_records())
        if center is not None and hasattr(center, "clear_all"):
            center.clear_all()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清空任务记录 {before} 条", bgcolor=ft.Colors.PRIMARY)

    def _task_export_dir(self) -> str:
        return os.path.join(self.app.run_path, "downloads", "task_exports")

    async def open_task_export_dir(self) -> None:
        path = self._task_export_dir()
        os.makedirs(path, exist_ok=True)
        await self.open_path_or_url(path, success="已打开任务导出目录")

    async def export_tasks_csv(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        records = center.snapshot(500) if center is not None else []
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无任务记录可导出", bgcolor=ft.Colors.ERROR)
            return
        export_dir = self._task_export_dir()
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"task_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "任务标题",
                    "类型",
                    "状态",
                    "说明",
                    "总数",
                    "完成数",
                    "成功数",
                    "失败数",
                    "开始时间",
                    "更新时间",
                    "结束时间",
                    "失败归类",
                    "建议处理",
                    "重试动作",
                    "重试参数",
                ]
            )
            for record in records:
                failure = classify_failure(str(record.get("detail") or "")) if record.get("status") == TASK_STATUS_FAILED else {}
                writer.writerow(
                    [
                        record.get("title") or "",
                        record.get("category") or "",
                        record.get("status") or "",
                        record.get("detail") or "",
                        record.get("total") or 0,
                        record.get("completed") or 0,
                        record.get("success_count") or 0,
                        record.get("failed_count") or 0,
                        record.get("started_at") or "",
                        record.get("updated_at") or "",
                        record.get("finished_at") or "",
                        failure.get("category", ""),
                        failure.get("next_step", ""),
                        record.get("retry_action") or "",
                        record.get("retry_payload") or {},
                    ]
                )
        await self.app.snack_bar.show_snack_bar(f"已导出：{path}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)

    async def toggle_download_queue(self) -> None:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None:
            await self.app.snack_bar.show_snack_bar("下载队列不可用", bgcolor=ft.Colors.ERROR)
            return
        if queue.is_paused():
            queue.resume()
            await self.app.snack_bar.show_snack_bar("下载队列已继续", bgcolor=ft.Colors.PRIMARY)
        else:
            queue.pause()
            await self.app.snack_bar.show_snack_bar("下载队列已暂停，新任务会等待；正在写入的请求会尽快停在安全点", bgcolor=ft.Colors.PRIMARY)
        await self.load()

    async def cancel_download_queue(self) -> None:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "cancel_all"):
            await self.app.snack_bar.show_snack_bar("下载队列不可用", bgcolor=ft.Colors.ERROR)
            return
        if not self._queue_has_active_downloads():
            await self.app.snack_bar.show_snack_bar("当前没有运行或等待中的下载任务", bgcolor=ft.Colors.PRIMARY)
            await self.load()
            return
        queue.cancel_all()
        if hasattr(queue, "resume"):
            queue.resume()
        await self.app.snack_bar.show_snack_bar("已取消当前下载队列，运行中的任务会标记为已取消", bgcolor=ft.Colors.PRIMARY)
        await self.load()

    def _record_card(self, record: dict[str, Any]) -> ft.Container:
        status = str(record.get("status") or "")
        detail = str(record.get("detail") or "")
        color = self._status_color(status)
        failure = classify_failure(detail) if status == TASK_STATUS_FAILED else {}
        total = int(record.get("total") or 0)
        completed = int(record.get("completed") or 0)
        progress = f"{completed}/{total}" if total else "-"
        body_lines = [
            f"类型：{record.get('category') or '-'}",
            f"进度：{progress}，成功 {record.get('success_count') or 0}，失败 {record.get('failed_count') or 0}",
            f"开始：{record.get('started_at') or '-'}",
        ]
        if record.get("finished_at"):
            body_lines.append(f"结束：{record.get('finished_at')}")
        if detail:
            body_lines.append(f"说明：{detail}")
        if failure:
            body_lines.append(f"归类：{failure.get('category')}")
            body_lines.append(failure.get("next_step") or "")
        failed_ids = self._retry_failed_ids(record)
        if failed_ids:
            body_lines.append(f"可重试失败项：{len(failed_ids)} 个")
        actions: list[ft.Control] = []
        if status == TASK_STATUS_FAILED and record.get("retry_action"):
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.REPLAY,
                    tooltip="重试任务",
                    on_click=lambda e, task=record: self.run_async(self.retry_task(task)),
                    icon_color=ft.Colors.PRIMARY,
                )
            )
        actions.append(
            ft.IconButton(
                icon=ft.Icons.INFO_OUTLINE,
                tooltip="查看任务详情",
                on_click=lambda e, task=record: self.show_task_detail(task),
                icon_color=ft.Colors.PRIMARY,
            )
        )
        if self._has_locatable_payload(record):
            actions.append(
                ft.IconButton(
                    icon=ft.Icons.MY_LOCATION,
                    tooltip="定位到相关账号/作品",
                    on_click=lambda e, task=record: self.run_async(self.locate_task(task)),
                    icon_color=ft.Colors.PRIMARY,
                )
            )
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=12,
            content=ft.Column(
                controls=[
                    ft.Row(
                        controls=[
                            ft.Text(str(record.get("title") or "任务"), weight=ft.FontWeight.BOLD, expand=True, selectable=True),
                            ft.Container(
                                content=ft.Text(status or "-", size=11, color=ft.Colors.WHITE),
                                bgcolor=color,
                                border_radius=10,
                                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ft.Text("\n".join(line for line in body_lines if line), size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                    *([ft.Row(actions, spacing=4, wrap=True)] if actions else []),
                ],
                spacing=6,
            ),
        )

    @staticmethod
    def _has_locatable_payload(record: dict[str, Any]) -> bool:
        payload = record.get("retry_payload")
        return isinstance(payload, dict) and bool(payload.get("account_id"))

    async def locate_task(self, record: dict[str, Any]) -> None:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        account_id = str(payload.get("account_id") or "")
        item_ids = {str(item_id) for item_id in payload.get("item_ids", []) if item_id}
        if not account_id:
            await self.app.snack_bar.show_snack_bar("任务没有可定位的账号信息", bgcolor=ft.Colors.ERROR)
            return
        content_page = getattr(self.app, "douyin_content", None)
        if content_page is None:
            await self.app.snack_bar.show_snack_bar("内容监控页面不可用", bgcolor=ft.Colors.ERROR)
            return
        if hasattr(self.app, "switch_page"):
            await self.app.switch_page(getattr(content_page, "page_name", "douyin_content"))
        await content_page.open_account_works(account_id)
        content_page.selected_work_ids = item_ids
        content_page.work_select_mode = bool(item_ids)
        await content_page.render_current_view()

    async def retry_task(self, record: dict[str, Any]) -> None:
        action = str(record.get("retry_action") or "")
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        if action == "content_download_items":
            await self._retry_content_download_items(payload, notify=True)
            return
        await self.app.snack_bar.show_snack_bar("当前任务不支持自动重试", bgcolor=ft.Colors.ERROR)

    async def retry_all_failed_tasks(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        records = center.snapshot(500) if center is not None else []
        retryable = [record for record in records if record.get("status") == TASK_STATUS_FAILED and record.get("retry_action")]
        if not retryable:
            await self.app.snack_bar.show_snack_bar("没有可重试的失败任务", bgcolor=ft.Colors.PRIMARY)
            return
        success_tasks = 0
        failed_tasks = 0
        for record in retryable:
            action = str(record.get("retry_action") or "")
            payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
            try:
                if action == "content_download_items":
                    result = await self._retry_content_download_items(payload, notify=False)
                    if result.get("success"):
                        success_tasks += 1
                    else:
                        failed_tasks += 1
                else:
                    failed_tasks += 1
            except Exception:
                failed_tasks += 1
            await asyncio.sleep(0.1)
        await self.load()
        await self.app.snack_bar.show_snack_bar(
            f"失败任务重试完成：成功任务 {success_tasks} 个，仍失败 {failed_tasks} 个",
            bgcolor=ft.Colors.PRIMARY if failed_tasks == 0 else ft.Colors.ERROR,
            duration=6000,
            show_close_icon=True,
        )

    async def _retry_content_download_items(self, payload: dict[str, Any], notify: bool = True) -> dict[str, Any]:
        manager = getattr(self.app.services, "douyin_content_monitor", None)
        center = getattr(self.app.services, "task_center", None)
        account_id = str(payload.get("account_id") or "")
        item_ids = self._payload_retry_item_ids(payload)
        if manager is None or not account_id or not item_ids:
            if notify:
                await self.app.snack_bar.show_snack_bar("重试信息不完整，无法自动重试", bgcolor=ft.Colors.ERROR)
            return {"success": False, "reason": "重试信息不完整"}
        account = manager.find_account(account_id)
        if account is None:
            if notify:
                await self.app.snack_bar.show_snack_bar("重试账号不存在", bgcolor=ft.Colors.ERROR)
            return {"success": False, "reason": "重试账号不存在"}
        name = account.display_name or account.douyin_nickname or account.account_id
        unique_ids = list(dict.fromkeys(item_ids))
        failed_item_ids: list[str] = []
        task_id = (
            center.start(
                f"重试失败下载：{name}",
                "内容监控下载",
                total=len(unique_ids),
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids},
            )
            if center is not None
            else None
        )
        success = 0
        failed = 0
        try:
            for index, item_id in enumerate(unique_ids, start=1):
                try:
                    result = await manager.download_item(account_id, item_id)
                except asyncio.CancelledError:
                    if center is not None and task_id and hasattr(center, "cancel"):
                        center.cancel(task_id, f"重试已取消：成功 {success}，失败 {failed}")
                    await self.load()
                    if notify:
                        await self.app.snack_bar.show_snack_bar("重试已取消", bgcolor=ft.Colors.PRIMARY)
                    return {"success": False, "reason": "重试已取消", "success_count": success, "failed_count": failed}
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
                    failed_item_ids.append(item_id)
                if center is not None and task_id:
                    retry_payload = {
                        "account_id": account_id,
                        "item_ids": failed_item_ids or unique_ids,
                        "all_item_ids": unique_ids,
                        "failed_item_ids": failed_item_ids,
                    }
                    center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"重试进度：{index}/{len(unique_ids)}，成功 {success}，失败 {failed}",
                        retry_payload=retry_payload,
                    )
        except Exception as exc:
            if center is not None and task_id:
                center.finish(task_id, success=False, detail=f"重试失败：{exc}")
            await self.load()
            if notify:
                await self.app.snack_bar.show_snack_bar(f"重试失败：{exc}", bgcolor=ft.Colors.ERROR, duration=6000, show_close_icon=True)
            return {"success": False, "reason": str(exc), "success_count": success, "failed_count": failed}
        if center is not None and task_id:
            center.finish(task_id, success=failed == 0, detail=f"重试完成：成功 {success}，失败 {failed}")
        await self.load()
        if notify:
            await self.app.snack_bar.show_snack_bar(
                f"重试完成：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=6000,
                show_close_icon=True,
            )
        return {"success": failed == 0, "success_count": success, "failed_count": failed}

    @staticmethod
    def _payload_retry_item_ids(payload: dict[str, Any]) -> list[str]:
        failed_ids = [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]
        if failed_ids:
            return failed_ids
        return [str(item_id) for item_id in payload.get("item_ids", []) if item_id]

    @staticmethod
    def _retry_failed_ids(record: dict[str, Any]) -> list[str]:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        return [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]

    def show_task_detail(self, record: dict[str, Any]) -> None:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        failure = classify_failure(str(record.get("detail") or "")) if record.get("status") == TASK_STATUS_FAILED else {}
        failed_ids = [str(item_id) for item_id in payload.get("failed_item_ids", []) if item_id]
        lines = [
            f"标题：{record.get('title') or '-'}",
            f"类型：{record.get('category') or '-'}",
            f"状态：{record.get('status') or '-'}",
            f"进度：{record.get('completed') or 0}/{record.get('total') or 0}",
            f"成功：{record.get('success_count') or 0}",
            f"失败：{record.get('failed_count') or 0}",
            f"开始：{record.get('started_at') or '-'}",
            f"更新：{record.get('updated_at') or '-'}",
            f"结束：{record.get('finished_at') or '-'}",
            f"说明：{record.get('detail') or '-'}",
        ]
        if failure:
            lines.append(f"失败归类：{failure.get('category')}")
            lines.append(f"建议处理：{failure.get('next_step')}")
        if failed_ids:
            lines.append("失败作品ID：")
            lines.extend(f"  {item_id}" for item_id in failed_ids[:200])
        if payload:
            lines.append("重试参数：")
            lines.append(json.dumps(payload, ensure_ascii=False, indent=2))

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("任务详情"),
            content=ft.Column(
                controls=[ft.Text("\n".join(lines), selectable=True, size=12)],
                tight=True,
                width=760,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog))],
        )
        self.show_dialog(dialog)

    @staticmethod
    def _status_color(status: str) -> str:
        if status == TASK_STATUS_COMPLETED:
            return ft.Colors.GREEN
        if status == TASK_STATUS_FAILED:
            return ft.Colors.ERROR
        if status == TASK_STATUS_CANCELLED:
            return ft.Colors.ON_SURFACE_VARIANT
        if status == TASK_STATUS_RUNNING:
            return ft.Colors.PRIMARY
        return ft.Colors.ON_SURFACE_VARIANT

    async def _await_coro(self, coro) -> None:
        await coro

    def run_async(self, coro) -> None:
        self.page.run_task(self._await_coro, coro)
