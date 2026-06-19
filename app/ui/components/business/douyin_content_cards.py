from __future__ import annotations

from typing import Any

import flet as ft

from ..common.safe_icons import icon


def is_gallery_item(item: Any) -> bool:
    return bool(getattr(item, "image_urls", None)) or str(getattr(item, "media_type", "") or "").lower() in {
        "image",
        "images",
        "gallery",
        "note",
    }


def work_status_chip(page: Any, item: Any) -> ft.Container:
    status = str(getattr(item, "status", "") or "")
    if status == "new":
        label, color = page._.get("new_work", "新作品"), ft.Colors.PRIMARY
    elif status == "downloaded":
        label, color = "已下载", ft.Colors.GREEN
    elif status == "download_failed":
        label, color = "下载失败", ft.Colors.ERROR
    else:
        label, color = "", ft.Colors.ON_SURFACE_VARIANT
    return ft.Container(
        content=ft.Text(label, size=11, color=ft.Colors.WHITE),
        bgcolor=color,
        border_radius=10,
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        visible=bool(label),
    )


def create_inbox_item(page: Any, account: Any, item: Any) -> ft.Container:
    title = item.title or item.item_id
    owner = account.display_name or account.douyin_nickname or account.account_id
    gallery = is_gallery_item(item)
    cover = (
        ft.Image(src=item.cover_url, width=260, height=150, fit=ft.BoxFit.COVER)
        if item.cover_url
        else ft.Icon(ft.Icons.IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT)
    )
    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
        border_radius=8,
        content=ft.Column(
            spacing=6,
            tight=True,
            controls=[
                ft.Container(height=150, border_radius=6, clip_behavior=ft.ClipBehavior.HARD_EDGE, content=cover),
                ft.Text(title, size=13, weight=ft.FontWeight.BOLD, selectable=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(f"{owner}\nID: {item.item_id}\n首次发现：{item.first_seen_time or '-'}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True),
                ft.Row(
                    controls=[
                        ft.IconButton(icon=ft.Icons.PERSON_SEARCH, tooltip="查看该账号作品", on_click=lambda e, account_id=account.account_id: page.run_async(page.open_account_works(account_id)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="打开作品", on_click=lambda e, url=item.share_url: page.run_async(page.open_url(url)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.CONTENT_COPY, tooltip="复制作品链接", on_click=lambda e, url=item.share_url: page.run_async(page.copy_text(url)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.IMAGE_SEARCH if gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, tooltip="预览", on_click=lambda e, account_id=account.account_id, item_id=item.item_id, gallery=gallery: page.run_async(page.preview_inbox_item(account_id, item_id, gallery)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="下载", on_click=lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.download_inbox_item(account_id, item_id)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.DONE, tooltip="标记已处理", on_click=lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.mark_item_seen(account_id, item_id)), icon_color=ft.Colors.PRIMARY),
                    ],
                    spacing=3,
                    wrap=True,
                ),
            ],
        ),
    )


def create_account_card(page: Any, account: Any) -> ft.Container:
    status_meta = page.account_status_meta(account)
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
        on_click=lambda e, account_id=account.account_id: page.run_async(page.open_account_works(account_id)),
        tooltip=page._.get("select", "查看历史"),
    )
    account_checkbox = ft.Checkbox(
        value=account.account_id in page.selected_account_ids,
        visible=page.account_select_mode,
        on_change=lambda e, account_id=account.account_id: page.run_async(page.toggle_account_selected(account_id, bool(e.control.value))),
    )
    info_lines = [
        f"{page._.get('douyin_nickname', '抖音昵称')}：{account.douyin_nickname or '-'}",
        f"分组：{account.group_name or '未分组'}",
        f"自动下载：{page._auto_download_policy_label(account.auto_download_policy)}",
        (
            f"策略：间隔 {getattr(account, 'monitor_interval_minutes', 0) or '全局'} 分钟"
            f" / 失败暂停 {getattr(account, 'auto_pause_failures', 0) or '关闭'}"
            f" / 保留 {getattr(account, 'keep_recent_count', 0) or '不限'}"
        ),
        f"{page._.get('status', '状态')}：{account.status}",
        f"{page._.get('last_check', '最近检测')}：{account.last_check_time or '-'}",
        f"{page._.get('last_success', '最近成功')}：{account.last_success_time or '-'}",
        (
            f"{page._.get('works', '作品')}：{len(account.items)}"
            f"{f' / 资料总数 {account.aweme_count}' if getattr(account, 'aweme_count', -1) >= 0 else ''}"
            f" / {page._.get('new_total', '累计新增')} {account.total_new_count}"
        ),
    ]
    if account.last_error:
        info_lines.append(f"原因：{account.last_error}")
        next_step = page.account_next_step(account)
        if next_step:
            info_lines.append(next_step)
    return ft.Container(
        key=page._account_anchor_key(account.account_id),
        content=ft.Card(
            content=ft.Container(
                padding=12,
                content=ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            controls=[
                                avatar_control,
                                ft.Text(account.display_name or account.douyin_nickname or "抖音用户", weight=ft.FontWeight.BOLD, size=15, expand=True),
                                ft.Container(
                                    content=ft.Row([ft.Icon(status_meta["icon"], size=14, color=ft.Colors.WHITE), ft.Text(status_meta["label"], size=12, color=ft.Colors.WHITE)], spacing=4, tight=True),
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
                                ft.TextButton(page._.get("select", "查看历史"), icon=ft.Icons.HISTORY, on_click=lambda e, account_id=account.account_id: page.run_async(page.open_account_works(account_id))),
                                ft.TextButton(page._.get("check_now", "检测一次"), icon=ft.Icons.REFRESH, on_click=lambda e, account_id=account.account_id: page.run_async(page.check_one(account_id))),
                                ft.TextButton(page._.get("sync_works", "同步作品"), icon=ft.Icons.CLOUD_SYNC, on_click=lambda e, account_id=account.account_id: page.run_async(page.sync_works(account_id))),
                                ft.TextButton("编辑", icon=ft.Icons.SETTINGS, on_click=lambda e, account_id=account.account_id: page.run_async(page.show_edit_account_dialog(account_id))),
                                ft.IconButton(icon=icon("INSIGHTS", "HISTORY"), tooltip="查看监控历史", on_click=lambda e, account_id=account.account_id: page.run_async(page.show_monitor_history_dialog(account_id)), icon_color=ft.Colors.PRIMARY),
                                ft.TextButton(page._.get("start", "开始监控") if not account.monitor_enabled else page._.get("stop", "停止监控"), icon=ft.Icons.PLAY_ARROW if not account.monitor_enabled else ft.Icons.STOP, on_click=lambda e, account_id=account.account_id, enabled=account.monitor_enabled: page.run_async(page.toggle_monitor(account_id, enabled))),
                                ft.TextButton(page._.get("open", "打开主页"), icon=ft.Icons.OPEN_IN_BROWSER, on_click=lambda e, url=account.homepage_url: page.run_async(page.open_url(url))),
                                ft.TextButton(page._.get("copy", "复制链接"), icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=account.homepage_url: page.run_async(page.copy_text(url))),
                                ft.TextButton(page._.get("delete", "删除"), icon=ft.Icons.DELETE_OUTLINE, on_click=lambda e, account_id=account.account_id: page.run_async(page.delete_account(account_id))),
                            ],
                            wrap=True,
                            spacing=4,
                        ),
                    ],
                ),
            ),
        ),
    )


def create_history_item(page: Any, item: Any) -> ft.Container:
    title = item.title or item.item_id
    subtitle = f"ID: {item.item_id}\n{page._.get('publish_time', '发布时间')}：{item.publish_time or '-'}\n{page._.get('first_seen', '首次发现')}：{item.first_seen_time or '-'}"
    gallery = is_gallery_item(item)
    cover_control = (
        ft.Container(
            height=150,
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Image(src=item.cover_url, width=260, height=150, fit=ft.BoxFit.COVER),
            on_click=(lambda e, item_id=item.item_id: page.run_async(page.preview_item_images(item_id))) if gallery else (lambda e, url=item.share_url: page.run_async(page.open_url(url))),
            tooltip="预览图片" if gallery else page._.get("open_work", "打开作品"),
        )
        if item.cover_url
        else ft.Container(height=150, border_radius=6, border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT), alignment=ft.Alignment(0, 0), content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT))
    )
    select_checkbox = ft.Checkbox(
        value=item.item_id in page.selected_work_ids,
        width=40,
        height=40,
        on_change=lambda e, item_id=item.item_id: page.run_async(page.toggle_work_selected(item_id, bool(e.control.value))),
    )
    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        content=ft.Stack(
            clip_behavior=ft.ClipBehavior.NONE,
            controls=[
                ft.Column(
                    spacing=6,
                    tight=True,
                    controls=[
                        cover_control,
                        ft.Row(controls=[ft.Text(title, size=13, weight=ft.FontWeight.BOLD, selectable=True, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS), work_status_chip(page, item)], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Text(subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True, max_lines=3),
                        ft.Row(
                            controls=[
                                ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color=ft.Colors.PRIMARY, tooltip=page._.get("open_work", "打开作品"), on_click=lambda e, url=item.share_url: page.run_async(page.open_url(url))),
                                ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_color=ft.Colors.PRIMARY, tooltip=page._.get("copy_work", "复制作品链接"), on_click=lambda e, url=item.share_url: page.run_async(page.copy_text(url))),
                                ft.IconButton(icon=ft.Icons.INFO_OUTLINE, icon_color=ft.Colors.PRIMARY, tooltip="作品详情", on_click=lambda e, item_id=item.item_id: page.run_async(page.show_work_detail(item_id))),
                                ft.IconButton(icon=ft.Icons.IMAGE_SEARCH if gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, icon_color=ft.Colors.PRIMARY, tooltip="预览图片" if gallery else page._.get("browse_video", "浏览视频"), on_click=(lambda e, item_id=item.item_id: page.run_async(page.preview_item_images(item_id))) if gallery else (lambda e, item_id=item.item_id: page.run_async(page.browse_video(item_id)))),
                                ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color=ft.Colors.PRIMARY, tooltip=page._.get("download_work", "下载作品"), on_click=lambda e, item_id=item.item_id: page.run_async(page.download_one(item_id))),
                                ft.IconButton(icon=ft.Icons.FOLDER_OPEN, icon_color=ft.Colors.PRIMARY, tooltip="打开下载位置", visible=item.status == "downloaded", on_click=lambda e, item_id=item.item_id: page.run_async(page.open_item_download_location(item_id))),
                            ],
                            spacing=3,
                            wrap=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                ),
                ft.Container(content=select_checkbox, width=40, height=40, right=2, bottom=2, alignment=ft.Alignment(0, 0)),
            ],
        ),
    )
