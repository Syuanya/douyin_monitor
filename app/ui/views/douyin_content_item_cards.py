from __future__ import annotations

import flet as ft


def _short(value, max_len=96):
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= max_len else text[: max(8, max_len - 3)] + "..."


def _safe_image_box(url, *, width: int, height: int, icon_name: str, radius: int = 8) -> ft.Container:
    image_url = str(url or "").strip()
    return ft.Container(
        width=width,
        height=height,
        border_radius=radius,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        alignment=ft.Alignment(0, 0),
        content=(
            ft.Image(src=image_url, width=width, height=height, fit=ft.BoxFit.COVER)
            if image_url
            else ft.Icon(icon_name, size=min(width, height) // 2, color=ft.Colors.PRIMARY)
        ),
    )


def _media_badge(is_gallery: bool) -> ft.Container:
    return ft.Container(
        width=60,
        height=52,
        border_radius=10,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            controls=[
                ft.Icon(ft.Icons.IMAGE_OUTLINED if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, size=20, color=ft.Colors.PRIMARY),
                ft.Text("图集" if is_gallery else "视频", size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=1,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
    )


def build_inbox_item_card(view, account, item):
    title = item.title or item.item_id
    owner = account.display_name or account.douyin_nickname or account.account_id
    is_gallery = view._is_gallery_item(item)
    return ft.Container(
        padding=10,
        border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
        content=ft.Column(
            spacing=8,
            controls=[
                ft.Row(
                    controls=[
                        _safe_image_box(
                            getattr(item, "cover_url", "") or getattr(item, "cover", ""),
                            width=72,
                            height=54,
                            icon_name=ft.Icons.IMAGE_OUTLINED if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE,
                            radius=8,
                        ),
                        ft.Column(
                            controls=[
                                ft.Text(_short(title, 100), size=13, weight=ft.FontWeight.BOLD, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(f"账号：{owner}\nID：{item.item_id}\n首次发现：{item.first_seen_time or '-'}\n链接：{_short(item.share_url, 120)}", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                            ],
                            spacing=4,
                            expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    controls=[
                        ft.TextButton("账号作品", icon=ft.Icons.PERSON_SEARCH, on_click=lambda e, account_id=account.account_id: view.run_async(view.open_account_works(account_id))),
                        ft.TextButton("打开作品", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e, url=item.share_url: view.run_async(view.open_url(url))),
                        ft.TextButton("复制链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=item.share_url: view.run_async(view.copy_text(url))),
                        ft.TextButton("预览图集" if is_gallery else "预览视频", icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, on_click=lambda e, account_id=account.account_id, item_id=item.item_id, gallery=is_gallery: view.run_async(view.preview_inbox_item(account_id, item_id, gallery))),
                        ft.TextButton("下载", icon=ft.Icons.DOWNLOAD, on_click=lambda e, account_id=account.account_id, item_id=item.item_id: view.run_async(view.download_inbox_item(account_id, item_id))),
                        ft.TextButton("已处理", icon=ft.Icons.DONE, on_click=lambda e, account_id=account.account_id, item_id=item.item_id: view.run_async(view.mark_item_seen(account_id, item_id))),
                    ],
                    spacing=4,
                    wrap=True,
                ),
            ],
        ),
    )


def build_history_item_card(view, item):
    title = item.title or item.item_id
    is_gallery = view._is_gallery_item(item)
    subtitle = (
        f"ID：{item.item_id}\n"
        f"{view._.get('publish_time', '发布时间')}：{item.publish_time or '-'}\n"
        f"{view._.get('first_seen', '首次发现')}：{item.first_seen_time or '-'}\n"
        f"链接：{_short(item.share_url, 120)}"
    )
    select_checkbox = ft.Checkbox(
        value=item.item_id in view.selected_work_ids,
        width=40,
        height=40,
        on_change=lambda e, item_id=item.item_id: view.run_async(view.toggle_work_selected(item_id, bool(e.control.value))),
    )
    return ft.Container(
        padding=10,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
        content=ft.Stack(
            clip_behavior=ft.ClipBehavior.NONE,
            controls=[
                ft.Column(
                    spacing=8,
                    controls=[
                        ft.Row(
                            controls=[
                                _safe_image_box(
                                    getattr(item, "cover_url", "") or getattr(item, "cover", ""),
                                    width=72,
                                    height=54,
                                    icon_name=ft.Icons.IMAGE_OUTLINED if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE,
                                    radius=8,
                                ),
                                ft.Column(
                                    controls=[
                                        ft.Row(controls=[ft.Text(_short(title, 100), size=13, weight=ft.FontWeight.BOLD, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS), build_work_status_chip(view, item)], spacing=6, wrap=True),
                                        ft.Text(subtitle, size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=4),
                                    ],
                                    spacing=4,
                                    expand=True,
                                ),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        ft.Row(
                            controls=[
                                ft.TextButton(view._.get("open_work", "打开作品"), icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e, url=item.share_url: view.run_async(view.open_url(url))),
                                ft.TextButton(view._.get("copy_work", "复制作品链接"), icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=item.share_url: view.run_async(view.copy_text(url))),
                                ft.TextButton("详情", icon=ft.Icons.INFO_OUTLINE, on_click=lambda e, item_id=item.item_id: view.run_async(view.show_work_detail(item_id))),
                                ft.TextButton("预览图集" if is_gallery else view._.get("browse_video", "浏览视频"), icon=ft.Icons.IMAGE_SEARCH if is_gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, on_click=(lambda e, item_id=item.item_id: view.run_async(view.preview_item_images(item_id))) if is_gallery else (lambda e, item_id=item.item_id: view.run_async(view.browse_video(item_id)))),
                                ft.TextButton(view._.get("download_work", "下载作品"), icon=ft.Icons.DOWNLOAD, on_click=lambda e, item_id=item.item_id: view.run_async(view.download_one(item_id))),
                            ],
                            spacing=4,
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
