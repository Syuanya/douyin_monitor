from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_work_controller import DouyinContentWorkController


def item(item_id, status="", first_seen_time=""):
    return SimpleNamespace(
        item_id=item_id,
        status=status,
        first_seen_time=first_seen_time,
        publish_time=first_seen_time,
        media_type="video",
        image_urls=[],
    )


class Manager:
    def __init__(self, account):
        self.account = account

    def find_account(self, account_id):
        return self.account if account_id == self.account.account_id else None

    def sort_items_newest_first(self, items):
        return sorted(items, key=lambda work: work.first_seen_time, reverse=True)


def owner_with():
    works = [
        item("old", "new", "2026-06-29 10:00"),
        item("failed", "download_failed", "2026-06-30 11:00"),
        item("new", "new", "2026-06-30 12:00"),
    ]
    account = SimpleNamespace(account_id="a1", items=works)
    owner = SimpleNamespace(
        manager=Manager(account),
        selected_account_id="a1",
        work_filter="new",
        visible_work_count=2,
        selected_work_ids=set(),
        work_select_mode=False,
        view_mode="works",
        work_page_size=20,
        inbox_visible_count=20,
        history_area=SimpleNamespace(updated=0, update=lambda: None),
        refresh_works_count=0,
        refresh_inbox_count=0,
        render_count=0,
        safe_update_count=0,
    )

    async def refresh_works():
        owner.refresh_works_count += 1

    async def refresh_new_work_inbox():
        owner.refresh_inbox_count += 1

    async def render_current_view():
        owner.render_count += 1

    def safe_content_update():
        owner.safe_update_count += 1

    owner.refresh_works = refresh_works
    owner.refresh_new_work_inbox = refresh_new_work_inbox
    owner.render_current_view = render_current_view
    owner.safe_content_update = safe_content_update
    return owner


def test_visible_items_reuses_filtering_and_sorting():
    owner = owner_with()
    controller = DouyinContentWorkController(owner)

    assert [work.item_id for work in controller.visible_items()] == ["new", "old"]
    assert [work.item_id for work in controller.filter_items(owner.manager.account.items, "failed")] == ["failed"]


@pytest.mark.asyncio
async def test_select_all_visible_toggles_current_window_only():
    owner = owner_with()
    controller = DouyinContentWorkController(owner)

    await controller.select_all_visible()
    assert owner.selected_work_ids == {"new", "old"}
    assert owner.refresh_works_count == 1

    await controller.select_all_visible()
    assert owner.selected_work_ids == set()


@pytest.mark.asyncio
async def test_load_more_and_select_mode_delegate_refreshing():
    owner = owner_with()
    controller = DouyinContentWorkController(owner)

    await controller.load_more()
    assert owner.visible_work_count == 22
    assert owner.refresh_works_count == 1

    await controller.toggle_select_mode()
    assert owner.work_select_mode is True
    assert owner.safe_update_count == 1

    await controller.toggle_selected("new")
    assert owner.selected_work_ids == {"new"}
    assert owner.render_count == 1
