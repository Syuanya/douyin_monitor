from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()

from .douyin_content_download_controller import DouyinContentDownloadController
from . import douyin_content_state as content_state


class DouyinContentPreviewController:
    """Preview/detail adapter for content monitor works."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        try:
            from ..components.business.image_preview_dialog import ImagePreviewDialog

            self.image_preview = ImagePreviewDialog(owner.app, "作品图集")
        except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
            self.image_preview = None

    @staticmethod
    def format_size(size: int | float | str) -> str:
        try:
            value = float(size or 0)
        except (TypeError, ValueError):
            value = 0.0
        if value <= 0:
            return "-"
        units = ["B", "KB", "MB", "GB", "TB"]
        unit_index = 0
        while value >= 1024 and unit_index < len(units) - 1:
            value /= 1024
            unit_index += 1
        return f"{value:.1f} {units[unit_index]}"

    async def open_download_location(self, path: str) -> None:
        owner = self.owner
        target = DouyinContentDownloadController.download_location(path)
        await owner.open_path_or_url(target, success=f"已打开：{target}", failed_prefix="打开下载位置失败")

    async def open_item_download_location(self, item_id: str, account_id: str | None = None) -> None:
        owner = self.owner
        target_account_id = account_id or owner.selected_account_id
        if not target_account_id:
            await owner.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        info = owner.manager.local_item_path_info(target_account_id, item_id)
        if not info.get("success"):
            await owner.app.snack_bar.show_snack_bar(info.get("reason") or "未找到下载文件", bgcolor=ft.Colors.ERROR)
            return
        path = info.get("folder") or info.get("path")
        await owner.open_path_or_url(str(path or ""), success="已打开下载位置")

    async def browse_video(self, item_id: str) -> None:
        owner = self.owner
        account_id = owner.selected_account_id
        if not account_id:
            await owner.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        await owner.set_loading(True)
        try:
            result = await owner.manager.resolve_item_preview(account_id, item_id)
            if not result.get("success"):
                await owner.app.snack_bar.show_snack_bar(
                    result.get("reason") or "视频浏览失败",
                    bgcolor=ft.Colors.ERROR,
                    duration=5000,
                    show_close_icon=True,
                )
                return
            source_url = result.get("url") or ""
            if not source_url:
                await owner.app.snack_bar.show_snack_bar("未获取到视频浏览地址", bgcolor=ft.Colors.ERROR)
                return
            from ..components.business.video_player import VideoPlayer

            await VideoPlayer(owner.app).preview_video(
                source_url,
                is_file_path=bool(result.get("is_file_path")),
                room_url=result.get("share_url") or source_url,
                copy_source_url=result.get("copy_source_url") or source_url,
            )
        finally:
            await owner.set_loading(False)

    async def preview_item_images(self, item_id: str, selected_index: int = 0) -> None:
        owner = self.owner
        account_id = owner.selected_account_id
        if not account_id:
            await owner.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        await owner.set_loading(True)
        try:
            result = await owner.manager.resolve_item_image_preview(account_id, item_id)
            if not result.get("success"):
                await owner.app.snack_bar.show_snack_bar(
                    result.get("reason") or "图片预览失败",
                    bgcolor=ft.Colors.ERROR,
                    duration=5000,
                    show_close_icon=True,
                )
                return
            urls = [str(url) for url in result.get("urls", []) if url]
            if not urls:
                await owner.app.snack_bar.show_snack_bar("未获取到图片预览地址", bgcolor=ft.Colors.ERROR)
                return
            index = max(0, min(selected_index, len(urls) - 1))
            self.show_image_preview_dialog(
                title=str(result.get("title") or item_id),
                urls=urls,
                selected_index=index,
            )
        finally:
            await owner.set_loading(False)

    def show_image_preview_dialog(self, title: str, urls: list[str], selected_index: int) -> None:
        if self.image_preview is None:
            raise RuntimeError("图片预览组件不可用")
        self.image_preview.show(urls, [title for _ in urls], selected_index)

    async def show_work_detail(self, item_id: str) -> None:
        owner = self.owner
        account = owner.manager.find_account(owner.selected_account_id) if owner.selected_account_id else None
        if account is None:
            await owner.app.snack_bar.show_snack_bar("请先选择一个博主", bgcolor=ft.Colors.ERROR)
            return
        item = next((work for work in account.items if work.item_id == item_id), None)
        if item is None:
            await owner.app.snack_bar.show_snack_bar("作品不存在", bgcolor=ft.Colors.ERROR)
            return
        is_gallery = content_state.is_gallery_item(item)

        async def close_dialog(_=None):
            dialog.open = False
            owner.app.dialog_area.update()

        info = [
            f"标题：{item.title or '-'}",
            f"作品 ID：{item.item_id}",
            f"类型：{'图集' if is_gallery else '视频'}",
            f"状态：{item.status or '-'}",
            f"发布时间：{item.publish_time or '-'}",
            f"首次发现：{item.first_seen_time or '-'}",
            f"最近发现：{item.last_seen_time or '-'}",
            f"最后尝试下载：{getattr(item, 'last_attempt_at', '') or '-'}",
            f"下载完成时间：{getattr(item, 'downloaded_at', '') or '-'}",
            f"下载路径：{getattr(item, 'download_path', '') or '-'}",
            f"文件大小：{self.format_size(getattr(item, 'file_size', 0) or 0)}",
            f"失败原因：{getattr(item, 'failure_reason', '') or '-'}",
            f"错误分类：{getattr(item, 'failure_category', '') or '-'}",
            f"处理建议：{getattr(item, 'failure_next_step', '') or '-'}",
            f"重试次数：{getattr(item, 'retry_count', 0) or 0}",
            f"图片数量：{len(item.image_urls or [])}",
            f"作品链接：{item.share_url or '-'}",
        ]
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("作品详情"),
            content=ft.Column(
                controls=[ft.Text("\n".join(info), selectable=True, size=12)],
                tight=True,
                width=620,
            ),
            actions=[
                ft.TextButton("复制链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=item.share_url: owner.run_async(owner.copy_text(url))),
                ft.TextButton(
                    "预览",
                    icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE,
                    on_click=lambda e, work_id=item.item_id: owner.run_async(owner.preview_item_images(work_id) if is_gallery else owner.browse_video(work_id)),
                ),
                ft.TextButton("下载", icon=ft.Icons.DOWNLOAD, on_click=lambda e, work_id=item.item_id: owner.run_async(owner.download_one(work_id))),
                ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog),
            ],
        )
        dialog.open = True
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()
