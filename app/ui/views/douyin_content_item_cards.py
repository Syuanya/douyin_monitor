from __future__ import annotations

import flet as ft


def build_inbox_item_card(view, account, item):
    title = item.title or item.item_id
    owner = account.display_name or account.douyin_nickname or account.account_id
    is_gallery = view._is_gallery_item(item)
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
                        ft.IconButton(icon=ft.Icons.PERSON_SEARCH, tooltip="查看该账号作品", on_click=lambda e, account_id=account.account_id: view.run_async(view.open_account_works(account_id)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, tooltip="打开作品", on_click=lambda e, url=item.share_url: view.run_async(view.open_url(url)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.CONTENT_COPY, tooltip="复制作品链接", on_click=lambda e, url=item.share_url: view.run_async(view.copy_text(url)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, tooltip="预览", on_click=lambda e, account_id=account.account_id, item_id=item.item_id, gallery=is_gallery: view.run_async(view.preview_inbox_item(account_id, item_id, gallery)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="下载", on_click=lambda e, account_id=account.account_id, item_id=item.item_id: view.run_async(view.download_inbox_item(account_id, item_id)), icon_color=ft.Colors.PRIMARY),
                        ft.IconButton(icon=ft.Icons.DONE, tooltip="标记已处理", on_click=lambda e, account_id=account.account_id, item_id=item.item_id: view.run_async(view.mark_item_seen(account_id, item_id)), icon_color=ft.Colors.PRIMARY),
                    ],
                    spacing=3,
                    wrap=True,
                ),
            ],
        ),
    )


def build_history_item_card(view, item):
    title = item.title or item.item_id
    subtitle = (
        f"ID: {item.item_id}\n"
        f"{view._.get('publish_time', '发布时间')}：{item.publish_time or '-'}\n"
        f"{view._.get('first_seen', '首次发现')}：{item.first_seen_time or '-'}"
    )
    is_gallery = view._is_gallery_item(item)
    cover_control = (
        ft.Container(
            height=150,
            border_radius=6,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            content=ft.Image(src=item.cover_url, width=260, height=150, fit=ft.BoxFit.COVER),
            on_click=(
                (lambda e, item_id=item.item_id: view.run_async(view.preview_item_images(item_id)))
                if is_gallery
                else (lambda e, url=item.share_url: view.run_async(view.open_url(url)))
            ),
            tooltip="预览图片" if is_gallery else view._.get("open_work", "打开作品"),
        )
        if item.cover_url
        else ft.Container(
            height=150,
            border_radius=6,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            alignment=ft.Alignment(0, 0),
            content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=ft.Colors.ON_SURFACE_VARIANT),
        )
    )
    title_row = ft.Row(
        controls=[
            ft.Text(title, size=13, weight=ft.FontWeight.BOLD, selectable=True, expand=True, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
            build_work_status_chip(view, item),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    select_checkbox = ft.Checkbox(
        value=item.item_id in view.selected_work_ids,
        width=40,
        height=40,
        on_change=lambda e, item_id=item.item_id: view.run_async(view.toggle_work_selected(item_id, bool(e.control.value))),
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
                        title_row,
                        ft.Text(subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True, max_lines=3),
                        ft.Row(
                            controls=[
                                ft.IconButton(icon=ft.Icons.OPEN_IN_NEW, icon_color=ft.Colors.PRIMARY, tooltip=view._.get("open_work", "打开作品"), on_click=lambda e, url=item.share_url: view.run_async(view.open_url(url))),
                                ft.IconButton(icon=ft.Icons.CONTENT_COPY, icon_color=ft.Colors.PRIMARY, tooltip=view._.get("copy_work", "复制作品链接"), on_click=lambda e, url=item.share_url: view.run_async(view.copy_text(url))),
                                ft.IconButton(icon=ft.Icons.INFO_OUTLINE, icon_color=ft.Colors.PRIMARY, tooltip="作品详情", on_click=lambda e, item_id=item.item_id: view.run_async(view.show_work_detail(item_id))),
                                ft.IconButton(
                                    icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE,
                                    icon_color=ft.Colors.PRIMARY,
                                    tooltip="预览图片" if is_gallery else view._.get("browse_video", "浏览视频"),
                                    on_click=(
                                        (lambda e, item_id=item.item_id: view.run_async(view.preview_item_images(item_id)))
                                        if is_gallery
                                        else (lambda e, item_id=item.item_id: view.run_async(view.browse_video(item_id)))
                                    ),
                                ),
                                ft.IconButton(icon=ft.Icons.DOWNLOAD, icon_color=ft.Colors.PRIMARY, tooltip=view._.get("download_work", "下载作品"), on_click=lambda e, item_id=item.item_id: view.run_async(view.download_one(item_id))),
                                ft.IconButton(icon=ft.Icons.FOLDER_OPEN, icon_color=ft.Colors.PRIMARY, tooltip="打开下载位置", visible=item.status == "downloaded", on_click=lambda e, item_id=item.item_id: view.run_async(view.open_item_download_location(item_id))),
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


def build_work_status_chip(view, item) -> ft.Container:
    status = str(getattr(item, "status", "") or "")
    if status == "new":
        label, color = view._.get("new_work", "新作品"), ft.Colors.PRIMARY
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
