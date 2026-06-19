from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import flet as ft


@dataclass(slots=True)
class BatchImportControls:
    text_field: ft.TextField
    default_group: ft.TextField
    start_switch: ft.Switch
    notify_switch: ft.Switch
    policy_dropdown: ft.Dropdown
    dialog: ft.AlertDialog


def build_work_bulk_action_rows(view, account: Any, has_selected: bool) -> list[ft.Control]:
    return [
        ft.Row(
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
        ),
        ft.Row(
            controls=[
                ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="下载全部", disabled=view.download_in_progress, on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="all")), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.NEW_RELEASES, tooltip="只下载新作品", disabled=view.download_in_progress, on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="new")), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.IMAGE, tooltip="只下载图集", disabled=view.download_in_progress, on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="gallery")), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.SMART_DISPLAY, tooltip="只下载视频", disabled=view.download_in_progress, on_click=lambda e: view.run_async(view.download_all(view.selected_account_id or "", filter_mode="video")), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.CLEAR, tooltip="取消选择", disabled=not has_selected, on_click=lambda e: view.run_async(view.clear_selected_works()), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.DOWNLOAD_FOR_OFFLINE, tooltip="批量下载选中", disabled=not has_selected or view.download_in_progress, on_click=lambda e: view.run_async(view.download_selected_works()), icon_color=ft.Colors.PRIMARY),
                ft.IconButton(icon=ft.Icons.STOP_CIRCLE, tooltip="停止下载", disabled=not view.download_in_progress or view.download_stop_requested, on_click=lambda e: view.run_async(view.stop_downloads()), icon_color=ft.Colors.PRIMARY),
            ],
            spacing=6,
            wrap=True,
        ),
    ]


def build_batch_import_dialog(on_submit: Callable[[BatchImportControls], Any], on_close: Callable[..., Any]) -> BatchImportControls:
    text_field = ft.TextField(
        label="批量账号",
        hint_text="一行一个主页链接，也支持：主页链接,备注,分组",
        multiline=True,
        min_lines=8,
        max_lines=14,
        width=680,
    )
    default_group = ft.TextField(label="默认分组", width=320, hint_text="可选")
    start_switch = ft.Switch(label="导入后立即开始监控", value=True)
    notify_switch = ft.Switch(label="发现新作品时通知", value=True)
    policy_dropdown = ft.Dropdown(
        label="新增作品自动下载",
        value="none",
        width=300,
        options=[
            ft.dropdown.Option("none", "不自动下载"),
            ft.dropdown.Option("video", "只下载视频"),
            ft.dropdown.Option("gallery", "只下载图集"),
            ft.dropdown.Option("all", "自动下载全部"),
        ],
    )
    controls = BatchImportControls(
        text_field=text_field,
        default_group=default_group,
        start_switch=start_switch,
        notify_switch=notify_switch,
        policy_dropdown=policy_dropdown,
        dialog=None,  # type: ignore[arg-type]
    )
    dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("批量导入监控账号"),
        content=ft.Column(
            controls=[
                text_field,
                ft.Row([default_group, policy_dropdown], spacing=10, wrap=True),
                ft.Row([start_switch, notify_switch], spacing=10, wrap=True),
            ],
            tight=True,
            spacing=10,
            width=700,
        ),
        actions=[
            ft.TextButton("取消", icon=ft.Icons.CLOSE, on_click=on_close),
            ft.FilledButton("导入", icon=ft.Icons.ADD, on_click=lambda e: on_submit(controls)),
        ],
    )
    controls.dialog = dialog
    return controls
