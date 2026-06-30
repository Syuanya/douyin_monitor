from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_error_repair_controller import DouyinContentErrorRepairController


class SnackBar:
    def __init__(self):
        self.messages: list[str] = []

    async def show_snack_bar(self, message, **_kwargs):
        self.messages.append(message)


def account(account_id: str, status: str = "异常", last_error: str = ""):
    return SimpleNamespace(
        account_id=account_id,
        display_name=account_id,
        douyin_nickname="",
        homepage_url=f"https://example.com/{account_id}",
        status=status,
        last_error=last_error,
    )


def owner_with_errors():
    owner = SimpleNamespace(
        manager=SimpleNamespace(
            accounts=[
                account("cookie", last_error="Cookie 失效"),
                account("risk", last_error="空响应 429 风控"),
                account("ok", status="active", last_error=""),
            ]
        ),
        app=SimpleNamespace(snack_bar=SnackBar()),
        copied="",
    )

    async def copy_text(text: str):
        owner.copied = text

    owner.copy_text = copy_text
    return owner


def test_error_accounts_and_summary_classify_actionable_buckets():
    owner = owner_with_errors()
    controller = DouyinContentErrorRepairController(owner)

    assert [item.account_id for item in controller.accounts()] == ["cookie", "risk"]
    assert controller.summary()["cookie"] == 1
    assert controller.summary()["risk_control"] == 1


@pytest.mark.asyncio
async def test_copy_summary_contains_bucket_and_homepage():
    owner = owner_with_errors()
    controller = DouyinContentErrorRepairController(owner)

    await controller.copy_summary()

    assert "[cookie] cookie" in owner.copied
    assert "[risk_control] risk" in owner.copied
    assert "https://example.com/risk" in owner.copied
