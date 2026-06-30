from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_add_account_controller import DouyinContentAddAccountController


class Manager:
    def __init__(self, *, hydrate_success=True):
        self.account = SimpleNamespace(account_id="a1", display_name="", douyin_nickname="舞蹈号")
        self.add_calls = []
        self.hydrate_calls = []
        self.hydrate_success = hydrate_success

    async def add_account(self, url, name):
        self.add_calls.append((url, name))
        self.account.display_name = name or ""
        return self.account

    async def hydrate_account_display_name(self, account_id, force=False):
        self.hydrate_calls.append((account_id, force))
        if self.hydrate_success:
            self.account.display_name = "舞蹈号"
        return {"success": self.hydrate_success}

    def find_account(self, account_id):
        return self.account if account_id == self.account.account_id else None


@pytest.mark.asyncio
async def test_add_account_with_manual_name_skips_hydration():
    owner = SimpleNamespace(manager=Manager())
    controller = DouyinContentAddAccountController(owner)

    account, message = await controller.add_account_with_auto_name("https://example.com/u", "备注")

    assert account.account_id == "a1"
    assert message == "已添加抖音监控用户"
    assert owner.manager.add_calls == [("https://example.com/u", "备注")]
    assert owner.manager.hydrate_calls == []


@pytest.mark.asyncio
async def test_add_account_auto_fills_nickname_when_no_manual_name():
    owner = SimpleNamespace(manager=Manager())
    controller = DouyinContentAddAccountController(owner)

    account, message = await controller.add_account_with_auto_name("https://example.com/u", "")

    assert account.display_name == "舞蹈号"
    assert "自动填充昵称" in message
    assert owner.manager.hydrate_calls == [("a1", True)]
