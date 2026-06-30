from __future__ import annotations

from typing import Any

import flet as ft

from ..common.safe_icons import icon
from ...views import douyin_content_state as content_state


def is_gallery_item(item: Any) -> bool:
    return content_state.is_gallery_item(item)


def work_status_chip(page: Any, item: Any) -> ft.Container:
    status = str(getattr(item, "status", "") or "")
    if status == "new":
        label, color = page._.get("new_work", "新作品"), ft.Colors.PRIMARY
    elif status == "count_only":
        label, color = "数量变化", ft.Colors.ORANGE
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


def _short_text(value: Any, max_len: int = 96) -> str:
    text = str(value or "").replace("\n", " ").strip()
    if len(text) <= max_len:
        return text
    return text[: max(8, max_len - 3)] + "..."




def _safe_image_box(url: Any, *, width: int, height: int, icon_name: str, radius: int = 8) -> ft.Container:
    """Small, bounded image box used in lists.

    Remote images are allowed only inside a fixed-size clipped container. This
    keeps WebView2/Flet image fallback bugs from expanding into a full gray
    panel. When no URL is available the box falls back to an icon.
    """

    image_url = str(url or "").strip()
    fallback = ft.Icon(icon_name, size=min(width, height) // 2, color=ft.Colors.PRIMARY)
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
            else fallback
        ),
    )


def _avatar_box(url: Any, fallback_label: str = "") -> ft.Container:
    image_url = str(url or "").strip()
    fallback_text = str(fallback_label or "").strip()[:1]
    fallback = (
        ft.Text(fallback_text, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.PRIMARY)
        if fallback_text
        else ft.Icon(ft.Icons.PERSON, size=20, color=ft.Colors.PRIMARY)
    )
    return ft.Container(
        width=40,
        height=40,
        border_radius=20,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        alignment=ft.Alignment(0, 0),
        content=(
            ft.Image(src=image_url, width=40, height=40, fit=ft.BoxFit.COVER)
            if image_url
            else fallback
        ),
    )

