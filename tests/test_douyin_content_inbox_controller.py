from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_inbox_controller import DouyinContentInboxController


def item(item_id: str, status: str, first_seen_time: str = "2026-06-30 12:00"):
    return SimpleNamespace(
        item_id=item_id,
        status=status,
        first_seen_time=first_seen_time,
        publish_time=first_seen_time,
        media_type="video",
        image_urls=[],
    )


class Manager:
    def __init__(self, accounts):
        self.accounts = accounts
        self.persist_count = 0

    def find_account(self, account_id):
        return next((account for account in self.accounts if account.account_id == account_id), None)

    async def persist(self, force: bool = False):
        self.persist_count += 1


class SnackBar:
    def __init__(self):
        self.messages: list[str] = []

    async def show_snack_bar(self, message, **_kwargs):
        self.messages.append(message)


async def noop_render():
    return None


def owner_with_items():
    account = SimpleNamespace(
        account_id="a1",
        display_name="账号A",
        douyin_nickname="账号A",
        items=[item("failed", "download_failed"), item("new", "new", "2026-06-30 13:00"), item("old", "active")],
        last_new_count=0,
    )
    owner = SimpleNamespace(
        manager=Manager([account]),
        app=SimpleNamespace(snack_bar=SnackBar()),
        render_current_view=noop_render,
    )
    return owner, account


def test_entries_keep_failed_downloads_as_pending_new_work():
    owner, _account = owner_with_items()
    controller = DouyinContentInboxController(owner)

    assert [entry[1].item_id for entry in controller.entries()] == ["new", "failed"]


@pytest.mark.asyncio
async def test_mark_failed_inbox_item_seen_resets_to_active_and_persists():
    owner, account = owner_with_items()
    controller = DouyinContentInboxController(owner)

    await controller.mark_item_seen("a1", "failed")

    assert account.items[0].status == "active"
    assert account.last_new_count == 1
    assert owner.manager.persist_count == 1
    assert owner.app.snack_bar.messages[-1] == "已标记为已处理"


@pytest.mark.asyncio
async def test_mark_all_seen_handles_failed_and_new_items():
    owner, account = owner_with_items()
    controller = DouyinContentInboxController(owner)

    await controller.mark_all_seen()

    assert [work.status for work in account.items] == ["active", "active", "active"]
    assert account.last_new_count == 0
    assert owner.manager.persist_count == 1
