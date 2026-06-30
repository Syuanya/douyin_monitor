from __future__ import annotations

from typing import Any

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    class _FallbackColors:
        ERROR = "error"
        ERROR_CONTAINER = "error_container"
        GREEN = "green"
        ON_SURFACE_VARIANT = "on_surface_variant"
        OUTLINE_VARIANT = "outline_variant"
        PRIMARY = "primary"
        PRIMARY_CONTAINER = "primary_container"
        SURFACE_VARIANT = "surface_variant"
        ORANGE = "orange"

    class _FallbackIcons:
        CHECK = "check"
        CLOSE = "close"
        CONTENT_COPY = "content_copy"
        DOWNLOAD = "download"
        ERROR_OUTLINE = "error_outline"
        FOLDER_OPEN = "folder_open"
        HEALTH_AND_SAFETY = "health_and_safety"
        INFO_OUTLINE = "info_outline"
        LIST_ALT = "list_alt"
        OPEN_IN_NEW = "open_in_new"
        QUERY_STATS = "query_stats"
        REFRESH = "refresh"
        SEARCH = "search"
        WARNING_AMBER = "warning_amber"

    class _FallbackFlet:
        Colors = _FallbackColors
        Icons = _FallbackIcons

    ft = _FallbackFlet()  # type: ignore[assignment]