def _media_badge(gallery: bool, count_only: bool = False) -> ft.Container:
    if count_only:
        icon_name = ft.Icons.NOTIFICATIONS_ACTIVE
        label = "数量变化"
        color = ft.Colors.ORANGE
    elif gallery:
        icon_name = ft.Icons.IMAGE_OUTLINED
        label = "图集"
        color = ft.Colors.PRIMARY
    else:
        icon_name = ft.Icons.PLAY_CIRCLE_OUTLINE
        label = "视频"
        color = ft.Colors.PRIMARY
    return ft.Container(
        width=60,
        height=52,
        border_radius=10,
        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        alignment=ft.Alignment(0, 0),
        content=ft.Column(
            controls=[
                ft.Icon(icon_name, size=20, color=color),
                ft.Text(label, size=10, color=ft.Colors.ON_SURFACE_VARIANT),
            ],
            spacing=1,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
    )


def _cover_grid_box(url: Any, *, is_gallery: bool, count_only: bool = False) -> ft.Container:
    image_url = str(url or "").strip()
    icon_name = ft.Icons.NOTIFICATIONS_ACTIVE if count_only else (ft.Icons.IMAGE_OUTLINED if is_gallery else ft.Icons.PLAY_ARROW)
    fallback = ft.Container(
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        alignment=ft.Alignment(0, 0),
        content=ft.Icon(icon_name, size=34, color=ft.Colors.PRIMARY),
    )
    return ft.Container(
        height=150,
        border_radius=8,
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        content=(
            ft.Image(src=image_url, height=150, fit=ft.BoxFit.COVER)
            if image_url
            else fallback
        ),
    )


def _icon_action(icon_name: str, tooltip: str, on_click) -> ft.IconButton:
    return ft.IconButton(
        icon=icon_name,
        tooltip=tooltip,
        icon_color=ft.Colors.PRIMARY,
        on_click=on_click,
    )


def create_inbox_item(page: Any, account: Any, item: Any) -> ft.Container:
    """Build a grid-style new work card.

    This restores the visual card layout while keeping every remote cover inside
    a bounded 150px clipped container. The image can fail without expanding into
    a page-sized grey panel.
    """

    title = item.title or item.item_id
    owner = account.display_name or account.douyin_nickname or account.account_id
    gallery = is_gallery_item(item)
    count_only = str(getattr(item, "status", "") or "") == "count_only"
    item_id = str(getattr(item, "item_id", "") or "-")
    share_url = str(getattr(item, "share_url", "") or getattr(account, "homepage_url", "") or "")
    first_seen = getattr(item, "first_seen_time", "") or "-"
    cover_url = getattr(item, "cover_url", "") or getattr(item, "cover", "")
    actions: list[ft.Control] = [
        _icon_action(ft.Icons.PERSON_SEARCH, "查看账号作品", lambda e, account_id=account.account_id: page.run_async(page.open_account_works(account_id))),
        _icon_action(ft.Icons.OPEN_IN_NEW, "打开主页" if count_only else "打开作品", lambda e, url=share_url: page.run_async(page.open_url(url))),
        _icon_action(ft.Icons.CONTENT_COPY, "复制主页" if count_only else "复制链接", lambda e, url=share_url: page.run_async(page.copy_text(url))),
    ]
    if count_only:
        actions.append(_icon_action(ft.Icons.CLOUD_SYNC, "重新同步该账号作品", lambda e, account_id=account.account_id: page.run_async(page.sync_works(account_id))))
    else:
        actions.append(_icon_action(ft.Icons.IMAGE_SEARCH if gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, "预览图集" if gallery else "预览视频", lambda e, account_id=account.account_id, item_id=item.item_id, gallery=gallery: page.run_async(page.preview_inbox_item(account_id, item_id, gallery))))
        if str(getattr(item, "status", "") or "") == "download_failed":
            actions.append(_icon_action(ft.Icons.REPLAY, "重试下载", lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.download_inbox_item(account_id, item_id))))
        else:
            actions.append(_icon_action(ft.Icons.DOWNLOAD, "下载作品", lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.download_inbox_item(account_id, item_id))))
        if str(getattr(item, "status", "") or "") == "downloaded":
            actions.append(_icon_action(ft.Icons.FOLDER_OPEN, "打开下载位置", lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.open_inbox_item_download_location(account_id, item_id))))
    actions.append(_icon_action(ft.Icons.DONE, "标记已处理", lambda e, account_id=account.account_id, item_id=item.item_id: page.run_async(page.mark_item_seen(account_id, item_id))))
    details = [
        ft.Row(
            controls=[
                ft.Text(owner, size=11, color=ft.Colors.ON_SURFACE_VARIANT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                work_status_chip(page, item),
            ],
            spacing=4,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        ft.Text(f"ID: {item_id}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(f"首次发现：{first_seen}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    failure_reason = str(getattr(item, "failure_reason", "") or "").strip()
    if failure_reason:
        details.append(ft.Text(f"失败原因：{_short_text(failure_reason, 80)}", size=11, color=ft.Colors.ERROR, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        next_step = str(getattr(item, "failure_next_step", "") or "").strip()
        if next_step:
            details.append(ft.Text(f"建议：{_short_text(next_step, 80)}", size=11, color=ft.Colors.ORANGE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
    download_path = str(getattr(item, "download_path", "") or "").strip()
    if download_path and str(getattr(item, "status", "") or "") == "downloaded":
        details.append(ft.Text(f"保存：{_short_text(download_path, 70)}", size=11, color=ft.Colors.GREEN, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))
    if count_only:
        details.append(ft.Text("检测到数量变化，请重新同步获取具体作品。", size=11, color=ft.Colors.ORANGE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.PRIMARY_CONTAINER),
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
        content=ft.Column(
            spacing=6,
            controls=[
                _cover_grid_box(cover_url, is_gallery=gallery, count_only=count_only),
                ft.Text(_short_text(title, 56), size=13, weight=ft.FontWeight.BOLD, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                *details,
                ft.Row(controls=actions[:4], spacing=2, wrap=True),
                ft.Row(controls=actions[4:], spacing=2, wrap=True),
            ],
        ),
    )

def create_account_card(page: Any, account: Any) -> ft.Container:
    status_meta = page.account_status_meta(account)
    status_color = status_meta["color"]
    avatar_control = _avatar_box(
        getattr(account, "avatar_url", ""),
        account.display_name or account.douyin_nickname or "",
    )
    avatar_control.on_click = lambda e, account_id=account.account_id: page.run_async(page.open_account_works(account_id))
    avatar_control.tooltip = page._.get("select", "查看历史")
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
        f"下一次检测：{page.account_next_check_time(account)} / 连续失败：{getattr(account, 'error_count', 0) or 0}",
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
                                ft.TextButton(page._.get("check_now", "快速检测更新"), icon=ft.Icons.REFRESH, on_click=lambda e, account_id=account.account_id: page.run_async(page.check_one(account_id))),
                                ft.TextButton(page._.get("sync_works", "同步作品列表"), icon=ft.Icons.CLOUD_SYNC, on_click=lambda e, account_id=account.account_id: page.run_async(page.sync_works(account_id))),
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
    """Build a grid-style history work card with bounded cover image."""

    title = item.title or item.item_id
    gallery = is_gallery_item(item)
    item_id = str(getattr(item, "item_id", "") or "-")
    publish_time = getattr(item, "publish_time", "") or "-"
    first_seen = getattr(item, "first_seen_time", "") or "-"
    cover_url = getattr(item, "cover_url", "") or getattr(item, "cover", "")
    select_checkbox = ft.Checkbox(
        value=item.item_id in page.selected_work_ids,
        width=36,
        height=36,
        on_change=lambda e, item_id=item.item_id: page.run_async(page.toggle_work_selected(item_id, bool(e.control.value))),
    )
    actions: list[ft.Control] = [
        _icon_action(ft.Icons.OPEN_IN_NEW, page._.get("open_work", "打开作品"), lambda e, url=item.share_url: page.run_async(page.open_url(url))),
        _icon_action(ft.Icons.CONTENT_COPY, page._.get("copy_work", "复制作品链接"), lambda e, url=item.share_url: page.run_async(page.copy_text(url))),
        _icon_action(ft.Icons.INFO_OUTLINE, "详情", lambda e, item_id=item.item_id: page.run_async(page.show_work_detail(item_id))),
        _icon_action(ft.Icons.IMAGE_SEARCH if gallery else ft.Icons.PLAY_CIRCLE_OUTLINE, "预览图集" if gallery else page._.get("browse_video", "浏览视频"), (lambda e, item_id=item.item_id: page.run_async(page.preview_item_images(item_id))) if gallery else (lambda e, item_id=item.item_id: page.run_async(page.browse_video(item_id)))),
        _icon_action(ft.Icons.REPLAY if str(getattr(item, "status", "") or "") == "download_failed" else ft.Icons.DOWNLOAD, "重试下载" if str(getattr(item, "status", "") or "") == "download_failed" else page._.get("download_work", "下载作品"), lambda e, item_id=item.item_id: page.run_async(page.download_one(item_id))),
    ]
    if getattr(item, "status", "") == "downloaded":
        actions.append(_icon_action(ft.Icons.FOLDER_OPEN, "打开下载位置", lambda e, item_id=item.item_id: page.run_async(page.open_item_download_location(item_id))))
    meta_controls: list[ft.Control] = [
        ft.Text(f"ID: {item_id}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(f"发布时间：{publish_time}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
        ft.Text(f"首次发现：{first_seen}", size=11, color=ft.Colors.ON_SURFACE_VARIANT, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
    ]
    failure_reason = str(getattr(item, "failure_reason", "") or "").strip()
    if failure_reason:
        meta_controls.append(ft.Text(f"失败原因：{_short_text(failure_reason, 80)}", size=11, color=ft.Colors.ERROR, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
        next_step = str(getattr(item, "failure_next_step", "") or "").strip()
        if next_step:
            meta_controls.append(ft.Text(f"建议：{_short_text(next_step, 80)}", size=11, color=ft.Colors.ORANGE, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS))
    download_path = str(getattr(item, "download_path", "") or "").strip()
    if download_path and str(getattr(item, "status", "") or "") == "downloaded":
        meta_controls.append(ft.Text(f"保存：{_short_text(download_path, 70)}", size=11, color=ft.Colors.GREEN, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS))

    return ft.Container(
        padding=8,
        border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
        border_radius=8,
        bgcolor=ft.Colors.SURFACE,
        content=ft.Stack(
            clip_behavior=ft.ClipBehavior.NONE,
            controls=[
                ft.Column(
                    spacing=6,
                    controls=[
                        _cover_grid_box(cover_url, is_gallery=gallery),
                        ft.Row(
                            controls=[
                                ft.Text(_short_text(title, 54), size=13, weight=ft.FontWeight.BOLD, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                                work_status_chip(page, item),
                            ],
                            spacing=4,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                        *meta_controls,
                        ft.Row(controls=actions[:4], spacing=2, wrap=True),
                        ft.Row(controls=actions[4:], spacing=2, wrap=True),
                    ],
                ),
                ft.Container(content=select_checkbox, width=36, height=36, right=0, bottom=0, alignment=ft.Alignment(0, 0)),
            ],
        ),
    )
