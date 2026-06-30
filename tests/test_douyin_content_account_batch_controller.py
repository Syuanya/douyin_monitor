from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_account_batch_controller import DouyinContentAccountBatchController


class SnackBar:
    def __init__(self):
        self.messages = []

    async def show_snack_bar(self, message, **kwargs):
        self.messages.append((message, kwargs))


class TaskCenter:
    def __init__(self):
        self.started = []
        self.progresses = []
        self.finished = []
        self.cancelled = []

    def start(self, title, category, total=0, **kwargs):
        self.started.append({"title": title, "category": category, "total": total, **kwargs})
        return "task-1"

    def progress(self, task_id, **kwargs):
        self.progresses.append({"task_id": task_id, **kwargs})

    def finish(self, task_id, **kwargs):
        self.finished.append({"task_id": task_id, **kwargs})

    def cancel(self, task_id, reason):
        self.cancelled.append({"task_id": task_id, "reason": reason})

    def snapshot(self, limit=30):
        return [
            {
                "title": "检测选中账号",
                "category": "内容监控",
                "status": "finished",
                "completed": 2,
                "total": 2,
                "success_count": 1,
                "failed_count": 1,
                "detail": "完成：成功 1，失败 1",
                "updated_at": "2026-06-30 10:00",
            }
        ]


class Manager:
    def __init__(self, accounts):
        self.accounts = accounts
        self.enabled_calls = []
        self.delete_calls = []

    async def set_monitor_enabled_batch(self, account_ids, enabled):
        self.enabled_calls.append((list(account_ids), enabled))
        for account in self.accounts:
            if account.account_id in account_ids:
                account.monitor_enabled = enabled
        return {"total": len(account_ids), "account_ids": list(account_ids)}

    async def delete_accounts_batch(self, account_ids):
        self.delete_calls.append(list(account_ids))
        self.accounts = [account for account in self.accounts if account.account_id not in account_ids]
        return {"deleted": len(account_ids), "account_ids": list(account_ids)}

    def find_account(self, account_id):
        return next((account for account in self.accounts if account.account_id == account_id), None)


def account(account_id, *, monitor_enabled=True):
    return SimpleNamespace(
        account_id=account_id,
        display_name=f"账号{account_id}",
        douyin_nickname="",
        homepage_url=f"https://example.com/{account_id}",
        monitor_enabled=monitor_enabled,
        to_dict=lambda: {"account_id": account_id},
    )


def owner_with(*, settings=None, accounts=None, task_center=None, selected=None):
    accounts = accounts or [account("a1"), account("a2")]
    snack_bar = SnackBar()
    services = SimpleNamespace(settings_config=SimpleNamespace(user_config=settings or {}), task_center=task_center)
    owner = SimpleNamespace(
        app=SimpleNamespace(services=services, snack_bar=snack_bar),
        manager=Manager(accounts),
        selected_account_ids=set(selected or []),
        selected_account_id=None,
        batch_job_running=False,
        batch_cancel_requested=False,
        batch_progress_cancelled=False,
        batch_result_lines=[],
        batch_progress_text="",
        recent_deleted_accounts=[],
        deleted_account_batches=[],
        loading_events=[],
        render_count=0,
        progress_states=[],
        progress_updates=0,
        confirm_calls=[],
        _pending_monitor_refresh=False,
    )

    async def set_loading(value):
        owner.loading_events.append(value)

    async def render_current_view():
        owner.render_count += 1

    def set_progress_state(**kwargs):
        owner.progress_states.append(kwargs)
        total = kwargs.get("total", 0) or 0
        completed = kwargs.get("completed", 0) or 0
        success = kwargs.get("success", 0) or 0
        failed = kwargs.get("failed", 0) or 0
        owner.batch_progress_text = f"进度 {completed}/{total}，成功 {success}，失败 {failed}"
        owner.batch_progress_cancelled = bool(kwargs.get("cancelled", owner.batch_progress_cancelled))

    def update_progress_controls():
        owner.progress_updates += 1

    def show_confirm_dialog(title, body, callback):
        owner.confirm_calls.append((title, body, callback))

    owner.set_loading = set_loading
    owner.render_current_view = render_current_view
    owner._set_batch_progress_state = set_progress_state
    owner._update_batch_progress_controls = update_progress_controls
    owner.show_confirm_dialog = show_confirm_dialog
    return owner


def test_parallel_limit_and_selection_are_owned_by_controller():
    owner = owner_with(settings={"monitor_batch_concurrency": "99"}, selected={"a2"})
    controller = DouyinContentAccountBatchController(owner)

    assert controller.parallel_limit() == 8
    assert [account.account_id for account in controller.selected_accounts()] == ["a2"]


def test_latest_batch_result_lines_reads_task_center_snapshot():
    owner = owner_with(task_center=TaskCenter())
    controller = DouyinContentAccountBatchController(owner)

    lines = controller.latest_batch_result_lines()

    assert len(lines) == 1
    assert "检测选中账号" in lines[0]
    assert "成功 1，失败 1" in lines[0]


def test_batch_failure_advice_is_user_actionable():
    assert "Cookie" in DouyinContentAccountBatchController.batch_failure_advice("Cookie 登录态失效")
    assert "降低并发" in DouyinContentAccountBatchController.batch_failure_advice("429 风控验证")
    assert DouyinContentAccountBatchController.is_batch_task_record({"retry_action": "content_check_accounts"})


@pytest.mark.asyncio
async def test_run_batch_updates_task_center_and_result_lines():
    task_center = TaskCenter()
    owner = owner_with(task_center=task_center, selected={"a1", "a2"})
    controller = DouyinContentAccountBatchController(owner)

    async def job(target):
        if target.account_id == "a1":
            return {"success": True, "reason": "正常", "new": 2}
        return {"success": False, "reason": "Cookie 失效"}

    success, failed, new_total = await controller.run_selected_job("检测选中账号", "内容监控", job)

    assert (success, failed, new_total) == (1, 1, 2)
    assert task_center.started[0]["total"] == 2
    assert task_center.finished[-1]["success"] is False
    assert any("[失败]" in line and "Cookie" in line for line in owner.batch_result_lines)
    assert owner.batch_job_running is False
    assert owner.loading_events[0] is True and owner.loading_events[-1] is False


@pytest.mark.asyncio
async def test_delete_selected_accounts_uses_manager_and_keeps_restore_snapshot():
    owner = owner_with(selected={"a1"})
    controller = DouyinContentAccountBatchController(owner)

    await controller.delete_selected_accounts(confirmed=True)

    assert owner.manager.delete_calls == [["a1"]]
    assert owner.recent_deleted_accounts == [{"account_id": "a1"}]
    assert owner.selected_account_ids == set()
    assert owner.app.snack_bar.messages[-1][0] == "已删除 1 个账号"
