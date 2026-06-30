from __future__ import annotations

from typing import Any

import flet as ft


def build_title_area(owner: Any) -> ft.Control:
    batch_controls = []
    if not owner.account_select_mode:
        batch_controls.append(
            ft.TextButton(
                "批量处理",
                icon=ft.Icons.CHECKLIST,
                on_click=lambda e: owner.run_async(owner.toggle_account_select_mode()),
            )
        )
    return ft.Column(
        controls=[
            ft.Row(
                controls=[
                    ft.Text(owner._.get("title", "抖音内容监控"), theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                    ft.IconButton(
                        icon=ft.Icons.INFO_OUTLINE,
                        tooltip=owner._.get("subtitle", "低频检测公开主页作品更新"),
                        icon_color=ft.Colors.ON_SURFACE_VARIANT,
                    ),
                    *batch_controls,
                    ft.Container(expand=True),
                    owner.loading_indicator,
                    ft.IconButton(
                        icon=ft.Icons.STOP_CIRCLE,
                        tooltip="处理完当前请求后停止批量检测/同步",
                        disabled=not owner.batch_job_running,
                        on_click=lambda e: owner.run_async(owner.cancel_batch_job()),
                        icon_color=ft.Colors.ERROR,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.SEARCH,
                        tooltip="搜索监控用户",
                        on_click=lambda e: owner.run_async(owner.search_accounts_on_click()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.TextButton(
                        f"新作品箱 {owner._pending_new_work_count()}",
                        icon=ft.Icons.INBOX,
                        tooltip=f"打开新作品箱（当前 {owner._pending_new_work_count()} 个）",
                        on_click=lambda e: owner.run_async(owner.open_new_work_inbox()),
                    ),
                    ft.TextButton(
                        f"异常修复 {len(owner._error_accounts())}",
                        icon=ft.Icons.HEALTH_AND_SAFETY,
                        tooltip="集中查看 Cookie、风控、主页不可访问等异常账号",
                        disabled=not owner._error_accounts(),
                        on_click=lambda e: owner.run_async(owner.open_error_repair_center()),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ADD,
                        tooltip="添加监控用户",
                        on_click=lambda e: owner.run_async(owner.show_add_account_dialog()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CHECKLIST,
                        tooltip="批量导入账号（支持 TXT / CSV 文件）",
                        on_click=lambda e: owner.run_async(owner.show_batch_import_dialog()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.REFRESH,
                        tooltip="刷新界面（不请求抖音；需要请求平台请点快速检测或同步作品列表）",
                        on_click=owner.refresh_on_click,
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.BUG_REPORT_OUTLINED,
                        tooltip=owner._.get("export_diagnostics", "导出诊断包"),
                        on_click=owner.export_diagnostics_on_click,
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip=owner._.get("open_log_dir", "打开日志目录"),
                        on_click=owner.open_log_dir_on_click,
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.RESTORE,
                        tooltip="恢复最近删除的账号",
                        visible=bool(owner.recent_deleted_accounts or owner.deleted_account_batches),
                        on_click=lambda e: owner.run_async(owner.restore_recent_deleted_accounts()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                ],
                alignment=ft.MainAxisAlignment.START,
            ),
            ft.Row(
                controls=[
                    owner._monitor_summary_chip(),
                    ft.TextButton(
                        "健康面板",
                        icon=ft.Icons.HEALTH_AND_SAFETY,
                        tooltip="查看账号健康评分、风险账号和处理建议",
                        on_click=lambda e: owner.run_async(owner.show_content_health_dashboard()),
                    ),
                    ft.TextButton(
                        "素材收集箱",
                        icon=ft.Icons.INBOX,
                        tooltip="集中筛选新作品、失败项、已下载素材并导出链接",
                        on_click=lambda e: owner.run_async(owner.show_content_material_collection()),
                    ),
                    ft.TextButton(
                        "分组统计",
                        icon=ft.Icons.QUERY_STATS,
                        tooltip="按分组查看账号、作品、失败和健康数据",
                        on_click=lambda e: owner.run_async(owner.show_content_group_statistics()),
                    ),
                    ft.TextButton(
                        "新增摘要",
                        icon=ft.Icons.INSIGHTS,
                        tooltip="查看近 24 小时新增作品和高产账号",
                        on_click=lambda e: owner.run_async(owner.show_content_digest(1)),
                    ),
                    *owner._account_filter_buttons(),
                    ft.TextButton(
                        "快速检测更新",
                        icon=ft.Icons.REFRESH,
                        tooltip="低成本检查账号是否有新作品；不会完整拉取作品明细",
                        on_click=lambda e: owner.run_async(owner.check_all_enabled_on_click()),
                    ),
                    ft.TextButton(
                        "同步作品列表",
                        icon=ft.Icons.CLOUD_SYNC,
                        tooltip="请求作品明细、封面和下载信息；账号多时建议低频使用",
                        on_click=lambda e: owner.run_async(owner.sync_all_accounts_on_click()),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DOWNLOAD,
                        tooltip="导出作品明细CSV",
                        on_click=lambda e: owner.run_async(owner.export_monitor_csv()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.GROUP,
                        tooltip="导出监控用户CSV",
                        on_click=lambda e: owner.run_async(owner.export_monitor_accounts_csv()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN,
                        tooltip="打开导出目录",
                        on_click=lambda e: owner.run_async(owner.open_monitor_export_dir()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.LIST_ALT,
                        tooltip="查看最近批量结果",
                        on_click=lambda e: owner.run_async(owner.show_batch_result_dialog()),
                        icon_color=ft.Colors.PRIMARY,
                    ),
                ],
                spacing=8,
                wrap=True,
            ),
            owner._account_group_filter_area(),
            *([owner._batch_account_toolbar()] if owner.account_select_mode else ([owner._batch_progress_panel()] if (owner.batch_job_running or owner.batch_progress_text) else [])),
        ],
        spacing=6,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
    )

