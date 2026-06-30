from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any, Callable

try:
    import flet as ft
except ModuleNotFoundError:  # pragma: no cover - test/runtime without optional desktop deps
    class _FallbackColors:
        ERROR = "error"
        PRIMARY = "primary"

    class _FallbackFlet:
        Colors = _FallbackColors

    ft = _FallbackFlet()

from ...core.content_monitor.models import DouyinMonitorAccount
from ...utils.logger import logger
from . import douyin_content_state as content_state


class DouyinContentAccountBatchController:
    """Account batch workflow adapter for the Douyin content monitor page.

    The page owns Flet controls and rendering. This controller owns account batch
    selection, queue execution, progress publishing and task-center snapshots.
    Keeping those rules here prevents the page from duplicating orchestration
    code across detect/sync/start/stop/delete entry points.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def parallel_limit(self) -> int:
        settings = getattr(self.owner.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        raw = config.get("monitor_batch_concurrency", config.get("douyin_content_monitor_batch_concurrency", 2))
        try:
            value = int(raw or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(8, value))

    def selected_accounts(self) -> list[DouyinMonitorAccount]:
        selected = set(getattr(self.owner, "selected_account_ids", set()) or set())
        return [account for account in self.owner.manager.accounts if account.account_id in selected]

    def latest_batch_result_lines(self) -> list[str]:
        owner = self.owner
        if owner.batch_result_lines:
            return list(owner.batch_result_lines)
        task_center = getattr(getattr(owner.app, "services", None), "task_center", None)
        snapshot = getattr(task_center, "snapshot", None)
        if not callable(snapshot):
            return []
        try:
            records = snapshot(limit=30)
        except Exception as exc:
            logger.debug(f"load latest batch task results failed: {exc}")
            return []
        lines: list[str] = []
        for record in records:
            if not isinstance(record, dict) or not self.is_batch_task_record(record):
                continue
            title = str(record.get("title") or "批量任务")
            status = str(record.get("status") or "-")
            detail = str(record.get("detail") or "").strip()
            updated = str(record.get("finished_at") or record.get("updated_at") or record.get("started_at") or "")
            completed = int(record.get("completed") or 0)
            total = int(record.get("total") or 0)
            success = int(record.get("success_count") or 0)
            failed = int(record.get("failed_count") or 0)
            progress = f"{completed}/{total}" if total else str(completed or "-")
            suffix = f"，{detail}" if detail else ""
            lines.append(f"[任务] {title}｜{status}｜进度 {progress}｜成功 {success}，失败 {failed}｜{updated}{suffix}")
            if len(lines) >= 20:
                break
        return lines

    @staticmethod
    def is_batch_task_record(record: dict[str, Any]) -> bool:
        title = str(record.get("title") or "")
        category = str(record.get("category") or "")
        retry_action = str(record.get("retry_action") or "")
        batch_markers = ("批量", "全部账号", "全部作品", "选中账号", "检测全部", "同步全部", "自动下载")
        return (
            any(marker in title for marker in batch_markers)
            or any(marker in category for marker in ("作品监控", "内容监控", "自动下载"))
            or retry_action in {"content_download_items", "content_sync_accounts", "content_check_accounts"}
        )

    @staticmethod
    def batch_failure_category(reason: str) -> str:
        return content_state.batch_failure_category(reason)

    @classmethod
    def batch_failure_advice(cls, reason: str) -> str:
        category = cls.batch_failure_category(reason)
        return {
            "risk_control": "疑似 IP / 风控限制，建议暂停当前批次、降低并发并等待冷却。",
            "cookie": "疑似 Cookie / 登录态异常，建议到设置页更新 Cookie 后重试。",
            "profile": "账号主页可能不可访问或无公开作品，建议打开主页确认。",
            "cancelled": "批量任务已按用户请求停止。",
        }.get(category, "可稍后重试；若多账号同时失败，建议先检查网络和 Cookie。")

    async def run_selected_job(self, title: str, category: str, job: Callable[[DouyinMonitorAccount], Any]) -> tuple[int, int, int]:
        return await self.run_batch(self.selected_accounts(), title, category, job)

    async def run_batch(
        self,
        accounts: list[DouyinMonitorAccount],
        title: str,
        category: str,
        job: Callable[[DouyinMonitorAccount], Any],
    ) -> tuple[int, int, int]:
        owner = self.owner
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        if owner.batch_job_running:
            await owner.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return 0, 0, 0
        owner.batch_job_running = True
        owner.batch_cancel_requested = False
        owner.batch_progress_cancelled = False
        owner._set_batch_progress_state(title=title, completed=0, total=len(accounts), success=0, failed=0, new_total=0)
        await owner.set_loading(True)
        await owner.render_current_view()
        task_center = getattr(owner.app.services, "task_center", None)
        task_id = task_center.start(title, category, total=len(accounts)) if task_center else None
        success = 0
        failed = 0
        new_total = 0
        completed = 0
        result_lines: list[str] = []
        cancelled = False
        queue: asyncio.Queue[DouyinMonitorAccount] = asyncio.Queue()
        for account in accounts:
            queue.put_nowait(account)
        progress_lock = asyncio.Lock()
        last_progress_update = 0.0
        concurrency = min(self.parallel_limit(), max(1, len(accounts)))

        async def publish_progress(current: str = "", *, force: bool = False, final: bool = False) -> None:
            nonlocal last_progress_update
            now = time.monotonic()
            if not force and not final and now - last_progress_update < 0.25:
                return
            last_progress_update = now
            owner._set_batch_progress_state(
                title=title,
                completed=completed,
                total=len(accounts),
                success=success,
                failed=failed,
                new_total=new_total,
                current=current,
                cancelled=cancelled,
                final=final,
            )
            if task_center and task_id:
                task_center.progress(
                    task_id,
                    completed=completed,
                    success_count=success,
                    failed_count=failed,
                    detail=owner.batch_progress_text,
                )
            owner._update_batch_progress_controls()
            await asyncio.sleep(0)

        async def worker() -> None:
            nonlocal success, failed, new_total, completed, cancelled
            while True:
                if owner.batch_cancel_requested:
                    cancelled = True
                    return
                try:
                    account = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                name = account.display_name or account.douyin_nickname or account.account_id
                try:
                    async with progress_lock:
                        await publish_progress(name, force=True)
                    result = job(account)
                    if inspect.isawaitable(result):
                        result = await result
                    ok = bool(result.get("success")) if isinstance(result, dict) else bool(result)
                    async with progress_lock:
                        completed += 1
                        if ok:
                            success += 1
                            reason = str(result.get("reason") or "成功") if isinstance(result, dict) else "成功"
                            result_lines.append(f"[成功] {name}：{reason}")
                            if isinstance(result, dict):
                                try:
                                    new_total += int(result.get("new") or len(result.get("new_items") or []))
                                except (TypeError, ValueError):
                                    pass
                        else:
                            failed += 1
                            reason = str(result.get("reason") or "失败") if isinstance(result, dict) else "失败"
                            result_lines.append(f"[失败] {name}：{reason}｜{self.batch_failure_advice(reason)}")
                        await publish_progress(name, force=True)
                except asyncio.CancelledError:
                    async with progress_lock:
                        cancelled = True
                        result_lines.append(f"[取消] {name}：任务已取消")
                        await publish_progress(name, force=True)
                    raise
                except Exception as exc:
                    async with progress_lock:
                        completed += 1
                        failed += 1
                        reason = str(exc) or exc.__class__.__name__
                        result_lines.append(f"[失败] {name}：{reason}｜{self.batch_failure_advice(reason)}")
                        await publish_progress(name, force=True)
                    logger.debug(f"{title} failed for account={account.account_id}: {exc}")
                finally:
                    try:
                        queue.task_done()
                    except ValueError:
                        pass

        workers = [asyncio.create_task(worker()) for _ in range(concurrency)]
        try:
            await asyncio.gather(*workers)
            if owner.batch_cancel_requested:
                cancelled = True
                result_lines.append("[取消] 用户已取消批量任务，未开始的账号已跳过")
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            if task_center and task_id:
                detail = f"已取消：成功 {success}，失败 {failed}，新增 {new_total}" if cancelled else f"完成：成功 {success}，失败 {failed}，新增 {new_total}"
                if cancelled and hasattr(task_center, "cancel"):
                    task_center.cancel(task_id, detail)
                else:
                    task_center.finish(task_id, success=(failed == 0 and not cancelled), detail=detail)
            owner.batch_result_lines = result_lines[-200:]
            owner._set_batch_progress_state(
                title=title,
                completed=completed,
                total=len(accounts),
                success=success,
                failed=failed,
                new_total=new_total,
                cancelled=cancelled,
                final=True,
            )
            owner.batch_job_running = False
            owner.batch_cancel_requested = False
            await owner.set_loading(False)
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                owner._pending_monitor_refresh = False
                await owner.render_current_view()
        return success, failed, new_total

    async def cancel_batch_job(self) -> None:
        owner = self.owner
        if not owner.batch_job_running:
            await owner.app.snack_bar.show_snack_bar("当前没有批量任务", bgcolor=ft.Colors.ERROR)
            return
        owner.batch_cancel_requested = True
        owner.batch_progress_cancelled = True
        owner._set_batch_progress_state(cancelled=True)
        owner._update_batch_progress_controls()
        await owner.app.snack_bar.show_snack_bar("已请求取消，等待中的账号会跳过，正在请求的账号完成后停止", bgcolor=ft.Colors.PRIMARY)

    async def start_selected_accounts(self) -> None:
        owner = self.owner
        accounts = self.selected_accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        if owner.batch_job_running:
            await owner.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return
        await owner.set_loading(True)
        try:
            result = await owner.manager.set_monitor_enabled_batch([account.account_id for account in accounts], True)
            changed = int(result.get("total") or 0) if isinstance(result, dict) else 0
            owner.batch_result_lines = [
                f"[成功] {account.display_name or account.douyin_nickname or account.account_id}：已开始监控"
                for account in accounts
                if account.monitor_enabled
            ][-200:]
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                await owner.render_current_view()
            await owner.app.snack_bar.show_snack_bar(
                f"批量开始监控完成：变更 {changed} 个账号，未变更 {max(0, len(accounts) - changed)} 个",
                bgcolor=ft.Colors.PRIMARY,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            await owner.set_loading(False)

    async def stop_selected_accounts(self, confirmed: bool = False) -> None:
        owner = self.owner
        if not owner.selected_account_ids:
            await owner.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        if owner.batch_job_running:
            await owner.app.snack_bar.show_snack_bar("已有批量任务正在运行", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            count = len(owner.selected_account_ids)
            owner.show_confirm_dialog(
                "确认批量停止",
                f"将停止监控 {count} 个账号，是否继续？",
                lambda: owner.stop_selected_accounts(confirmed=True),
            )
            return

        accounts = self.selected_accounts()
        await owner.set_loading(True)
        try:
            result = await owner.manager.set_monitor_enabled_batch([account.account_id for account in accounts], False)
            changed = int(result.get("total") or 0) if isinstance(result, dict) else 0
            owner.batch_result_lines = [
                f"[成功] {account.display_name or account.douyin_nickname or account.account_id}：已停止监控"
                for account in accounts
                if not account.monitor_enabled
            ][-200:]
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                await owner.render_current_view()
            await owner.app.snack_bar.show_snack_bar(
                f"批量停止监控完成：变更 {changed} 个账号，未变更 {max(0, len(accounts) - changed)} 个",
                bgcolor=ft.Colors.PRIMARY,
                duration=5000,
                show_close_icon=True,
            )
        finally:
            await owner.set_loading(False)

    async def check_selected_accounts(self) -> None:
        owner = self.owner
        success, failed, _new_total = await self.run_selected_job(
            "检测选中账号",
            "内容监控",
            lambda account: owner.manager.check_account(account.account_id, notify=True),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"检测选中完成：成功 {success}，失败 {failed}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def sync_selected_accounts(self) -> None:
        owner = self.owner
        success, failed, new_total = await self.run_selected_job(
            "同步选中账号作品",
            "作品监控",
            lambda account: owner.manager.sync_account_works(account.account_id),
        )
        if success or failed:
            await owner.app.snack_bar.show_snack_bar(
                f"同步选中完成：成功 {success}，失败 {failed}，新增 {new_total}",
                bgcolor=ft.Colors.PRIMARY if failed == 0 else ft.Colors.ERROR,
                duration=5000,
                show_close_icon=True,
            )

    async def delete_selected_accounts(self, confirmed: bool = False) -> None:
        owner = self.owner
        accounts = self.selected_accounts()
        if not accounts:
            await owner.app.snack_bar.show_snack_bar("请先选择账号", bgcolor=ft.Colors.ERROR)
            return
        if not confirmed:
            names = [account.display_name or account.douyin_nickname or account.homepage_url or account.account_id for account in accounts[:5]]
            suffix = "..." if len(accounts) > 5 else ""
            owner.show_confirm_dialog(
                "确认批量删除",
                f"将删除 {len(accounts)} 个账号及其监控记录：{', '.join(names)}{suffix}。是否继续？",
                lambda: owner.delete_selected_accounts(confirmed=True),
            )
            return
        await owner.set_loading(True)
        try:
            owner.recent_deleted_accounts = [account.to_dict() for account in accounts]
            owner.deleted_account_batches.append(owner.recent_deleted_accounts)
            owner.deleted_account_batches = owner.deleted_account_batches[-10:]
            result = await owner.manager.delete_accounts_batch([account.account_id for account in accounts])
            deleted_ids = set(result.get("account_ids") or []) if isinstance(result, dict) else set()
            deleted = int(result.get("deleted") or len(deleted_ids)) if isinstance(result, dict) else len(deleted_ids)
            lines = []
            for account in accounts:
                name = account.display_name or account.douyin_nickname or account.account_id
                if account.account_id in deleted_ids:
                    lines.append(f"[成功] {name}：已删除，可从恢复按钮找回")
                else:
                    lines.append(f"[失败] {name}：删除失败或账号不存在")
            owner.batch_result_lines = lines[-200:]
            owner.selected_account_ids.clear()
            if owner.selected_account_id and not owner.manager.find_account(owner.selected_account_id):
                owner.selected_account_id = None
            coordinator = getattr(owner, "refresh_coordinator", None)
            if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
                await coordinator.flush_after_long_task(force=True)
            else:
                await owner.render_current_view()
            await owner.app.snack_bar.show_snack_bar(f"已删除 {deleted} 个账号", bgcolor=ft.Colors.PRIMARY)
        finally:
            await owner.set_loading(False)
