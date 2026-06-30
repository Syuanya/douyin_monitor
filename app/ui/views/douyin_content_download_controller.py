from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from . import douyin_content_state as content_state


class DouyinContentDownloadController:
    """Download workflow adapter for the Douyin content monitor page.

    The Flet page still owns UI rendering and snackbars. This controller owns the
    batch-download selection, concurrency and task-center progress mechanics so
    the page does not duplicate queue orchestration logic.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    def parallel_limit(self) -> int:
        settings = getattr(self.owner.app.services, "settings_config", None)
        config = getattr(settings, "user_config", {}) if settings is not None else {}
        try:
            value = int(config.get("batch_download_concurrency", config.get("max_parallel_downloads", 3)) or 3)
        except (TypeError, ValueError):
            value = 3
        return max(1, min(12, value))

    def filter_items(self, account: Any, filter_mode: str) -> list[Any]:
        sorted_items = self.owner.manager.sort_items_newest_first(getattr(account, "items", []) or [])
        return content_state.filter_download_items(sorted_items, filter_mode)

    @staticmethod
    def filter_label(filter_mode: str) -> str:
        return content_state.download_filter_label(filter_mode)

    @staticmethod
    def download_location(path: str) -> str:
        text = os.path.abspath(os.path.expanduser(str(path or "").strip()))
        if os.path.isfile(text):
            return os.path.dirname(text)
        return text

    async def run_items_until_stopped(self, account_id: str, item_ids: list[str]) -> tuple[int, int, bool]:
        owner = self.owner
        success = 0
        failed = 0
        stopped = False
        failed_reasons: list[str] = []
        failed_item_ids: list[str] = []
        unique_ids = list(dict.fromkeys(item_ids))
        total = len(unique_ids)
        if total <= 0:
            owner.download_failure_reasons = []
            owner.download_progress_text = "下载进度：0/0"
            return 0, 0, False

        task_center = getattr(owner.app.services, "task_center", None)
        task_id = None
        if task_center is not None:
            account = owner.manager.find_account(account_id)
            name = (account.display_name or account.douyin_nickname or account.account_id) if account else account_id
            task_id = task_center.start(
                f"批量下载：{name}",
                "内容监控下载",
                total=total,
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids},
            )

        queue: asyncio.Queue[str] = asyncio.Queue()
        for item_id in unique_ids:
            queue.put_nowait(item_id)

        refresh_lock = asyncio.Lock()
        last_refresh = 0.0

        async def maybe_refresh(done: int) -> None:
            nonlocal last_refresh
            now = time.monotonic()
            if done < total and now - last_refresh < 0.8:
                return
            async with refresh_lock:
                now = time.monotonic()
                if done < total and now - last_refresh < 0.8:
                    return
                try:
                    await owner.render_current_view()
                    last_refresh = now
                except Exception:
                    pass

        def task_retry_payload() -> dict[str, Any]:
            return {
                "account_id": account_id,
                "item_ids": failed_item_ids or unique_ids,
                "all_item_ids": unique_ids,
                "failed_item_ids": failed_item_ids,
            }

        async def worker() -> None:
            nonlocal success, failed, stopped
            while not owner.download_stop_requested:
                try:
                    item_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    try:
                        result = await owner.manager.download_item(account_id, item_id)
                    except asyncio.CancelledError:
                        stopped = True
                        return
                    except Exception as exc:
                        result = {"success": False, "reason": str(exc) or exc.__class__.__name__}

                    if result.get("success"):
                        success += 1
                    else:
                        failed += 1
                        failed_item_ids.append(item_id)
                        failed_reasons.append(f"{item_id}：{result.get('reason') or '下载失败'}")

                    done = success + failed
                    account = owner.manager.find_account(account_id)
                    item = next(
                        (candidate for candidate in getattr(account, "items", []) or [] if getattr(candidate, "item_id", "") == item_id),
                        None,
                    ) if account else None
                    title = (getattr(item, "title", "") or item_id)[:40]
                    owner.download_progress_text = f"下载进度：{done}/{total}，当前 {title}，成功 {success}，失败 {failed}"
                    if task_center is not None and task_id:
                        task_center.progress(
                            task_id,
                            completed=done,
                            success_count=success,
                            failed_count=failed,
                            detail=owner.download_progress_text,
                            retry_payload=task_retry_payload(),
                        )
                    await maybe_refresh(done)
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(self.parallel_limit(), max(1, total)))]
        try:
            await asyncio.gather(*workers)
        finally:
            for task in workers:
                if not task.done():
                    task.cancel()
            while not queue.empty():
                try:
                    queue.get_nowait()
                    queue.task_done()
                except asyncio.QueueEmpty:
                    break

        if owner.download_stop_requested:
            stopped = True
        if task_center is not None and task_id:
            retry_payload = task_retry_payload()
            if hasattr(task_center, "update_retry_payload"):
                task_center.update_retry_payload(task_id, retry_payload)
            if stopped and hasattr(task_center, "cancel"):
                task_center.cancel(task_id, "下载已停止")
            else:
                task_center.finish(
                    task_id,
                    success=(failed == 0 and not stopped),
                    detail=owner.download_progress_text,
                )
        owner.download_failure_reasons = failed_reasons[-100:]
        coordinator = getattr(owner, "refresh_coordinator", None)
        if coordinator is not None and hasattr(coordinator, "flush_after_long_task"):
            await coordinator.flush_after_long_task(force=True)
        else:
            try:
                await owner.render_current_view()
            except Exception:
                pass
        return success, failed, stopped
