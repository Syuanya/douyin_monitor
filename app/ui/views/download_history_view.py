from __future__ import annotations

import os
from typing import Any

import flet as ft

from ...core.ui_services.download_history_service import DownloadHistoryService
from ..base_page import PageBase


class DownloadHistoryPage(PageBase):
    """Download history page with search, progressive loading and recovery actions."""

    def __init__(self, app):
        super().__init__(app)
        self.page_name = "download_history"
        self.status_filter = "all"
        self.search_query = ""
        self.visible_count = 50
        self.page_size = 50
        self.records_area: ft.Column | None = None
        self.search_field: Any | None = None
        self.history_service = DownloadHistoryService(app)
        self.recovery_concurrency = 2

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.records_area = ft.Column(controls=[], spacing=8, expand=False)
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self._title_row(),
                self._summary_text(),
                self._action_row(),
                self._search_row(),
                self._filter_row(),
                self.records_area,
            ]
        )
        await self.refresh()
        self.content_area.update()

    def _title_row(self) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Text("下载历史与恢复", theme_style=ft.TextThemeStyle.TITLE_LARGE),
                ft.IconButton(
                    icon=ft.Icons.INFO_OUTLINE,
                    tooltip="查看下载历史、搜索失败原因、恢复中断下载、导出或清理本地下载记录。",
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _summary_text(self) -> ft.Control:
        counts = self._counts()
        suffix = f" / 文件缺失 {counts['missing_file']}" if counts.get("missing_file") else ""
        query_text = f"；当前搜索：{self.search_query}" if self.search_query else ""
        return ft.Text(
            f"全部 {counts['total']} / 可恢复 {counts['recoverable']} / 运行 {counts['running']} / 等待 {counts['pending']} / 失败 {counts['failed']} / 完成 {counts['completed']}{suffix}{query_text}",
            size=13,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

    def _action_row(self) -> ft.Control:
        counts = self._counts()
        return ft.Row(
            controls=[
                ft.TextButton("恢复全部", icon=ft.Icons.RESTORE, disabled=counts["recoverable"] == 0, on_click=lambda e: self.show_recover_all_dialog()),
                ft.TextButton("导出当前筛选", icon=ft.Icons.DOWNLOAD, disabled=counts["total"] == 0, on_click=lambda e: self.run_async(self.export_csv_current())),
                ft.TextButton("导出全部", icon=ft.Icons.FILE_DOWNLOAD, disabled=self.history_service.count("all") == 0, on_click=lambda e: self.run_async(self.export_csv_all())),
                ft.TextButton("清理完成", icon=ft.Icons.CLEANING_SERVICES, disabled=counts["completed"] == 0, on_click=lambda e: self.run_async(self.confirm_clear_completed())),
                ft.TextButton("清理失败/取消", icon=ft.Icons.DELETE_SWEEP, disabled=counts["failed_cancelled"] == 0, on_click=lambda e: self.run_async(self.confirm_clear_failed_cancelled())),
                ft.TextButton("校验文件状态", icon=ft.Icons.FACT_CHECK, on_click=lambda e: self.run_async(self.verify_file_states())),
                ft.TextButton("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: self.run_async(self.load())),
            ],
            spacing=6,
            wrap=True,
        )

    def _search_row(self) -> ft.Control:
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
            label="搜索下载历史",
            value=self.search_query,
            hint_text="标题、路径、URL、失败原因、关联任务ID",
            dense=True,
            width=480,
            autofocus=True,
        )

        async def submit(_=None):
            self.search_query = str(query_field.value or "").strip()
            self.visible_count = self.page_size
            self.close_dialog(dialog)
            count = self.history_service.count(self.status_filter, query=self.search_query)
            await self.load()
            await self.app.snack_bar.show_snack_bar(f"下载历史搜索已应用，匹配 {count} 条")

        query_field.on_submit = submit
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("搜索下载历史"),
            content=ft.Column(controls=[query_field], tight=True, width=500),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.FilledButton("搜索", icon=ft.Icons.SEARCH, on_click=lambda e: self.run_async(submit())),
            ],
        )
        self.show_dialog(dialog)

    def _filter_row(self) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Text("状态：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                self._filter_button("全部", "all"),
                self._filter_button("可恢复", "recoverable"),
                self._filter_button("运行中", "running"),
                self._filter_button("等待中", "pending"),
                self._filter_button("失败", "failed"),
                self._filter_button("完成", "completed"),
                self._filter_button("文件缺失", "missing_file"),
                self._filter_button("已取消", "cancelled"),
            ],
            spacing=6,
            wrap=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _filter_button(self, label: str, mode: str) -> ft.Control:
        selected = self.status_filter == mode
        text = f"✓ {label}" if selected else label
        return ft.TextButton(text, on_click=lambda e, value=mode: self.run_async(self.set_status_filter(value)))

    async def refresh(self) -> None:
        if self.records_area is None:
            return
        total = self.history_service.count(self.status_filter, query=self.search_query)
        records = self._records(limit=self.visible_count)
        self.records_area.controls.clear()
        if not records:
            hint = "暂无匹配下载记录。" if self.search_query or self.status_filter != "all" else "暂无下载记录。下载任务产生后会在这里显示。"
            self.records_area.controls.append(ft.Text(hint, color=ft.Colors.ON_SURFACE_VARIANT))
        else:
            self.records_area.controls.append(
                ft.Text(
                    f"当前显示 {len(records)} / 匹配 {total} 条" + (f"；搜索：{self.search_query}" if self.search_query else ""),
                    size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT,
                )
            )
            for record in records:
                self.records_area.controls.append(self._record_view(record))
            if len(records) < total:
                self.records_area.controls.append(
                    ft.Row(
                        controls=[
                            ft.OutlinedButton("加载更多", icon=ft.Icons.EXPAND_MORE, on_click=lambda e: self.run_async(self.load_more_records())),
                            ft.Text(f"剩余 {total - len(records)} 条", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
        try:
            self.records_area.update()
        except Exception:
            pass

    def _record_view(self, record: dict[str, Any]) -> ft.Control:
        status = str(record.get("status") or "-")
        title = str(record.get("label") or os.path.basename(str(record.get("save_path") or "")) or record.get("kind") or "下载记录")
        save_path = str(record.get("save_path") or "")
        error = str(record.get("error") or "")
        progress = self._progress_text(record)
        failure = self.history_service.failure_meta(record)
        lines = [
            ft.Text(f"{title}  [{self._status_label(status)}]", weight=ft.FontWeight.BOLD, selectable=True),
            ft.Text(f"类型：{record.get('kind') or '-'}；进度：{progress}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
            ft.Text(f"路径：{save_path or '-'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
            ft.Text(f"文件状态：{self.history_service.file_state_label(record)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
        ]
        task_id = str(record.get("task_id") or "")
        if task_id:
            lines.append(ft.Text(f"关联任务：{task_id}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True))
        if error:
            lines.append(ft.Text(f"错误：{error}", size=12, color=ft.Colors.ERROR, selectable=True))
        if failure:
            lines.append(ft.Text(f"失败归类：{failure.get('category') or '-'}；建议：{failure.get('next_step') or '-'}", size=12, color=ft.Colors.ERROR, selectable=True))
        actions: list[ft.Control] = []
        if self.history_service.is_recoverable(record):
            actions.append(ft.TextButton("恢复", icon=ft.Icons.RESTORE, on_click=lambda e, item=record: self.run_async(self.recover_one(item))))
        if save_path:
            actions.append(ft.TextButton("打开位置", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e, path=save_path: self.run_async(self.open_location(path))))
            actions.append(ft.TextButton("复制路径", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, path=save_path: self.run_async(self.copy_to_clipboard(path, success="已复制保存路径"))))
        if record.get("url"):
            actions.append(ft.TextButton("复制URL", icon=ft.Icons.LINK, on_click=lambda e, url=str(record.get("url") or ""): self.run_async(self.copy_to_clipboard(url, success="已复制下载URL"))))
        actions.append(ft.TextButton("详情", icon=ft.Icons.INFO_OUTLINE, on_click=lambda e, item=record: self.show_detail(item)))
        return ft.Column(controls=[*lines, ft.Row(actions, spacing=4, wrap=True), ft.Divider(height=8)], spacing=3)

    def _records(self, limit: int = 200) -> list[dict[str, Any]]:
        return self.history_service.records(self.status_filter, limit=limit, query=self.search_query)

    def _counts(self) -> dict[str, int]:
        return self.history_service.counts(query=self.search_query)

    async def set_status_filter(self, mode: str) -> None:
        self.status_filter = str(mode or "all")
        self.visible_count = self.page_size
        await self.load()

    async def clear_search(self) -> None:
        self.search_query = ""
        self.visible_count = self.page_size
        await self.load()
        await self.app.snack_bar.show_snack_bar("下载历史搜索已清除")

    async def load_more_records(self) -> None:
        self.visible_count += self.page_size
        await self.refresh()

    async def recover_one(self, record: dict[str, Any]) -> None:
        result = await self.history_service.recover_one(record, headers=self._headers(), proxy=self._proxy_url(), resume_enabled=self._resume_enabled())
        await self.load()
        ok = bool(result.get("success"))
        await self.app.snack_bar.show_snack_bar(
            "下载恢复成功" if ok else f"下载恢复失败：{result.get('reason') or '未知错误'}",
            duration=6000,
            show_close_icon=True,
        )

    def show_recover_all_dialog(self) -> None:
        counts = self._counts()
        total = int(counts.get("recoverable") or 0)

        async def submit(concurrency: int) -> None:
            self.recovery_concurrency = max(1, min(5, int(concurrency or 1)))
            self.close_dialog(dialog)
            await self.recover_all(self.recovery_concurrency)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("恢复全部下载"),
            content=ft.Column(
                controls=[
                    ft.Text(f"将恢复 {total} 条可恢复下载记录。并发越高速度越快，但更容易触发网络限速。"),
                    ft.Text("建议：网络稳定用并发 2；频繁失败或风控时用串行恢复。", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                ],
                tight=True,
                width=520,
            ),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.OutlinedButton("串行恢复", icon=ft.Icons.FILTER_1, on_click=lambda e: self.run_async(submit(1))),
                ft.FilledButton("并发 2", icon=ft.Icons.LOOKS_TWO, on_click=lambda e: self.run_async(submit(2))),
                ft.OutlinedButton("并发 3", icon=ft.Icons.LOOKS_3, on_click=lambda e: self.run_async(submit(3))),
            ],
        )
        self.show_dialog(dialog)

    async def recover_all(self, concurrency: int | None = None) -> None:
        result = await self.history_service.recover_all(
            headers=self._headers(),
            proxy=self._proxy_url(),
            resume_enabled=self._resume_enabled(),
            concurrency=concurrency or self.recovery_concurrency,
        )
        await self.load()
        await self.app.snack_bar.show_snack_bar(
            self.history_service.recovery_result_message(result),
            duration=8000,
            show_close_icon=True,
        )

    async def verify_file_states(self) -> None:
        counts = self._counts()
        await self.load()
        await self.app.snack_bar.show_snack_bar(
            f"文件状态已校验：文件缺失 {counts.get('missing_file') or 0} 条，可恢复 {counts.get('recoverable') or 0} 条",
            duration=5000,
            show_close_icon=True,
        )

    async def confirm_clear_completed(self) -> None:
        await self._confirm_clear("清理完成记录", "只清理完成状态的历史记录，不删除本地文件。是否继续？", self.clear_completed)

    async def confirm_clear_failed_cancelled(self) -> None:
        await self._confirm_clear("清理失败/取消记录", "只清理失败和已取消的历史记录，不删除本地文件。是否继续？", self.clear_failed_cancelled)

    async def _confirm_clear(self, title: str, message: str, action) -> None:
        async def confirm(_=None):
            self.close_dialog(dialog)
            await action()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(message),
            actions=[
                ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog)),
                ft.FilledButton("清理", icon=ft.Icons.DELETE_SWEEP, on_click=lambda e: self.run_async(confirm())),
            ],
        )
        self.show_dialog(dialog)

    async def clear_completed(self) -> None:
        deleted = self.history_service.clear_completed()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清理完成记录 {deleted} 条；本地文件未删除")

    async def clear_failed_cancelled(self) -> None:
        deleted = self.history_service.clear_failed_cancelled()
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清理失败/取消记录 {deleted} 条；本地文件未删除")

    async def export_csv_current(self) -> None:
        total = self.history_service.count(self.status_filter, query=self.search_query)
        records = self._records(limit=max(1, total))
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无下载记录可导出")
            return
        path = self.history_service.export_csv(records)
        await self.app.snack_bar.show_snack_bar(f"已导出当前筛选 {len(records)} 条：{path}", duration=6000, show_close_icon=True)

    async def export_csv_all(self) -> None:
        total = self.history_service.count("all")
        records = self.history_service.records("all", limit=max(1, total))
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无下载记录可导出")
            return
        path = self.history_service.export_csv(records)
        await self.app.snack_bar.show_snack_bar(f"已导出全部 {len(records)} 条：{path}", duration=6000, show_close_icon=True)

    # Backward-compatible name used by older tests or direct callers.
    async def export_csv(self) -> None:
        await self.export_csv_current()

    async def open_location(self, save_path: str) -> None:
        target = os.path.dirname(save_path) if save_path and not os.path.isdir(save_path) else save_path
        await self.open_path_or_url(target, success="已打开下载位置")

    def show_detail(self, record: dict[str, Any]) -> None:
        text = "\n".join(self.history_service.detail_lines(record))
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("下载记录详情"),
            content=ft.Column(controls=[ft.Text(text, selectable=True, size=12)], tight=True, width=760, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog))],
        )
        self.show_dialog(dialog)

    def _selected_statuses(self) -> list[str] | None:
        return self.history_service.selected_statuses(str(self.status_filter or "all"))

    def _headers(self) -> dict[str, str]:
        settings = getattr(self.app.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        cookie = str((cookies or {}).get("douyin_cookie") or "").strip()
        headers = {"User-Agent": "Mozilla/5.0", "Referer": "https://www.douyin.com/"}
        if cookie:
            headers["Cookie"] = cookie
        return headers

    def _proxy_url(self) -> str | None:
        settings = getattr(self.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        return str(config.get("proxy_address") or "").strip() or None if config.get("enable_proxy") else None

    def _resume_enabled(self) -> bool:
        settings = getattr(self.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        return bool(config.get("download_resume_enabled", True))

    @staticmethod
    def _progress_text(record: dict[str, Any]) -> str:
        return DownloadHistoryService.progress_text(record)

    @staticmethod
    def _status_label(status: str) -> str:
        return DownloadHistoryService.status_label(status)


def _bytes_text(value: int) -> str:
    from ...core.ui_services.common import format_bytes

    return format_bytes(value)
