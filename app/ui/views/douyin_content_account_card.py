from __future__ import annotations

import flet as ft

from ..components.common.safe_icons import icon


def build_account_card(view, account):
    """Build an account card for the Douyin content page.

    The card still receives the page/view object for callbacks, but the visual
    composition now lives outside the monolithic page class.
    """

    status_meta = view.account_status_meta(account)
    status_color = status_meta["color"]
    avatar_control = ft.Container(
        width=36,
        height=36,
        border_radius=18,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=(
            ft.Image(src=account.avatar_url, width=36, height=36, fit=ft.BoxFit.COVER)
            if account.avatar_url
            else ft.Icon(ft.Icons.PERSON, color=ft.Colors.PRIMARY)
        ),
        on_click=lambda e, account_id=account.account_id: view.run_async(view.open_account_works(account_id)),
        tooltip=view._.get("select", "查看历史"),
    )
    account_checkbox = ft.Checkbox(
        value=account.account_id in view.selected_account_ids,
        visible=view.account_select_mode,
        on_change=lambda e, account_id=account.account_id: view.run_async(view.toggle_account_selected(account_id, bool(e.control.value))),
    )

    info_lines = [
        f"{view._.get('douyin_nickname', '抖音昵称')}：{account.douyin_nickname or '-'}",
        f"分组：{account.group_name or '未分组'}",
        f"自动下载：{view._auto_download_policy_label(account.auto_download_policy)}",
        (
            f"策略：间隔 {getattr(account, 'monitor_interval_minutes', 0) or '全局'} 分钟"
            f" / 失败暂停 {getattr(account, 'auto_pause_failures', 0) or '关闭'}"
            f" / 保留 {getattr(account, 'keep_recent_count', 0) or '不限'}"
        ),
        f"{view._.get('status', '状态')}：{account.status}",
        f"{view._.get('last_check', '最近检测')}：{account.last_check_time or '-'}",
        f"{view._.get('last_success', '最近成功')}：{account.last_success_time or '-'}",
        (
            f"{view._.get('works', '作品')}：{len(account.items)}"
            f"{f' / 资料总数 {account.aweme_count}' if getattr(account, 'aweme_count', -1) >= 0 else ''}"
            f" / {view._.get('new_total', '累计新增')} {account.total_new_count}"
        ),
    ]
    if account.last_error:
        info_lines.append(f"原因：{account.last_error}")
        next_step = view.account_next_step(account)
        if next_step:
            info_lines.append(next_step)

    return ft.Container(
        key=view._account_anchor_key(account.account_id),
        content=ft.Card(
            content=ft.Container(
                padding=12,
                on_click=None,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            controls=[
                                avatar_control,
                                ft.Text(account.display_name or account.douyin_nickname or "抖音用户", weight=ft.FontWeight.BOLD, size=15, expand=True),
                                ft.Container(
                                    content=ft.Row(
                                        [
                                            ft.Icon(status_meta["icon"], size=14, color=ft.Colors.WHITE),
                                            ft.Text(status_meta["label"], size=12, color=ft.Colors.WHITE),
                                        ],
                                        spacing=4,
                                        tight=True,
                                    ),
                                    bgcolor=status_color,
                                    border_radius=12,
                                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                ),
                                account_checkbox,
                            ],
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        ft.Text(account.homepage_url, size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                        ft.Text("\n".join(info_lines), size=12, selectable=True),
                        ft.Row(
                            controls=[
                                ft.TextButton(view._.get("select", "查看历史"), icon=ft.Icons.HISTORY, on_click=lambda e, account_id=account.account_id: view.run_async(view.open_account_works(account_id))),
                                ft.TextButton(view._.get("check_now", "检测一次"), icon=ft.Icons.REFRESH, on_click=lambda e, account_id=account.account_id: view.run_async(view.check_one(account_id))),
                                ft.TextButton(view._.get("sync_works", "同步作品"), icon=ft.Icons.CLOUD_SYNC, on_click=lambda e, account_id=account.account_id: view.run_async(view.sync_works(account_id))),
                                ft.TextButton("编辑", icon=ft.Icons.SETTINGS, on_click=lambda e, account_id=account.account_id: view.run_async(view.show_edit_account_dialog(account_id))),
                                ft.IconButton(icon=icon("INSIGHTS", "HISTORY"), tooltip="查看监控历史", on_click=lambda e, account_id=account.account_id: view.run_async(view.show_monitor_history_dialog(account_id)), icon_color=ft.Colors.PRIMARY),
                                ft.TextButton(
                                    view._.get("start", "开始监控") if not account.monitor_enabled else view._.get("stop", "停止监控"),
                                    icon=ft.Icons.PLAY_ARROW if not account.monitor_enabled else ft.Icons.STOP,
                                    on_click=lambda e, account_id=account.account_id, enabled=account.monitor_enabled: view.run_async(view.toggle_monitor(account_id, enabled)),
                                ),
                                ft.TextButton(view._.get("open", "打开主页"), icon=ft.Icons.OPEN_IN_BROWSER, on_click=lambda e, url=account.homepage_url: view.run_async(view.open_url(url))),
                                ft.TextButton(view._.get("copy", "复制链接"), icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=account.homepage_url: view.run_async(view.copy_text(url))),
                                ft.TextButton(view._.get("delete", "删除"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e, account_id=account.account_id: view.run_async(view.delete_account(account_id))),
                            ],
                            wrap=True,
                            spacing=4,
                        ),
                    ],
                ),
            ),
        ),
    )
