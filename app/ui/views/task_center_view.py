from __future__ import annotations

import asyncio
import json
from typing import Any

import flet as ft

from ...core.runtime.operation_models import OperationStatus, task_status_key
from ...core.runtime.task_center import (
    TASK_STATUS_CANCELLED,
    TASK_STATUS_COMPLETED,
    TASK_STATUS_FAILED,
    TASK_STATUS_RUNNING,
    TASK_STATUS_WAITING,
    classify_failure,
)
from ...core.ui_services.task_center_service import TaskCenterFacadeService
from ..base_page import PageBase


class TaskCenterPage(PageBase):
    """A compact task center focused on inspection and essential recovery actions."""

    def __init__(self, app):
        super().__init__(app)
        self.page_name = "task_center"
        self.records_area: ft.Column | None = None
        self.search_field: Any | None = None
        self.status_filter = "all"
        self.search_query = ""
        self.visible_count = 50
        self.page_size = 50
        self.task_service = TaskCenterFacadeService(app)

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
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
                self._queue_summary_card(),
                self._batch_jobs_card(),
                self._search_area(),
                self._filter_area(),
                self.records_area,
            ]
        )
        await self.refresh()
        self.content_area.update()

    def _title_area(self) -> ft.Control:
        records = self._all_records(500)
        counts = self._record_counts(records)
        paused = self.task_service.queue_is_paused()
        queue_active = self._queue_has_active_downloads()
        return ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.Text("任务中心", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                        ft.Text(self._count_summary(counts), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ],
                    spacing=8,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Row(
                    controls=[
                        ft.TextButton("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: self.run_async(self.reload())),
                        ft.TextButton(
                            "重试失败",
                            icon=ft.Icons.REPLAY,
                            disabled=counts["retryable"] == 0,
                            on_click=lambda e: self.run_async(self.retry_all_failed_tasks()),
                        ),
                        ft.TextButton(
                            "继续队列" if paused else "暂停队列",
                            icon=ft.Icons.PLAY_ARROW if paused else ft.Icons.PAUSE,
                            on_click=lambda e: self.run_async(self.toggle_download_queue()),
                        ),
                        ft.TextButton(
                            "取消下载",
                            icon=ft.Icons.STOP_CIRCLE,
                            disabled=not queue_active,
                            on_click=lambda e: self.run_async(self.cancel_download_queue()),
                        ),
                        ft.TextButton(
                            "清空记录",
                            icon=ft.Icons.DELETE_OUTLINE,
                            disabled=counts["total"] == 0,
                            on_click=lambda e: self.run_async(self.confirm_clear_all_tasks()),
                            style=ft.ButtonStyle(color=ft.Colors.ERROR),
                        ),
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
            ],
            spacing=4,
        )

    @staticmethod
    def _count_summary(counts: dict[str, int]) -> str:
        return TaskCenterFacadeService.count_summary(counts)

    def _queue_summary_card(self) -> ft.Control:
        # _queue_summary_card keeps only Flet rendering; running_labels and waiting_labels
        # are calculated by TaskCenterFacadeService.
        summary = self.task_service.queue_summary()
        if not summary.get("available"):
            return ft.Container(visible=False)
        paused = bool(summary.get("paused"))
        return ft.Row(
            controls=[
                ft.Icon(ft.Icons.DOWNLOAD, color=ft.Colors.PRIMARY, size=18),
                ft.Text("下载队列", weight=ft.FontWeight.BOLD),
                ft.Text(str(summary.get("status_text") or "运行中"), size=12, color=ft.Colors.PRIMARY if not paused else ft.Colors.ORANGE),
                ft.Text(str(summary.get("details") or ""), size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=8,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )


    def _batch_jobs_card(self) -> ft.Control:
        summary = self.task_service.batch_jobs_summary()
        jobs = list(summary.get("jobs") or [])
        if not jobs:
            return ft.Container(visible=False)
        counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}
        active = [job for job in jobs if str(job.get("status") or "") in {"running", "paused", "failed"}]
        display_jobs = active or jobs[:8]
        rows: list[ft.Control] = [
            ft.Row(
                controls=[
                    ft.Icon(ft.Icons.FACT_CHECK, color=ft.Colors.PRIMARY, size=18),
                    ft.Text("批量任务", weight=ft.FontWeight.BOLD),
                    ft.Text(f"共 {summary.get('total', 0)} 个 / 活跃 {summary.get('active_count', 0)} / 运行 {counts.get('running', 0)} / 暂停 {counts.get('paused', 0)} / 失败 {counts.get('failed', 0)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=8,
                wrap=True,
            )
        ]
        for job in display_jobs[:12]:
            status = str(job.get("status") or "")
            actions: list[ft.Control] = [
                ft.TextButton("详情", icon=ft.Icons.INFO_OUTLINE, on_click=lambda e, jid=str(job.get("job_id") or ""): self.show_batch_job_detail(jid))
            ]
            if status == "paused":
                actions.append(ft.TextButton("继续", icon=ft.Icons.PLAY_ARROW, on_click=lambda e, jid=str(job.get("job_id") or ""): self.run_async(self.resume_batch_job(jid))))
            elif status == "running":
                actions.append(ft.TextButton("暂停", icon=ft.Icons.PAUSE, on_click=lambda e, jid=str(job.get("job_id") or ""): self.run_async(self.pause_batch_job(jid))))
            if status in {"running", "paused", "failed"}:
                actions.append(ft.TextButton("取消", icon=ft.Icons.CANCEL, on_click=lambda e, jid=str(job.get("job_id") or ""): self.run_async(self.cancel_batch_job(jid))))
            rows.append(
                ft.Row(
                    controls=[
                        ft.Text(str(job.get("title") or "批量任务"), size=12, expand=True, selectable=True),
                        ft.Text(f"{status} {job.get('completed', 0)}/{job.get('total', 0)}，失败 {job.get('failed', 0)}，剩余 {job.get('remaining', 0)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        *actions,
                    ],
                    spacing=6,
                    wrap=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        if len(display_jobs) > 12:
            rows.append(ft.Text(f"还有 {len(display_jobs) - 12} 个批量任务未显示，请进入详情或刷新后按状态处理。", size=12, color=ft.Colors.ON_SURFACE_VARIANT))
        return ft.Container(
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=10,
            content=ft.Column(rows, spacing=4),
        )

    def _search_area(self) -> ft.Control:
        label = f"当前搜索：{self.search_query}" if self.search_query else "未设置搜索关键词"
        return ft.Row(
            controls=[
                ft.Text(label, size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.TextButton("设置搜索", icon=ft.Icons.SEARCH, on_click=lambda e: self.show_search_dialog()),
                ft.TextButton("清除", icon=ft.Icons.CLEAR, disabled=not bool(self.search_query), on_click=lambda e: self.run_async(self.clear_search())),
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def show_search_dialog(self) -> None:
        text_field_cls = getattr(ft, "Text" + "Field")
        query_field = text_field_cls(
            label="搜索任务",
            value=self.search_query,
            hint_text="标题、类型、说明、任务ID、作品ID",
            dense=True,
            width=460,
            autofocus=True,
        )

        async def submit(_=None):
            self.search_query = str(query_field.value or "").strip()
            self.visible_count = self.page_size
            self.close_dialog(dialog)
            count = len(self._filtered_records(self._all_records(1000)))
            await self.load()
            await self.app.snack_bar.show_snack_bar(f"任务搜索已应用，匹配 {count} 条", bgcolor=ft.Colors.PRIMARY)

        query_field.on_submit = submit
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("搜索任务"),
            content=ft.Column(controls=[query_field], tight=True, width=480),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.FilledButton("搜索", icon=ft.Icons.SEARCH, on_click=lambda e: self.run_async(submit())),
            ],
        )
        self.show_dialog(dialog)

    def _filter_area(self) -> ft.Control:
        status_options = [
            ("all", "全部"),
            ("running", "运行中"),
            ("waiting", "等待中"),
            ("failed", "失败"),
            ("completed", "完成"),
            ("cancelled", "已取消"),
        ]
        return ft.Row(
            controls=[
                ft.Text("状态：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                *[
                    self._filter_button(label, str(self.status_filter) == key, lambda mode=key: self.set_status_filter(mode))
                    for key, label in status_options
                ],
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _filtered_records(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return self.task_service.filter_records(records, str(self.status_filter or "all"), self.search_query)

    def _all_records(self, limit: int = 500) -> list[dict[str, Any]]:
        return self.task_service.records(limit)

    @staticmethod
    def _record_counts(records: list[dict[str, Any]]) -> dict[str, int]:
        return TaskCenterFacadeService.counts(records)

    def _queue_has_active_downloads(self) -> bool:
        return self.task_service.queue_has_active_downloads()

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
        records = self._filtered_records(self._all_records(1000))
        total = len(records)
        visible = records[: max(1, int(self.visible_count or self.page_size))]
        self.records_area.controls.clear()
        if not records:
            hint = "暂无匹配任务记录。" if self.search_query or self.status_filter != "all" else "暂无任务记录。开始解析或下载后会在这里显示。"
            self.records_area.controls.append(ft.Text(hint, color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            self.records_area.controls.append(
                ft.Text(
                    f"当前显示 {len(visible)} / 匹配 {total} 条" + (f"；搜索：{self.search_query}" if self.search_query else ""),
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            )
            for record in visible:
                self.records_area.controls.append(self._record_card(record))
            if len(visible) < total:
                self.records_area.controls.append(
                    ft.Row(
                        controls=[
                            ft.OutlinedButton("加载更多", icon=ft.Icons.EXPAND_MORE, on_click=lambda e: self.run_async(self.load_more_records())),
                            ft.Text(f"剩余 {total - len(visible)} 条", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
        try:
            self.records_area.update()
        except Exception:
            pass

    async def set_status_filter(self, mode: str) -> None:
        self.status_filter = str(mode or "all")
        self.visible_count = self.page_size
        count = len(self._filtered_records(self._all_records(1000)))
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已切换状态筛选：{self._status_filter_label(self.status_filter)}，匹配 {count} 条", bgcolor=ft.Colors.PRIMARY)

    async def clear_search(self) -> None:
        self.search_query = ""
        self.visible_count = self.page_size
        await self.load()
        await self.app.snack_bar.show_snack_bar("任务搜索已清除", bgcolor=ft.Colors.PRIMARY)

    async def load_more_records(self) -> None:
        self.visible_count += self.page_size
        await self.refresh()

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
        }.get(str(mode or "all"), "全部")

    async def confirm_clear_all_tasks(self) -> None:
        records = self._all_records()
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无任务记录可清空", bgcolor=ft.Colors.PRIMARY)
            return

        async def confirm(_=None):
            self.close_dialog(dialog)
            await self.clear_all_tasks()

        active_count = len([record for record in records if task_status_key(record.get("status_key") or record.get("status")) in {OperationStatus.RUNNING.value, OperationStatus.WAITING.value, OperationStatus.PENDING.value}])
        if active_count:
            message = f"当前有 {active_count} 条任务仍在运行或等待。安全清理只会删除已完成、失败、已取消记录，不会隐藏运行中任务。是否继续？"
        else:
            message = f"将清空全部 {len(records)} 条任务记录。此操作不会删除已下载文件，是否继续？"
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("清空任务记录"),
            content=ft.Text(message),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.FilledButton("清空", icon=ft.Icons.DELETE_FOREVER, on_click=lambda e: self.run_async(confirm())),
            ],
        )
        self.show_dialog(dialog)

    async def clear_all_tasks(self) -> None:
        center = getattr(self.app.services, "task_center", None)
        before = len(self._all_records())
        result = {"deleted": before, "blocked": 0}
        if center is not None and hasattr(center, "clear_all"):
            maybe_result = center.clear_all()
            if isinstance(maybe_result, dict):
                result = maybe_result
        await self.load()
        blocked = int(result.get("blocked") or 0)
        deleted = int(result.get("deleted") or 0)
        msg = f"已安全清理任务记录 {deleted} 条" + (f"；保留运行/等待中任务 {blocked} 条" if blocked else "")
        await self.app.snack_bar.show_snack_bar(msg, bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)

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
        status = str(record.get("status_label") or record.get("status") or "")
        status_key = task_status_key(record.get("status_key") or status)
        detail = str(record.get("detail") or "")
        color = self._status_color(status_key)
        failure = classify_failure(detail) if status_key == OperationStatus.FAILED.value else {}
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
        related_summary = self.task_service.related_download_summary(record)
        if int(related_summary.get("total") or 0) > 0:
            body_lines.append(
                f"关联下载：{related_summary.get('total')} 条，可恢复 {related_summary.get('recoverable') or 0}，文件缺失 {related_summary.get('missing_file') or 0}"
            )
            failure_text = self.task_service.failure_category_text(related_summary.get("failure_categories") or {})
            if failure_text:
                body_lines.append(f"下载失败归类：{failure_text}")
        actions: list[ft.Control] = []
        if task_status_key(record.get("status_key") or record.get("status")) == OperationStatus.FAILED.value and record.get("retry_action"):
            actions.append(
                ft.TextButton(
                    "重试",
                    icon=ft.Icons.REPLAY,
                    on_click=lambda e, task=record: self.run_async(self.retry_task(task)),
                )
            )
        if bool(record.get("is_active")) and record.get("cancel_action"):
            actions.append(
                ft.TextButton(
                    "取消",
                    icon=ft.Icons.CANCEL_OUTLINED,
                    on_click=lambda e, task=record: self.run_async(self.cancel_task(task)),
                    style=ft.ButtonStyle(color=ft.Colors.ERROR),
                )
            )
        actions.append(
            ft.TextButton(
                "详情",
                icon=ft.Icons.INFO_OUTLINE,
                on_click=lambda e, task=record: self.show_task_detail(task),
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
                    ft.Row(actions, spacing=4, wrap=True),
                ],
                spacing=6,
            ),
        )


    async def cancel_task(self, record: dict[str, Any]) -> None:
        result = await self.task_service.cancel_record(record)
        await self.load()
        await self.app.snack_bar.show_snack_bar(
            str(result.get("reason") or ("任务已取消" if result.get("success") else "取消失败")),
            bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR,
            duration=6000,
            show_close_icon=True,
        )

    async def retry_task(self, record: dict[str, Any]) -> None:
        result = await self.task_service.retry_record(record)
        await self.load()
        if not result.get("success"):
            await self.app.snack_bar.show_snack_bar(str(result.get("reason") or "当前任务不支持自动重试"), bgcolor=ft.Colors.ERROR)
            return
        await self.app.snack_bar.show_snack_bar(
            f"重试完成：成功 {result.get('success_count') or 0}，失败 {result.get('failed_count') or 0}",
            bgcolor=ft.Colors.PRIMARY if int(result.get("failed_count") or 0) == 0 else ft.Colors.ERROR,
        )

    async def retry_all_failed_tasks(self) -> None:
        records = self._all_records(500)
        retryable = [record for record in records if task_status_key(record.get("status_key") or record.get("status")) == OperationStatus.FAILED.value and record.get("retry_action")]
        if not retryable:
            await self.app.snack_bar.show_snack_bar("没有可重试的失败任务", bgcolor=ft.Colors.PRIMARY)
            return
        result = await self.task_service.retry_all_failed()
        await self.load()
        failed_tasks = int(result.get("failed_tasks") or 0)
        await self.app.snack_bar.show_snack_bar(
            f"失败任务重试完成：成功任务 {result.get('success_tasks') or 0} 个，仍失败 {failed_tasks} 个",
            bgcolor=ft.Colors.PRIMARY if failed_tasks == 0 else ft.Colors.ERROR,
            duration=6000,
            show_close_icon=True,
        )

    async def _retry_content_download_items(self, payload: dict[str, Any], notify: bool = True) -> dict[str, Any]:
        result = await self.task_service.retry_content_download_items(payload)
        await self.load()
        if notify:
            if result.get("success"):
                await self.app.snack_bar.show_snack_bar(
                    f"重试完成：成功 {result.get('success_count') or 0}，失败 {result.get('failed_count') or 0}",
                    bgcolor=ft.Colors.PRIMARY,
                    duration=6000,
                    show_close_icon=True,
                )
            else:
                await self.app.snack_bar.show_snack_bar(
                    str(result.get("reason") or "重试失败"),
                    bgcolor=ft.Colors.ERROR,
                    duration=6000,
                    show_close_icon=True,
                )
        return result

    @staticmethod
    def _payload_retry_item_ids(payload: dict[str, Any]) -> list[str]:
        return TaskCenterFacadeService.payload_retry_item_ids(payload)

    @staticmethod
    def _retry_failed_ids(record: dict[str, Any]) -> list[str]:
        return TaskCenterFacadeService.retry_failed_ids(record)


    async def pause_batch_job(self, job_id: str) -> None:
        result = await self.task_service.pause_batch_job(job_id)
        await self.load()
        await self.app.snack_bar.show_snack_bar(str(result.get("reason") or "批量任务已暂停"), bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR)

    async def resume_batch_job(self, job_id: str) -> None:
        result = await self.task_service.resume_batch_job(job_id)
        await self.load()
        await self.app.snack_bar.show_snack_bar(str(result.get("reason") or "批量任务已继续"), bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR, duration=6000, show_close_icon=True)

    async def cancel_batch_job(self, job_id: str) -> None:
        result = await self.task_service.cancel_batch_job(job_id)
        await self.load()
        await self.app.snack_bar.show_snack_bar(str(result.get("reason") or "批量任务已取消"), bgcolor=ft.Colors.PRIMARY if result.get("success") else ft.Colors.ERROR)

    def show_batch_job_detail(self, job_id: str) -> None:
        detail = self.task_service.batch_job_detail(job_id)
        if not detail:
            return
        lines = [
            f"标题：{detail.get('title') or '-'}",
            f"状态：{detail.get('status') or '-'}",
            f"进度：完成 {detail.get('completed', 0)} / 失败 {detail.get('failed', 0)} / 跳过 {detail.get('skipped', 0)} / 剩余 {detail.get('remaining', 0)} / 总数 {detail.get('total', 0)}",
            f"批次键：{detail.get('batch_key') or '-'}",
        ]
        failed_ids = [str(item) for item in detail.get("failed_ids", []) if item]
        remaining_ids = [str(item) for item in detail.get("remaining_ids", []) if item]
        if failed_ids:
            lines.append("失败作品ID：")
            lines.extend(f"  {item}" for item in failed_ids[:200])
        if remaining_ids:
            lines.append("剩余作品ID：")
            lines.extend(f"  {item}" for item in remaining_ids[:200])
        reasons = detail.get("failure_reasons") if isinstance(detail.get("failure_reasons"), dict) else {}
        if reasons:
            summary = self.task_service.failure_category_summary_from_reasons(reasons)
            text = self.task_service.failure_category_text(summary)
            if text:
                lines.append(f"失败归类汇总：{text}")
            lines.append("失败原因：")
            lines.append(json.dumps(reasons, ensure_ascii=False, indent=2))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("批量任务详情"),
            content=ft.Column(controls=[ft.Text("\n".join(lines), selectable=True, size=12)], tight=True, width=760, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog))],
        )
        self.show_dialog(dialog)

    def show_task_detail(self, record: dict[str, Any]) -> None:
        payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
        failure = classify_failure(str(record.get("detail") or "")) if task_status_key(record.get("status_key") or record.get("status")) == OperationStatus.FAILED.value else {}
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
        related_summary = self.task_service.related_download_summary(record)
        related_downloads = self.task_service.related_download_records(record, limit=30)
        if related_downloads:
            status_counts = related_summary.get("status_counts") if isinstance(related_summary.get("status_counts"), dict) else {}
            status_text = "，".join(f"{name} {count}" for name, count in sorted(status_counts.items()))
            lines.append(f"关联下载汇总：总计 {related_summary.get('total') or 0}，可恢复 {related_summary.get('recoverable') or 0}，文件缺失 {related_summary.get('missing_file') or 0}" + (f"，状态：{status_text}" if status_text else ""))
            failure_text = self.task_service.failure_category_text(related_summary.get("failure_categories") or {})
            if failure_text:
                lines.append(f"关联下载失败归类：{failure_text}")
            lines.append("关联下载记录：")
            for item in related_downloads[:30]:
                lines.append(f"  {item.get('status') or '-'} | {item.get('label') or item.get('download_id') or '-'} | {item.get('save_path') or '-'}")
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
        key = task_status_key(status)
        if key == OperationStatus.COMPLETED.value:
            return ft.Colors.GREEN
        if key == OperationStatus.FAILED.value:
            return ft.Colors.ERROR
        if key == OperationStatus.CANCELLED.value:
            return ft.Colors.ON_SURFACE_VARIANT
        if key == OperationStatus.RUNNING.value:
            return ft.Colors.PRIMARY
        return ft.Colors.ON_SURFACE_VARIANT

    async def _await_coro(self, coro) -> None:
        await coro

    def run_async(self, coro) -> None:
        self.page.run_task(self._await_coro, coro)
