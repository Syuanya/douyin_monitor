from __future__ import annotations

from pathlib import Path


def test_settings_page_does_not_mount_native_switches() -> None:
    text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")
    assert "ft.Switch" not in text
    assert "_make_toggle_button" in text
    assert "_toggle_values" in text
    assert "_set_toggle_value" in text


def test_account_notify_list_is_paginated_and_state_backed() -> None:
    text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")
    assert "ACCOUNT_NOTIFY_PAGE_SIZE = 20" in text
    assert "ACCOUNT_NOTIFY_LIST_HEIGHT" in text
    assert "account_notify_values" in text
    assert "_account_notify_page_accounts" in text
    assert "filter_account_notify_list" in text
    assert "set_filtered_account_notify" in text
    account_block = text.split("def _account_notify_controls", 1)[1].split("def _begin_edit_tracking", 1)[0]
    assert "ft.Switch" not in account_block
    assert "ft.OutlinedButton" in account_block
    assert "height=420" not in account_block
    assert "len(accounts) > self.ACCOUNT_NOTIFY_PAGE_SIZE" not in account_block
    assert "scroll=ft.ScrollMode.AUTO" in account_block
    assert "clip_behavior=ft.ClipBehavior.HARD_EDGE" in account_block