class DouyinContentInsightsController:
    """P3 efficiency dashboards for the Douyin content monitor desktop page.

    The core service owns all business calculations. This controller only adapts
    those summaries into user-facing dialogs, keeping the monitor page thin and
    avoiding duplicate scoring/filtering rules in the UI layer.
    """

    STATUS_OPTIONS = {
        "pending": "待处理",
        "all": "全部",
        "new": "新作品",
        "downloaded": "已下载",
        "failed": "下载失败",
        "unprocessed": "未处理",
    }
    MEDIA_OPTIONS = {"all": "全部类型", "video": "视频", "gallery": "图集"}

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    # ---------- pure adapters used by tests and UI ----------
    def health_summary(self) -> dict[str, Any]:
        if hasattr(self.owner.manager, "content_monitor_health_summary"):
            return self.owner.manager.content_monitor_health_summary()
        return {"total": 0, "average_score": 0, "counts": {}, "accounts": [], "priority_accounts": []}

    def group_statistics(self) -> dict[str, Any]:
        if hasattr(self.owner.manager, "content_monitor_group_statistics"):
            return self.owner.manager.content_monitor_group_statistics()
        return {"total_groups": 0, "groups": []}

    def digest(self, days: int = 1) -> dict[str, Any]:
        if hasattr(self.owner.manager, "content_monitor_time_window_digest"):
            return self.owner.manager.content_monitor_time_window_digest(days=days)
        return {"days": days, "new_items": 0, "downloaded": 0, "failed": 0, "gallery": 0, "video": 0, "top_accounts": [], "items": []}

    def material_collection(
        self,
        *,
        query: str = "",
        status: str = "pending",
        media_type: str = "all",
        group_name: str = "",
        limit: int = 100,
    ) -> dict[str, Any]:
        if hasattr(self.owner.manager, "content_monitor_material_collection"):
            return self.owner.manager.content_monitor_material_collection(
                query=query,
                status=status,
                media_type=media_type,
                group_name=group_name,
                limit=limit,
            )
        return {"total": 0, "limit": limit, "items": []}

    @staticmethod
    def health_level_label(level: str) -> str:
        return {
            "excellent": "健康",
            "good": "正常",
            "warning": "需关注",
            "risk": "高风险",
            "paused": "未监控",
        }.get(str(level or ""), "未知")

    @staticmethod
    def health_level_color(level: str) -> Any:
        return {
            "excellent": ft.Colors.GREEN,
            "good": ft.Colors.PRIMARY,
            "warning": ft.Colors.ORANGE,
            "risk": ft.Colors.ERROR,
            "paused": ft.Colors.ON_SURFACE_VARIANT,
        }.get(str(level or ""), ft.Colors.ON_SURFACE_VARIANT)

    @classmethod
    def material_filter_label(cls, *, status: str, media_type: str, group_name: str = "", query: str = "") -> str:
        parts = [cls.STATUS_OPTIONS.get(str(status or "pending"), str(status or "pending"))]
        media_label = cls.MEDIA_OPTIONS.get(str(media_type or "all"), str(media_type or "all"))
        if media_label != "全部类型":
            parts.append(media_label)
        if group_name:
            parts.append(f"分组：{group_name}")
        if query:
            parts.append(f"关键词：{query}")
        return " / ".join(parts)

    @staticmethod
    def compact_text(value: Any, *, max_len: int = 72) -> str:
        text = str(value or "").strip()
        if len(text) <= max_len:
            return text
        return text[: max(1, max_len - 1)] + "…"

    def group_names(self) -> list[str]:
        names = {str(getattr(account, "group_name", "") or "").strip() or "未分组" for account in self.owner.manager.accounts}
        return sorted(names)

    # ---------- shared UI helpers ----------
    def _close_dialog(self, dialog: Any) -> None:
        dialog.open = False
        self.owner.app.dialog_area.update()

    def _chip(self, text: str, *, color: Any | None = None) -> Any:
        return ft.Container(
            content=ft.Text(text, size=12, color=color or ft.Colors.ON_SURFACE_VARIANT),
            padding=ft.Padding.symmetric(horizontal=9, vertical=4),
            border=ft.Border.all(1, color or ft.Colors.OUTLINE_VARIANT),
            border_radius=16,
        )

    def _empty_state(self, message: str) -> Any:
        return ft.Container(
            content=ft.Text(message, size=13, color=ft.Colors.ON_SURFACE_VARIANT),
            padding=16,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=10,
        )

    def _account_health_card(self, row: dict[str, Any]) -> Any:
        level = str(row.get("level") or "")
        color = self.health_level_color(level)
        reasons = [str(reason) for reason in row.get("reasons") or [] if str(reason or "")]
        steps = [str(step) for step in row.get("next_steps") or [] if str(step or "")]
        controls: list[Any] = [
            ft.Row(
                controls=[
                    ft.Text(self.compact_text(row.get("account_name"), max_len=28), weight=ft.FontWeight.BOLD, expand=True),
                    ft.Text(f"{row.get('score', 0)}分 · {row.get('label') or self.health_level_label(level)}", color=color, size=12),
                ],
                spacing=8,
            ),
            ft.Text(f"分组：{row.get('group_name') or '未分组'} / 新作品 {row.get('pending_new', 0)} / 失败 {row.get('download_failed', 0)}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if reasons:
            controls.append(ft.Text("原因：" + "；".join(reasons[:2]), size=12, selectable=True))
        if steps:
            controls.append(ft.Text("建议：" + "；".join(steps[:2]), size=12, color=ft.Colors.PRIMARY, selectable=True))
        account_id = str(row.get("account_id") or "")
        actions: list[Any] = []
        if account_id:
            actions.extend(
                [
                    ft.TextButton("查看作品", icon=ft.Icons.LIST_ALT, on_click=lambda e, aid=account_id: self.owner.run_async(self.owner.open_account_works(aid))),
                    ft.TextButton("重新检测", icon=ft.Icons.REFRESH, on_click=lambda e, aid=account_id: self.owner.run_async(self.owner.check_one(aid))),
                ]
            )
        if actions:
            controls.append(ft.Row(controls=actions, spacing=6, wrap=True))
        return ft.Container(
            content=ft.Column(controls=controls, spacing=5),
            padding=10,
            border=ft.Border.all(1, color),
            border_radius=10,
        )

    def _material_card(self, row: dict[str, Any]) -> Any:
        media_label = "图集" if row.get("media_type") == "gallery" else "视频"
        status_text = str(row.get("status") or "")
        failed = status_text == "download_failed" or bool(row.get("failure_category"))
        controls: list[Any] = [
            ft.Row(
                controls=[
                    ft.Text(self.compact_text(row.get("title") or row.get("item_id"), max_len=42), weight=ft.FontWeight.BOLD, expand=True),
                    self._chip(media_label, color=ft.Colors.PRIMARY),
                    self._chip("失败" if failed else status_text or "-", color=ft.Colors.ERROR if failed else ft.Colors.ON_SURFACE_VARIANT),
                ],
                spacing=6,
            ),
            ft.Text(f"账号：{row.get('account_name') or '-'} / 分组：{row.get('group_name') or '未分组'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
            ft.Text(f"发现：{row.get('first_seen_time') or '-'} / 发布：{row.get('publish_time') or '-'}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
        ]
        if row.get("download_path"):
            controls.append(ft.Text("保存：" + self.compact_text(row.get("download_path"), max_len=88), size=12, selectable=True))
        if row.get("failure_next_step"):
            controls.append(ft.Text("建议：" + str(row.get("failure_next_step")), size=12, color=ft.Colors.PRIMARY, selectable=True))
        item_url = str(row.get("share_url") or "")
        actions: list[Any] = []
        if item_url:
            actions.append(ft.TextButton("打开作品", icon=ft.Icons.OPEN_IN_NEW, on_click=lambda e, url=item_url: self.owner.run_async(self.owner.open_url(url))))
            actions.append(ft.TextButton("复制链接", icon=ft.Icons.CONTENT_COPY, on_click=lambda e, url=item_url: self.owner.run_async(self.owner.copy_text(url))))
        if row.get("download_path"):
            actions.append(ft.TextButton("打开位置", icon=ft.Icons.FOLDER_OPEN, on_click=lambda e, path=str(row.get("download_path") or ""): self.owner.run_async(self.owner.open_download_location(path))))
        if actions:
            controls.append(ft.Row(controls=actions, spacing=6, wrap=True))
        return ft.Container(
            content=ft.Column(controls=controls, spacing=5),
            padding=10,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=10,
        )

    # ---------- dialogs ----------
    async def show_health_dashboard(self) -> None:
        summary = self.health_summary()
        counts = summary.get("counts") or {}
        priority = list(summary.get("priority_accounts") or [])[:12]
        chips = [
            self._chip(f"账号 {summary.get('total', 0)}"),
            self._chip(f"平均健康 {summary.get('average_score', 0)}", color=ft.Colors.PRIMARY),
            self._chip(f"高风险 {counts.get('risk', 0)}", color=ft.Colors.ERROR),
            self._chip(f"需关注 {counts.get('warning', 0)}", color=ft.Colors.ORANGE),
            self._chip(f"未监控 {counts.get('paused', 0)}"),
        ]
        cards = [self._account_health_card(row) for row in priority] if priority else [self._empty_state("暂无账号健康数据。")]
        dialog: Any = None

        def close(_=None):
            self._close_dialog(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("账号健康面板", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                controls=[
                    ft.Row(controls=chips, wrap=True, spacing=6),
                    ft.Text("优先处理低分账号：", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                    ft.Column(controls=cards, spacing=8, scroll=ft.ScrollMode.AUTO, height=520),
                ],
                spacing=10,
                width=760,
                tight=True,
            ),
            actions=[
                ft.TextButton("异常修复", icon=ft.Icons.HEALTH_AND_SAFETY, on_click=lambda e: self.owner.run_async(self.owner.open_error_repair_center())),
                ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        dialog.open = True
        self.owner.app.dialog_area.content = dialog
        self.owner.app.dialog_area.update()

    async def show_group_statistics(self) -> None:
        stats = self.group_statistics()
        rows = list(stats.get("groups") or [])
        controls: list[Any] = []
        for row in rows[:40]:
            controls.append(
                ft.Container(
                    content=ft.Column(
                        controls=[
                            ft.Row(
                                controls=[
                                    ft.Text(str(row.get("group_name") or "未分组"), weight=ft.FontWeight.BOLD, expand=True),
                                    ft.Text(f"健康 {row.get('average_health_score', 0)}", color=ft.Colors.PRIMARY, size=12),
                                ]
                            ),
                            ft.Text(
                                f"账号 {row.get('accounts_total', 0)} / 监控 {row.get('accounts_enabled', 0)} / 异常 {row.get('accounts_with_errors', 0)} / 作品 {row.get('items_total', 0)}",
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                            ft.Text(
                                f"待处理 {row.get('pending_new', 0)} / 已下载 {row.get('downloaded', 0)} / 失败 {row.get('download_failed', 0)} / 视频 {row.get('video', 0)} / 图集 {row.get('gallery', 0)}",
                                size=12,
                                color=ft.Colors.ON_SURFACE_VARIANT,
                            ),
                        ],
                        spacing=4,
                    ),
                    padding=10,
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=10,
                )
            )
        if not controls:
            controls.append(self._empty_state("暂无分组统计数据。"))
        dialog: Any = None

        def close(_=None):
            self._close_dialog(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("分组统计报告", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column(controls=controls, spacing=8, width=720, height=560, scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close)],
        )
        dialog.open = True
        self.owner.app.dialog_area.content = dialog
        self.owner.app.dialog_area.update()

    async def show_digest(self, days: int = 1) -> None:
        current_days = max(1, min(30, int(days or 1)))
        data = self.digest(days=current_days)
        items = list(data.get("items") or [])[:80]
        top_accounts = list(data.get("top_accounts") or [])[:8]
        chips = [
            self._chip(f"{current_days} 天新增 {data.get('new_items', 0)}", color=ft.Colors.PRIMARY),
            self._chip(f"视频 {data.get('video', 0)}"),
            self._chip(f"图集 {data.get('gallery', 0)}"),
            self._chip(f"已下载 {data.get('downloaded', 0)}"),
            self._chip(f"失败 {data.get('failed', 0)}", color=ft.Colors.ERROR if data.get("failed") else ft.Colors.ON_SURFACE_VARIANT),
        ]
        top_text = "；".join(f"{row.get('account_name')} +{row.get('new_items', 0)}" for row in top_accounts) or "暂无"
        item_controls: list[Any] = [ft.Text(f"新增最多账号：{top_text}", size=12, color=ft.Colors.ON_SURFACE_VARIANT, selectable=True)]
        for row in items:
            url = str(row.get("share_url") or "")
            item_controls.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Text(self.compact_text(row.get("time"), max_len=18), size=12, width=120),
                            ft.Text(self.compact_text(row.get("account_name"), max_len=18), size=12, width=120),
                            ft.Text(self.compact_text(row.get("title") or row.get("item_id"), max_len=42), expand=True, size=12),
                            ft.TextButton("打开", icon=ft.Icons.OPEN_IN_NEW, disabled=not bool(url), on_click=lambda e, target=url: self.owner.run_async(self.owner.open_url(target))),
                        ],
                        spacing=6,
                    ),
                    padding=ft.Padding.symmetric(horizontal=6, vertical=4),
                    border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
                    border_radius=8,
                )
            )
        if not items:
            item_controls.append(self._empty_state("当前时间窗口没有新增作品。"))
        dialog: Any = None

        async def switch_days(value: int):
            self._close_dialog(dialog)
            await self.show_digest(days=value)

        def close(_=None):
            self._close_dialog(dialog)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("新增摘要", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                controls=[
                    ft.Row(controls=chips, wrap=True, spacing=6),
                    ft.Row(
                        controls=[
                            ft.TextButton("近 1 天", icon=ft.Icons.FILTER_1, disabled=current_days == 1, on_click=lambda e: self.owner.run_async(switch_days(1))),
                            ft.TextButton("近 3 天", icon=ft.Icons.LOOKS_3, disabled=current_days == 3, on_click=lambda e: self.owner.run_async(switch_days(3))),
                            ft.TextButton("近 7 天", icon=ft.Icons.HISTORY, disabled=current_days == 7, on_click=lambda e: self.owner.run_async(switch_days(7))),
                        ],
                        spacing=6,
                    ),
                    ft.Column(controls=item_controls, spacing=6, scroll=ft.ScrollMode.AUTO, height=500),
                ],
                spacing=8,
                width=820,
                tight=True,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close)],
        )
        dialog.open = True
        self.owner.app.dialog_area.content = dialog
        self.owner.app.dialog_area.update()

    async def show_material_collection(self) -> None:
        query_field = ft.TextField(label="关键词", dense=True, width=220, hint_text="标题 / 账号 / 链接")
        status_dropdown = ft.Dropdown(
            label="状态",
            value="pending",
            dense=True,
            width=150,
            options=[ft.dropdown.Option(key, label) for key, label in self.STATUS_OPTIONS.items()],
        )
        media_dropdown = ft.Dropdown(
            label="类型",
            value="all",
            dense=True,
            width=130,
            options=[ft.dropdown.Option(key, label) for key, label in self.MEDIA_OPTIONS.items()],
        )
        group_options = [ft.dropdown.Option("", "全部分组")]
        group_options.extend(ft.dropdown.Option(name, name) for name in self.group_names())
        group_dropdown = ft.Dropdown(label="分组", value="", dense=True, width=160, options=group_options)
        result_title = ft.Text("", size=12, color=ft.Colors.ON_SURFACE_VARIANT)
        results_column = ft.Column(controls=[], spacing=8, scroll=ft.ScrollMode.AUTO, height=500)

        def current_filters() -> dict[str, Any]:
            return {
                "query": str(query_field.value or "").strip(),
                "status": str(status_dropdown.value or "pending"),
                "media_type": str(media_dropdown.value or "all"),
                "group_name": str(group_dropdown.value or "").strip(),
                "limit": 120,
            }

        def render_results() -> None:
            filters = current_filters()
            data = self.material_collection(**filters)
            items = list(data.get("items") or [])
            result_title.value = f"{self.material_filter_label(status=filters['status'], media_type=filters['media_type'], group_name=filters['group_name'], query=filters['query'])}：显示 {len(items)}/{data.get('total', 0)}"
            results_column.controls.clear()
            if not items:
                results_column.controls.append(self._empty_state("暂无匹配素材。"))
            else:
                for row in items:
                    results_column.controls.append(self._material_card(row))
            try:
                result_title.update()
                results_column.update()
            except Exception:
                pass

        async def do_search(_=None):
            render_results()

        async def do_export(_=None):
            filters = current_filters()
            if not hasattr(self.owner.manager, "export_content_monitor_material_links"):
                await self.owner.app.snack_bar.show_snack_bar("当前版本不支持素材导出", bgcolor=ft.Colors.ERROR)
                return
            result = self.owner.manager.export_content_monitor_material_links(**filters, limit=1000)
            if result.get("success"):
                await self.owner.app.snack_bar.show_snack_bar(f"素材链接已导出：{result.get('path')}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)
            else:
                await self.owner.app.snack_bar.show_snack_bar(str(result.get("reason") or "导出失败"), bgcolor=ft.Colors.ERROR)

        dialog: Any = None

        def close(_=None):
            self._close_dialog(dialog)

        query_field.on_submit = lambda e: self.owner.run_async(do_search())
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("素材收集箱", size=20, weight=ft.FontWeight.BOLD),
            content=ft.Column(
                controls=[
                    ft.Row(controls=[query_field, status_dropdown, media_dropdown, group_dropdown], wrap=True, spacing=8),
                    ft.Row(
                        controls=[
                            ft.FilledButton("筛选", icon=ft.Icons.SEARCH, on_click=lambda e: self.owner.run_async(do_search())),
                            ft.TextButton("导出链接", icon=ft.Icons.DOWNLOAD, on_click=lambda e: self.owner.run_async(do_export())),
                            result_title,
                        ],
                        wrap=True,
                        spacing=8,
                    ),
                    results_column,
                ],
                spacing=8,
                width=860,
                tight=True,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close)],
        )
        render_results()
        dialog.open = True
        self.owner.app.dialog_area.content = dialog
        self.owner.app.dialog_area.update()

    async def export_default_material_links(self) -> dict[str, Any]:
        if not hasattr(self.owner.manager, "export_content_monitor_material_links"):
            return {"success": False, "reason": "当前版本不支持素材导出"}
        result = self.owner.manager.export_content_monitor_material_links(status="pending", media_type="all", limit=1000)
        if result.get("success"):
            await self.owner.app.snack_bar.show_snack_bar(f"待处理素材链接已导出：{result.get('path')}", bgcolor=ft.Colors.PRIMARY, duration=6000, show_close_icon=True)
        else:
            await self.owner.app.snack_bar.show_snack_bar(str(result.get("reason") or "导出失败"), bgcolor=ft.Colors.ERROR)
        return result
