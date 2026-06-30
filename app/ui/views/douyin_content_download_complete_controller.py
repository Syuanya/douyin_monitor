from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"
        ON_SURFACE_VARIANT = "on_surface_variant"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()


class DouyinContentDownloadCompleteController:
    """Owns the small download-complete dialog and its actions."""

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    @staticmethod
    def file_count_text(files: list[str] | None) -> str:
        return f"\n文件数：{len(files)}" if files else ""

    def show_dialog(self, path: str, reason: str = "下载完成", files: list[str] | None = None) -> None:
        owner = self.owner
        target_path = str(path or "").strip()
        file_count_text = self.file_count_text(files)
        dialog_ref: dict[str, ft.AlertDialog | None] = {"dialog": None}

        def close_dialog(_=None):
            dialog = dialog_ref.get("dialog")
            if dialog is not None:
                dialog.open = False
            owner.app.dialog_area.update()

        async def copy_path(_=None):
            close_dialog()
            await owner.copy_text(target_path)

        async def open_folder(_=None):
            close_dialog()
            await owner.open_download_location(target_path)

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
                ft.TextButton("复制路径", icon=ft.Icons.CONTENT_COPY, on_click=lambda e: owner.run_async(copy_path())),
                ft.FilledButton("打开文件夹", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e: owner.run_async(open_folder())),
            ],
        )
        dialog_ref["dialog"] = dialog
        dialog.open = True
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()
