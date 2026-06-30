from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_account_controller import DouyinContentAccountController


class SnackBar:
    def __init__(self):
        self.messages = []

    async def show_snack_bar(self, message, **kwargs):
        self.messages.append((message, kwargs))


class Manager:
    def __init__(self):
        self.account = SimpleNamespace(
            account_id="a1",
            display_name="账号1",
            douyin_nickname="",
            homepage_url="https://example.com/a1",
            monitor_enabled=True,
            monitor_history=[],
            to_dict=lambda: {"account_id": "a1"},
        )
        self.stop_calls = []
        self.start_calls = []
        self.delete_calls = []
        self.restored = []

    def find_account(self, account_id):
        return self.account if self.account and account_id == self.account.account_id else None

    async def stop_monitor(self, account_id):
        self.stop_calls.append(account_id)
        self.account.monitor_enabled = False

    async def start_monitor(self, account_id):
        self.start_calls.append(account_id)
        self.account.monitor_enabled = True

    async def delete_account(self, account_id):
        self.delete_calls.append(account_id)
        self.account = None

    async def restore_accounts(self, data):
        self.restored.append(data)
        return len(data)


@pytest.mark.asyncio
async def test_toggle_monitor_uses_owner_messages_and_refreshes():
    manager = Manager()
    owner = SimpleNamespace(
        manager=manager,
        _={"stop_success": "已停止监控", "start_success": "已开始监控"},
        app=SimpleNamespace(snack_bar=SnackBar()),
        refresh_count=0,
    )

    async def refresh_view():
        owner.refresh_count += 1

    owner.refresh_view = refresh_view
    controller = DouyinContentAccountController(owner)

    await controller.toggle_monitor("a1", True)

    assert manager.stop_calls == ["a1"]
    assert owner.refresh_count == 1
    assert owner.app.snack_bar.messages[-1][0] == "已停止监控"


@pytest.mark.asyncio
async def test_delete_account_keeps_restore_snapshot():
    manager = Manager()
    owner = SimpleNamespace(
        manager=manager,
        _={"delete_success": "已删除"},
        app=SimpleNamespace(snack_bar=SnackBar()),
        selected_account_id="a1",
        recent_deleted_accounts=[],
        deleted_account_batches=[],
        refresh_count=0,
    )

    async def refresh_view():
        owner.refresh_count += 1

    owner.refresh_view = refresh_view
    controller = DouyinContentAccountController(owner)

    await controller.delete_account("a1", confirmed=True)

    assert manager.delete_calls == ["a1"]
    assert owner.selected_account_id is None
    assert owner.recent_deleted_accounts == [{"account_id": "a1"}]
    assert owner.deleted_account_batches == [[{"account_id": "a1"}]]
    assert owner.refresh_count == 1
