from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_batch_settings_controller import DouyinContentBatchSettingsController


class Manager:
    def __init__(self, accounts, *, batch=True):
        self.accounts = accounts
        self.batch = batch
        self.batch_calls = []
        self.single_calls = []

    async def update_account_settings_batch(self, account_ids, **payload):
        if not self.batch:
            raise AttributeError("disabled")
        self.batch_calls.append((list(account_ids), payload))
        return {"updated": len(account_ids), "changed": 1}

    async def update_account_settings(self, account_id, **payload):
        self.single_calls.append((account_id, payload))
        return True


def account(account_id):
    return SimpleNamespace(account_id=account_id)


def owner_with(*, batch=True):
    accounts = [account("a1"), account("a2")]
    owner = SimpleNamespace(manager=Manager(accounts, batch=batch), selected_account_ids={"a1", "a2"})
    return owner


def test_build_update_payload_preserves_unchecked_fields():
    payload = DouyinContentBatchSettingsController.build_update_payload(
        update_group=True,
        group_name="  素材组  ",
        update_policy=False,
        policy="video",
        update_notify=True,
        notify="off",
    )

    assert payload == {"group_name": "素材组", "auto_download_policy": None, "notify_enabled": False}
    assert DouyinContentBatchSettingsController.selected_update_count(payload) == 2


@pytest.mark.asyncio
async def test_apply_settings_uses_batch_api_when_available():
    owner = owner_with(batch=True)
    controller = DouyinContentBatchSettingsController(owner)
    accounts = controller.selected_accounts()

    result = await controller.apply_settings(accounts, {"group_name": "A", "auto_download_policy": None, "notify_enabled": None})

    assert result == {"updated": 2, "changed": 1}
    assert owner.manager.batch_calls[0][0] == ["a1", "a2"]


@pytest.mark.asyncio
async def test_apply_settings_falls_back_to_single_account_updates():
    class SingleManager:
        def __init__(self, accounts):
            self.accounts = accounts
            self.single_calls = []

        async def update_account_settings(self, account_id, **payload):
            self.single_calls.append((account_id, payload))
            return True

    owner = SimpleNamespace(manager=SingleManager([account("a1"), account("a2")]), selected_account_ids={"a1"})
    controller = DouyinContentBatchSettingsController(owner)

    result = await controller.apply_settings(controller.selected_accounts(), {"notify_enabled": True})

    assert result == {"updated": 1, "changed": 1}
    assert owner.manager.single_calls == [("a1", {"notify_enabled": True})]
