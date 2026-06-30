from __future__ import annotations

from typing import Any

from . import douyin_content_state as content_state


class DouyinContentWorkController:
    """Work-list state adapter for the Douyin content monitor page.

    It owns filtering, visible-window selection and bulk-select state for the
    selected account's work list. Rendering remains in the Flet page.
    """

    def __init__(self, owner: Any) -> None:
        self.owner = owner

    @staticmethod
    def filter_items(items: list[Any], mode: str) -> list[Any]:
        return content_state.filter_work_items(items, mode)

    def selected_account(self) -> Any | None:
        account_id = getattr(self.owner, "selected_account_id", None)
        if not account_id:
            return None
        return self.owner.manager.find_account(account_id)

    def visible_items(self) -> list[Any]:
        account = self.selected_account()
        if account is None:
            return []
        filtered = self.filter_items(list(getattr(account, "items", []) or []), getattr(self.owner, "work_filter", "all"))
        sorted_items = self.owner.manager.sort_items_newest_first(filtered)
        return sorted_items[: int(getattr(self.owner, "visible_work_count", 0) or 0)]

    async def load_more(self) -> None:
        owner = self.owner
        if owner.view_mode == "inbox":
            owner.inbox_visible_count += owner.work_page_size
            await owner.refresh_new_work_inbox()
        else:
            owner.visible_work_count += owner.work_page_size
            await owner.refresh_works()
        if owner.history_area:
            owner.history_area.update()

    async def toggle_select_mode(self) -> None:
        owner = self.owner
        owner.work_select_mode = not owner.work_select_mode
        if not owner.work_select_mode:
            owner.selected_work_ids.clear()
        await owner.refresh_works()
        if owner.history_area:
            owner.history_area.update()
        owner.safe_content_update()

    async def toggle_selected(self, item_id: str, selected: bool | None = None) -> None:
        owner = self.owner
        should_select = item_id not in owner.selected_work_ids if selected is None else selected
        if should_select:
            owner.selected_work_ids.add(item_id)
        else:
            owner.selected_work_ids.discard(item_id)
        await owner.render_current_view()

    async def clear_selected(self) -> None:
        self.owner.selected_work_ids.clear()
        await self.owner.render_current_view()

    async def select_all_visible(self) -> None:
        owner = self.owner
        visible_ids = {item.item_id for item in self.visible_items()}
        if owner.selected_work_ids >= visible_ids and visible_ids:
            owner.selected_work_ids.difference_update(visible_ids)
        else:
            owner.selected_work_ids.update(visible_ids)
        await owner.refresh_works()
        if owner.history_area:
            owner.history_area.update()
