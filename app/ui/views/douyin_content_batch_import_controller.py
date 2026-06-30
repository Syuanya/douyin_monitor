from __future__ import annotations

import asyncio
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

from ...core.content_monitor.services.batch_import_service import (
    BatchImportPreview,
    parse_batch_import_text,
    preview_to_report_lines,
    read_batch_import_file,
)
from ...utils.logger import logger
try:
    from .douyin_content_bulk_components import BatchImportControls, build_batch_import_dialog
except ModuleNotFoundError:  # pragma: no cover - optional desktop dependency in unit tests
    BatchImportControls = Any  # type: ignore[misc,assignment]

    def build_batch_import_dialog(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("Flet is required to build the batch import dialog")


class DouyinContentBatchImportController:
    """Owns batch account import flows for the Douyin content monitor page.

    The controller centralizes parsing, file picker mounting, preview reporting,
    import execution and background nickname hydration. The page only delegates
    entry points, which keeps import-specific state out of the main view.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner
        self.file_picker: ft.FilePicker | None = None

    def parse_rows(self, text: str, default_group: str = "") -> list[dict[str, str]]:
        preview = parse_batch_import_text(
            text,
            default_group=default_group,
            existing_accounts=list(self.owner.manager.accounts),
        )
        return [
            {
                "url": row.normalized_url,
                "name": row.name,
                "group": row.group,
                "action": row.action,
                "reason": row.reason,
            }
            for row in preview.valid_rows
        ]

    async def show_dialog(self) -> None:
        async def close_dialog(_=None):
            dialog = controls.dialog
            dialog.open = False
            self.owner.app.dialog_area.update()

        async def submit(import_controls: BatchImportControls):
            await self.submit(import_controls, close_dialog=close_dialog)

        controls = build_batch_import_dialog(
            lambda c: self.owner.run_async(submit(c)),
            close_dialog,
            on_preview=lambda c: self.owner.run_async(self.show_preview(c, popup=True)),
            on_pick_file=lambda c: self.owner.run_async(self.pick_file(c)),
        )
        dialog = controls.dialog
        dialog.open = True
        self.owner.app.dialog_area.content = dialog
        self.owner.app.dialog_area.update()

    async def load_preview(self, import_controls: BatchImportControls) -> BatchImportPreview:
        text_parts = [str(import_controls.text_field.value or "")]
        file_path = str(import_controls.file_path_field.value or "").strip()
        if file_path:
            try:
                text_parts.append(read_batch_import_file(file_path))
            except Exception as exc:
                preview = BatchImportPreview()
                preview.errors.append({"line_no": 0, "line": file_path, "reason": f"读取导入文件失败：{exc}"})
                return preview
        return parse_batch_import_text(
            "\n".join(text_parts),
            default_group=import_controls.default_group.value or "",
            existing_accounts=list(self.owner.manager.accounts),
        )

    async def show_preview(self, import_controls: BatchImportControls, *, popup: bool = False) -> BatchImportPreview:
        preview = await self.load_preview(import_controls)
        lines = preview_to_report_lines(preview, limit=80)
        import_controls.preview_text.value = preview.summary_text()
        import_controls.preview_text.color = ft.Colors.PRIMARY if preview.valid_rows else ft.Colors.ERROR
        try:
            import_controls.preview_text.update()
        except Exception:
            pass
        if popup:
            await self.show_text_report_dialog("批量导入预览", lines)
        return preview

    async def pick_file(self, import_controls: BatchImportControls) -> None:
        self.ensure_file_picker(import_controls)
        if self.file_picker is None:
            await self.owner.app.snack_bar.show_snack_bar("当前环境不支持文件选择器，请手动粘贴 TXT / CSV 路径", bgcolor=ft.Colors.ERROR)
            return
        try:
            self.file_picker.pick_files(
                allow_multiple=False,
                allowed_extensions=["txt", "csv"],
                dialog_title="选择批量导入账号文件",
            )
        except Exception as exc:
            logger.debug(f"open batch import picker failed: {exc}")
            await self.owner.app.snack_bar.show_snack_bar("打开文件选择器失败，请手动粘贴 TXT / CSV 路径", bgcolor=ft.Colors.ERROR)

    def ensure_file_picker(self, import_controls: BatchImportControls) -> None:
        if not hasattr(ft, "FilePicker"):
            return
        if self.file_picker is not None:
            try:
                if self.file_picker not in self.owner.page.overlay:
                    self.owner.page.overlay.append(self.file_picker)
                    self.owner.page.update()
            except Exception as exc:
                logger.debug(f"remount batch import picker failed: {exc}")
            return

        def on_result(event) -> None:
            try:
                files = list(getattr(event, "files", None) or [])
                path = str(getattr(files[0], "path", "") or "") if files else ""
                if path:
                    import_controls.file_path_field.value = path
                    import_controls.file_path_field.update()
                    import_controls.preview_text.value = "已选择文件，请点击“预览”检查重复和无效行。"
                    import_controls.preview_text.color = ft.Colors.PRIMARY
                    import_controls.preview_text.update()
            except Exception as exc:
                logger.debug(f"batch import picker result failed: {exc}")

        try:
            self.file_picker = ft.FilePicker(on_result=on_result)
            if self.file_picker not in self.owner.page.overlay:
                self.owner.page.overlay.append(self.file_picker)
                self.owner.page.update()
        except Exception as exc:
            logger.debug(f"create batch import picker failed: {exc}")
            self.file_picker = None

    async def submit(self, import_controls: BatchImportControls, *, close_dialog) -> dict[str, Any]:
        owner = self.owner
        preview = await self.show_preview(import_controls)
        rows = list(preview.valid_rows)
        if not rows:
            await owner.app.snack_bar.show_snack_bar("未识别到可导入的抖音主页链接，请先查看预览明细", bgcolor=ft.Colors.ERROR)
            return {"added": 0, "updated": 0, "failed": 0, "hydrate_count": 0}

        added = 0
        updated = 0
        failed = 0
        hydrate_account_ids: list[str] = []
        failure_lines: list[str] = []
        should_start = bool(import_controls.start_switch.value)
        if should_start and len(rows) >= 20:
            await owner.app.snack_bar.show_snack_bar(
                "大批量导入已启用分批启动监控，请不要立即连续同步全部作品",
                bgcolor=ft.Colors.PRIMARY,
                duration=6000,
                show_close_icon=True,
            )

        for row in rows:
            try:
                before_ids = {account.account_id for account in owner.manager.accounts}
                account = await owner.manager.add_account(row.normalized_url, row.name)
                if not row.name:
                    hydrate_account_ids.append(account.account_id)
                if account.account_id in before_ids:
                    updated += 1
                else:
                    added += 1
                await owner.manager.update_account_settings(
                    account.account_id,
                    display_name=row.name or account.display_name,
                    group_name=row.group,
                    auto_download_policy=import_controls.policy_dropdown.value or "none",
                    notify_enabled=bool(import_controls.notify_switch.value),
                )
                if should_start:
                    await owner.manager.start_monitor(account.account_id)
            except Exception as exc:
                failed += 1
                failure_lines.append(f"第 {row.line_no} 行 {row.normalized_url}：{exc}")
                logger.debug(f"batch import account failed: {row.normalized_url}, error={exc}")

        await close_dialog()
        await owner.render_current_view()
        if hydrate_account_ids:
            self.schedule_name_hydration(hydrate_account_ids)
        counts = preview.counts()
        owner.batch_result_lines = [preview.summary_text(), f"导入执行：新增 {added}，更新 {updated}，失败 {failed}"]
        owner.batch_result_lines.extend(failure_lines[:100])
        suffix = f"，跳过重复 {counts.get('duplicate', 0)}，无效 {counts.get('invalid', 0)}"
        if hydrate_account_ids:
            suffix += f"，{len(hydrate_account_ids)} 个未填备注账号将在后台补全昵称"
        await owner.app.snack_bar.show_snack_bar(
            f"批量导入完成：新增 {added}，更新 {updated}，失败 {failed}{suffix}",
            bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
            duration=7000,
            show_close_icon=True,
        )
        return {"added": added, "updated": updated, "failed": failed, "hydrate_count": len(hydrate_account_ids)}

    async def show_text_report_dialog(self, title: str, lines: list[str]) -> None:
        owner = self.owner

        def close_dialog(_=None):
            dialog.open = False
            owner.app.dialog_area.update()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Column(
                controls=[ft.Text("\n".join(lines), selectable=True, size=12)],
                tight=True,
                width=760,
                scroll=ft.ScrollMode.AUTO,
            ),
            actions=[ft.TextButton("关闭", icon=ft.Icons.CLOSE, on_click=close_dialog)],
        )
        dialog.open = True
        owner.app.dialog_area.content = dialog
        owner.app.dialog_area.update()

    def schedule_name_hydration(self, account_ids: list[str]) -> None:
        unique_ids = list(dict.fromkeys([account_id for account_id in account_ids if account_id]))
        if not unique_ids:
            return
        try:
            asyncio.create_task(self.hydrate_account_names(unique_ids))
        except RuntimeError:
            self.owner.run_async(self.hydrate_account_names(unique_ids))

    async def hydrate_account_names(self, account_ids: list[str]) -> tuple[int, int]:
        owner = self.owner
        success = 0
        failed = 0
        for account_id in account_ids:
            try:
                result = await owner.manager.hydrate_account_display_name(account_id, force=True)
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
            except Exception as exc:
                failed += 1
                logger.debug(f"batch import background hydrate nickname failed: account={account_id}, error={exc}")
            await asyncio.sleep(0.8)
        try:
            await owner.render_current_view()
            await owner.app.snack_bar.show_snack_bar(
                f"批量昵称后台补全完成：成功 {success}，未获取 {failed}",
                bgcolor=ft.Colors.PRIMARY if success else ft.Colors.ON_SURFACE_VARIANT,
                duration=4000,
                show_close_icon=True,
            )
        except Exception as exc:
            logger.debug(f"batch import background hydrate UI refresh failed: {exc}")
        return success, failed
