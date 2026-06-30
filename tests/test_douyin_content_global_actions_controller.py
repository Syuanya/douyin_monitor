from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_global_actions_controller import DouyinContentGlobalActionsController


class SnackBar:
    def __init__(self):
        self.messages = []

    async def show_snack_bar(self, message, **kwargs):
        self.messages.append((message, kwargs))


class Manager:
    def __init__(self, accounts):
        self.accounts = accounts
        self.check_calls = []
        self.sync_calls = []
        self.start_all_calls = 0
        self.stop_all_calls = 0

    async def check_account(self, account_id, notify=False):
        self.check_calls.append((account_id, notify))
        return {"success": True, "reason": "正常"}

    async def sync_account_works(self, account_id):
        self.sync_calls.append(account_id)
        return {"success": True, "reason": "同步完成", "new": 1}

    async def start_all(self):
        self.start_all_calls += 1
        return {"total": len(self.accounts)}

    async def stop_all(self):
        self.stop_all_calls += 1
        return {"total": len(self.accounts)}


class AccountBatch:
    def __init__(self):
        self.calls = []

    async def run_batch(self, accounts, title, category, job):
        self.calls.append((accounts, title, category))
        success = 0
        failed = 0
        new_total = 0
        for account in accounts:
            result = await job(account)
            if result.get("success"):
                success += 1
                new_total += int(result.get("new") or 0)
            else:
                failed += 1
        return success, failed, new_total


def account(account_id, enabled=True):
    return SimpleNamespace(account_id=account_id, monitor_enabled=enabled)


def owner_with(accounts):
    owner = SimpleNamespace(
        manager=Manager(accounts),
        app=SimpleNamespace(snack_bar=SnackBar()),
        account_batch_controller=AccountBatch(),
        confirm_calls=[],
        loading_events=[],
        refresh_count=0,
        _={
            "batch_start_success": "批量开始监控完成：{total} 个",
            "batch_stop_success": "批量停止监控完成：{total} 个",
        },
    )

    def show_confirm_dialog(title, body, callback):
        owner.confirm_calls.append((title, body, callback))

    async def set_loading(value):
        owner.loading_events.append(value)

    async def refresh_view():
        owner.refresh_count += 1

    owner.show_confirm_dialog = show_confirm_dialog
    owner.set_loading = set_loading
    owner.refresh_view = refresh_view
    return owner


@pytest.mark.asyncio
async def test_check_all_enabled_only_runs_enabled_accounts():
    owner = owner_with([account("a1", True), account("a2", False)])
    controller = DouyinContentGlobalActionsController(owner)

    result = await controller.check_all_enabled()

    assert result == (1, 0, 0)
    assert owner.manager.check_calls == [("a1", True)]
    assert owner.account_batch_controller.calls[0][1] == "检测全部监控账号"
    assert "检测完成" in owner.app.snack_bar.messages[-1][0]


@pytest.mark.asyncio
async def test_check_all_enabled_handles_empty_enabled_list():
    owner = owner_with([account("a1", False)])
    controller = DouyinContentGlobalActionsController(owner)

    result = await controller.check_all_enabled()

    assert result == (0, 0, 0)
    assert owner.app.snack_bar.messages[-1][0] == "没有启用监控的账号"


@pytest.mark.asyncio
async def test_sync_all_requires_confirmation_before_heavy_request():
    owner = owner_with([account("a1", True), account("a2", True)])
    controller = DouyinContentGlobalActionsController(owner)

    result = await controller.sync_all_accounts(confirmed=False)

    assert result == (0, 0, 0)
    assert len(owner.confirm_calls) == 1
    assert owner.manager.sync_calls == []


@pytest.mark.asyncio
async def test_sync_all_confirmed_runs_all_accounts_and_summarizes_new_total():
    owner = owner_with([account("a1", True), account("a2", False)])
    controller = DouyinContentGlobalActionsController(owner)

    result = await controller.sync_all_accounts(confirmed=True)

    assert result == (2, 0, 2)
    assert owner.manager.sync_calls == ["a1", "a2"]
    assert owner.account_batch_controller.calls[0][1] == "同步全部账号作品"
    assert "新增 2" in owner.app.snack_bar.messages[-1][0]


@pytest.mark.asyncio
async def test_start_and_stop_all_delegate_to_manager_with_loading_feedback():
    owner = owner_with([account("a1"), account("a2")])
    controller = DouyinContentGlobalActionsController(owner)

    started = await controller.start_all()
    stopped = await controller.stop_all()

    assert (started, stopped) == (2, 2)
    assert owner.manager.start_all_calls == 1
    assert owner.manager.stop_all_calls == 1
    assert owner.loading_events == [True, False, True, False]
    assert owner.refresh_count == 2
