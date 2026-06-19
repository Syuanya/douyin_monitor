from __future__ import annotations

import flet as ft


def build_work_filter_bar(view) -> ft.Row:
    return ft.Row(
        controls=[
            *view._work_filter_buttons(),
            ft.IconButton(
                icon=ft.Icons.REPLAY,
                tooltip="重试失败下载",
                disabled=view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="failed")),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.ERROR_OUTLINE,
                tooltip="查看下载失败详情",
                disabled=not view.download_failure_reasons,
                on_click=lambda e: view.run_async(view.show_download_failures_dialog()),
                icon_color=ft.Colors.ERROR,
            ),
        ],
        spacing=6,
        wrap=True,
    )


def build_bulk_download_bar(view, has_selected: bool) -> ft.Row:
    return ft.Row(
        controls=[
            ft.IconButton(
                icon=ft.Icons.DOWNLOAD,
                tooltip="下载全部",
                disabled=view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="all")),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.NEW_RELEASES,
                tooltip="只下载新作品",
                disabled=view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="new")),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.IMAGE,
                tooltip="只下载图集",
                disabled=view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="gallery")),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.SMART_DISPLAY,
                tooltip="只下载视频",
                disabled=view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="video")),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.CLEAR,
                tooltip="取消选择",
                disabled=not has_selected,
                on_click=lambda e: view.run_async(view.clear_selected_works()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.DOWNLOAD_FOR_OFFLINE,
                tooltip="批量下载选中",
                disabled=not has_selected or view.download_in_progress,
                on_click=lambda e: view.run_async(view.download_selected_works()),
                icon_color=ft.Colors.PRIMARY,
            ),
            ft.IconButton(
                icon=ft.Icons.STOP_CIRCLE,
                tooltip="停止下载",
                disabled=not view.download_in_progress or view.download_stop_requested,
                on_click=lambda e: view.run_async(view.stop_downloads()),
                icon_color=ft.Colors.PRIMARY,
            ),
        ],
        spacing=6,
        wrap=True,
    )


def build_download_recovery_bar(view, recoverable_count: int) -> ft.Container:
    return ft.Container(
        visible=recoverable_count > 0,
        padding=ft.Padding.symmetric(horizontal=8, vertical=6),
        border=ft.Border.all(1, ft.Colors.ERROR_CONTAINER),
        border_radius=8,
        content=ft.Row(
            controls=[
                ft.Icon(ft.Icons.RESTORE, color=ft.Colors.ERROR),
                ft.Text(f"发现 {recoverable_count} 个可恢复下载任务", size=12, expand=True),
                ft.TextButton(
                    "查看",
                    icon=ft.Icons.LIST_ALT,
                    on_click=lambda e: view.run_async(view.show_download_recovery_dialog()),
                ),
                ft.FilledTonalButton(
                    "恢复",
                    icon=ft.Icons.REPLAY,
                    disabled=view.download_in_progress,
                    on_click=lambda e: view.run_async(view.recover_downloads_on_click()),
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )
