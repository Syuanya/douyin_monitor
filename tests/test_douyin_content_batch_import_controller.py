from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_batch_import_controller import DouyinContentBatchImportController


class SnackBar:
    def __init__(self):
        self.messages = []

    async def show_snack_bar(self, message, **kwargs):
        self.messages.append((message, kwargs))


class DialogArea:
    def __init__(self):
        self.updated = 0
        self.content = None

    def update(self):
        self.updated += 1


class Manager:
    def __init__(self):
        self.accounts = []
        self.add_calls = []
        self.settings_calls = []
        self.start_calls = []
        self.hydrate_calls = []

    async def add_account(self, url, name):
        self.add_calls.append((url, name))
        existing = next((a for a in self.accounts if a.homepage_url.rstrip("/") == url.rstrip("/")), None)
        if existing:
            existing.display_name = name or existing.display_name
            return existing
        account = SimpleNamespace(
            account_id=f"a{len(self.accounts) + 1}",
            homepage_url=url,
            display_name=name or "",
            douyin_nickname="",
        )
        self.accounts.append(account)
        return account

    async def update_account_settings(self, account_id, **kwargs):
        self.settings_calls.append((account_id, kwargs))
        account = next(a for a in self.accounts if a.account_id == account_id)
        account.display_name = kwargs.get("display_name") or account.display_name
        return {"success": True}

    async def start_monitor(self, account_id):
        self.start_calls.append(account_id)
        return {"success": True}

    async def hydrate_account_display_name(self, account_id, force=False):
        self.hydrate_calls.append((account_id, force))
        return {"success": True}


def control(value=None):
    return SimpleNamespace(value=value, color=None, update=lambda: None)


def controls(text, *, group="默认组", start=False, notify=True, policy="video"):
    return SimpleNamespace(
        text_field=control(text),
        file_path_field=control(""),
        preview_text=control(""),
        default_group=control(group),
        start_switch=control(start),
        notify_switch=control(notify),
        policy_dropdown=control(policy),
        dialog=SimpleNamespace(open=True),
    )


def owner_with(manager=None):
    owner = SimpleNamespace(
        manager=manager or Manager(),
        app=SimpleNamespace(snack_bar=SnackBar(), dialog_area=DialogArea()),
        render_count=0,
        batch_result_lines=[],
        run_async=lambda coro: coro,
    )

    async def render_current_view():
        owner.render_count += 1

    owner.render_current_view = render_current_view
    return owner


def test_parse_rows_uses_core_import_parser_and_existing_accounts():
    manager = Manager()
    manager.accounts.append(SimpleNamespace(account_id="old", homepage_url="https://www.douyin.com/user/MS4wLjABAAAAabc"))
    owner = owner_with(manager)
    controller = DouyinContentBatchImportController(owner)

    rows = controller.parse_rows("https://www.douyin.com/user/MS4wLjABAAAAabc?from=copy, 新名称, A组")

    assert rows == [
        {
            "url": "https://www.douyin.com/user/MS4wLjABAAAAabc",
            "name": "新名称",
            "group": "A组",
            "action": "update",
            "reason": "已存在，将更新设置",
        }
    ]


@pytest.mark.asyncio
async def test_load_preview_reads_text_and_default_group():
    owner = owner_with()
    controller = DouyinContentBatchImportController(owner)
    ui = controls("https://www.douyin.com/user/MS4wLjABAAAAdef, 账号B", group="素材组")

    preview = await controller.load_preview(ui)

    assert preview.counts()["add"] == 1
    assert preview.valid_rows[0].group == "素材组"


@pytest.mark.asyncio
async def test_submit_import_updates_settings_and_can_start_monitoring():
    owner = owner_with()
    controller = DouyinContentBatchImportController(owner)
    ui = controls("https://www.douyin.com/user/MS4wLjABAAAAdef, 账号B, 分组B", start=True, policy="all")
    closed = []

    async def close_dialog():
        closed.append(True)

    result = await controller.submit(ui, close_dialog=close_dialog)

    assert result["added"] == 1
    assert result["updated"] == 0
    assert result["failed"] == 0
    assert owner.manager.add_calls == [("https://www.douyin.com/user/MS4wLjABAAAAdef", "账号B")]
    assert owner.manager.settings_calls[0][1]["group_name"] == "分组B"
    assert owner.manager.settings_calls[0][1]["auto_download_policy"] == "all"
    assert owner.manager.start_calls == ["a1"]
    assert closed == [True]
    assert owner.render_count == 1
    assert "导入执行" in owner.batch_result_lines[1]


@pytest.mark.asyncio
async def test_hydrate_account_names_reports_result():
    owner = owner_with()
    controller = DouyinContentBatchImportController(owner)

    success, failed = await controller.hydrate_account_names(["a1"])

    assert (success, failed) == (1, 0)
    assert owner.manager.hydrate_calls == [("a1", True)]
    assert "批量昵称后台补全完成" in owner.app.snack_bar.messages[-1][0]
