from __future__ import annotations

import csv
import os
from datetime import datetime
from typing import Any

import flet as ft

from ..base_page import PageBase


class DownloadHistoryPage(PageBase):
    """Conservative download history page.

    This page intentionally avoids TextField, expanding placeholders and
    decorated empty containers. Some Flet builds render failed/empty complex
    controls as a large grey block, so the empty state is plain text only.
    """

    def __init__(self, app):
        super().__init__(app)
        self.page_name = "download_history"
        self.status_filter = "all"
        self.records_area: ft.Column | None = None

    async def load(self) -> None:
        self.content_area.scroll = ft.ScrollMode.AUTO
        self.records_area = ft.Column(controls=[], spacing=8, expand=False)
        self.content_area.controls.clear()
        self.content_area.controls.extend(
            [
                self._title_row(),
                self._summary_text(),
                self._action_row(),
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
                    tooltip="查看下载历史、恢复中断下载、导出或清理本地下载记录。",
                    icon_color=ft.Colors.ON_SURFACE_VARIANT,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _summary_text(self) -> ft.Control:
        counts = self._counts()
        return ft.Text(
            f"全部 {counts['total']} / 可恢复 {counts['recoverable']} / 失败 {counts['failed']} / 完成 {counts['completed']}",
            size=13,
            color=ft.Colors.ON_SURFACE_VARIANT,
        )

    def _action_row(self) -> ft.Control:
        counts = self._counts()
        return ft.Row(
            controls=[
                ft.TextButton("恢复全部", icon=ft.Icons.RESTORE, disabled=counts["recoverable"] == 0, on_click=lambda e: self.run_async(self.recover_all())),
                ft.TextButton("导出 CSV", icon=ft.Icons.DOWNLOAD, disabled=counts["total"] == 0, on_click=lambda e: self.run_async(self.export_csv())),
                ft.TextButton("清理完成", icon=ft.Icons.CLEANING_SERVICES, disabled=counts["completed"] == 0, on_click=lambda e: self.run_async(self.clear_completed())),
                ft.TextButton("清理失败/取消", icon=ft.Icons.DELETE_SWEEP, disabled=counts["failed_cancelled"] == 0, on_click=lambda e: self.run_async(self.clear_failed_cancelled())),
                ft.TextButton("刷新", icon=ft.Icons.REFRESH, on_click=lambda e: self.run_async(self.load())),
            ],
            spacing=6,
            wrap=True,
        )

    def _filter_row(self) -> ft.Control:
        return ft.Row(
            controls=[
                ft.Text("状态：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                self._filter_button("全部", "all"),
                self._filter_button("可恢复", "recoverable"),
                self._filter_button("运行中", "running"),
                self._filter_button("失败", "failed"),
                self._filter_button("完成", "completed"),
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
        records = self._records(limit=200)
        self.records_area.controls.clear()
        if not records:
            self.records_area.controls.append(
                ft.Text("暂无匹配下载记录。下载任务产生后会在这里显示。", color=ft.Colors.ON_SURFACE_VARIANT)
            )
        else:
            for record in records:
                self.records_area.controls.append(self._record_view(record))
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
        lines = [
            ft.Text(f"{title}  [{self._status_label(status)}]", weight=ft.FontWeight.BOLD, selectable=True),
            ft.Text(f"类型：{record.get('kind') or '-'}；进度：{progress}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
            ft.Text(f"路径：{save_path or '-'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
        ]
        if error:
            lines.append(ft.Text(f"错误：{error}", size=12, color=ft.Colors.ERROR, selectable=True))
        actions: list[ft.Control] = []
        if status in {"recoverable", "failed", "cancelled", "pending", "running"}:
            actions.append(ft.TextButton("恢复", icon=ft.Icons.RESTORE, on_click=lambda e, item=record: self.run_async(self.recover_one(item))))
        if save_path:
            actions.append(ft.TextButton("打开位置", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e, path=save_path: self.run_async(self.open_location(path))))
        actions.append(ft.TextButton("详情", icon=ft.Icons.INFO_OUTLINE, on_click=lambda e, item=record: self.show_detail(item)))
        return ft.Column(controls=[*lines, ft.Row(actions, spacing=4, wrap=True), ft.Divider(height=8)], spacing=3)

    def _records(self, limit: int = 200) -> list[dict[str, Any]]:
        store = getattr(self.app.services, "sqlite_store", None)
        if store is None:
            return []
        return store.load_download_records(statuses=self._selected_statuses(), limit=limit)

    def _counts(self) -> dict[str, int]:
        store = getattr(self.app.services, "sqlite_store", None)
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if store is None:
            return {"total": 0, "recoverable": 0, "failed": 0, "completed": 0, "failed_cancelled": 0}
        failed = store.download_record_count(["failed"])
        cancelled = store.download_record_count(["cancelled"])
        return {
            "total": store.download_record_count(),
            "recoverable": len(recovery.recoverable(limit=500)) if recovery is not None else 0,
            "failed": failed,
            "completed": store.download_record_count(["completed"]),
            "failed_cancelled": failed + cancelled,
        }

    async def set_status_filter(self, mode: str) -> None:
        self.status_filter = str(mode or "all")
        await self.load()

    async def recover_one(self, record: dict[str, Any]) -> None:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if recovery is None:
            await self.app.snack_bar.show_snack_bar("下载恢复服务不可用")
            return
        ok = await recovery.recover_one(record, headers=self._headers(), proxy=self._proxy_url(), resume_enabled=self._resume_enabled())
        await self.load()
        await self.app.snack_bar.show_snack_bar("下载恢复成功" if ok else "下载恢复失败")

    async def recover_all(self) -> None:
        recovery = getattr(self.app.services, "download_recovery_service", None)
        if recovery is None:
            await self.app.snack_bar.show_snack_bar("下载恢复服务不可用")
            return
        result = await recovery.recover_all(headers=self._headers(), proxy=self._proxy_url(), resume_enabled=self._resume_enabled())
        await self.load()
        failed = int(result.get("failed_count") or 0)
        await self.app.snack_bar.show_snack_bar(
            f"恢复完成：总计 {result.get('total') or 0}，成功 {result.get('success_count') or 0}，失败 {failed}",
            duration=6000,
            show_close_icon=True,
        )

    async def clear_completed(self) -> None:
        store = getattr(self.app.services, "sqlite_store", None)
        deleted = store.delete_download_records(statuses=["completed"]) if store is not None else 0
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清理完成记录 {deleted} 条")

    async def clear_failed_cancelled(self) -> None:
        store = getattr(self.app.services, "sqlite_store", None)
        deleted = store.delete_download_records(statuses=["failed", "cancelled"]) if store is not None else 0
        await self.load()
        await self.app.snack_bar.show_snack_bar(f"已清理失败/取消记录 {deleted} 条")

    async def export_csv(self) -> None:
        records = self._records(limit=1000)
        if not records:
            await self.app.snack_bar.show_snack_bar("暂无下载记录可导出")
            return
        export_dir = os.path.join(self.app.run_path, "downloads", "download_history_exports")
        os.makedirs(export_dir, exist_ok=True)
        path = os.path.join(export_dir, f"download_records_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv")
        with open(path, "w", encoding="utf-8-sig", newline="") as file:
            writer = csv.writer(file)
            writer.writerow(["ID", "类型", "标题", "状态", "已下载", "总大小", "错误", "URL", "保存路径", "创建时间", "更新时间", "完成时间"])
            for record in records:
                writer.writerow(
                    [
                        record.get("download_id") or "",
                        record.get("kind") or "",
                        record.get("label") or "",
                        record.get("status") or "",
                        record.get("bytes_downloaded") or 0,
                        record.get("total_bytes") or 0,
                        record.get("error") or "",
                        record.get("url") or "",
                        record.get("save_path") or "",
                        record.get("created_at") or "",
                        record.get("updated_at") or "",
                        record.get("finished_at") or "",
                    ]
                )
        await self.app.snack_bar.show_snack_bar(f"已导出：{path}", duration=6000, show_close_icon=True)

    async def open_location(self, save_path: str) -> None:
        target = os.path.dirname(save_path) if save_path and not os.path.isdir(save_path) else save_path
        await self.open_path_or_url(target, success="已打开下载位置")

    def show_detail(self, record: dict[str, Any]) -> None:
        text = "\n".join(
            [
                f"ID：{record.get('download_id') or '-'}",
                f"状态：{record.get('status') or '-'}",
                f"类型：{record.get('kind') or '-'}",
                f"标题：{record.get('label') or '-'}",
                f"保存路径：{record.get('save_path') or '-'}",
                f"URL：{record.get('url') or '-'}",
                f"错误：{record.get('error') or '-'}",
            ]
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("下载记录详情"),
            content=ft.Text(text, selectable=True),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=lambda e: self.close_dialog(dialog))],
        )
        self.show_dialog(dialog)

    def _selected_statuses(self) -> list[str] | None:
        return {
            "recoverable": ["pending", "running", "recoverable", "failed", "cancelled"],
            "running": ["running", "pending"],
            "failed": ["failed"],
            "completed": ["completed"],
            "cancelled": ["cancelled"],
        }.get(str(self.status_filter or "all"))

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
        downloaded = int(record.get("bytes_downloaded") or 0)
        total = int(record.get("total_bytes") or 0)
        if total > 0:
            return f"{_bytes_text(downloaded)}/{_bytes_text(total)}"
        return _bytes_text(downloaded)

    @staticmethod
    def _status_label(status: str) -> str:
        return {
            "all": "全部",
            "completed": "完成",
            "running": "运行中",
            "pending": "等待中",
            "recoverable": "可恢复",
            "failed": "失败",
            "cancelled": "已取消",
        }.get(str(status or ""), str(status or "-"))


def _bytes_text(value: int) -> str:
    size = float(value or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} GB"
