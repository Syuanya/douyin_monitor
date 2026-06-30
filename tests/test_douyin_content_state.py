from types import SimpleNamespace

from app.ui.views import douyin_content_state as state


def item(status="", media_type="video", image_urls=None, item_id="i", first_seen_time=""):
    return SimpleNamespace(
        status=status,
        media_type=media_type,
        image_urls=image_urls or [],
        item_id=item_id,
        first_seen_time=first_seen_time,
        publish_time=first_seen_time,
    )


def account(account_id="a", *, items=None, monitor_enabled=True, group_name="", display_name="", status="", last_error=""):
    return SimpleNamespace(
        account_id=account_id,
        items=items or [],
        monitor_enabled=monitor_enabled,
        group_name=group_name,
        display_name=display_name,
        douyin_nickname="",
        homepage_url="https://example.com/" + account_id,
        status=status,
        last_error=last_error,
        last_new_count=0,
    )


def test_failed_download_stays_pending_in_new_work_inbox():
    works = [item("new", item_id="n"), item("download_failed", item_id="f"), item("downloaded", item_id="d")]
    a = account(items=works)

    assert state.pending_new_work_count_for_account(a) == 2
    assert [work.item_id for _account, work in state.new_work_entries([a])] == ["n", "f"]


def test_filter_work_items_uses_single_status_rule():
    works = [
        item("new", item_id="new"),
        item("download_failed", item_id="failed"),
        item("downloaded", item_id="done"),
        item("count_only", item_id="count"),
        item("", media_type="image", image_urls=["x"], item_id="gallery"),
    ]

    assert [work.item_id for work in state.filter_work_items(works, "pending")] == ["new", "gallery"]
    assert [work.item_id for work in state.filter_work_items(works, "failed")] == ["failed"]
    assert [work.item_id for work in state.filter_work_items(works, "gallery")] == ["gallery"]
    assert [work.item_id for work in state.filter_download_items(works, "failed")] == ["failed"]


def test_visible_accounts_combines_status_group_and_search_filters():
    accounts = [
        account("a1", group_name="剪辑", display_name="猫猫", items=[item("new")]),
        account("a2", group_name="直播", display_name="狗狗", monitor_enabled=False),
        account("a3", group_name="剪辑", display_name="异常", last_error="Cookie 失效"),
    ]

    assert [a.account_id for a in state.visible_accounts(accounts, mode="new", group_filter="剪辑")] == ["a1"]
    assert [a.account_id for a in state.visible_accounts(accounts, mode="stopped")] == ["a2"]
    assert [a.account_id for a in state.visible_accounts(accounts, mode="error", search_query="异常")] == ["a3"]


def test_download_status_counts_and_failure_category():
    works = [item("new"), item("download_failed"), item("downloaded"), item("count_only"), item("", media_type="gallery")]
    counts = state.download_status_counts(works)

    assert counts["total"] == 5
    assert counts["new"] == 1
    assert counts["failed"] == 1
    assert counts["downloaded"] == 1
    assert counts["count_only"] == 1
    assert counts["gallery"] == 1
    assert state.batch_failure_category("Cookie 登录态失效") == "cookie"
    assert state.batch_failure_category("429 风控验证") == "risk_control"


def test_core_status_rules_accept_dicts_for_web_serialization():
    from app.core.content_monitor import status_rules
    from app.web.serializers import account_to_dict

    data_item = {"status": "download_failed", "item_id": "failed"}
    assert status_rules.is_pending_new_work_item(data_item)

    account_data = account(items=[data_item, {"status": "downloaded", "item_id": "done"}])
    assert account_to_dict(account_data, include_items=True)["new_unhandled_count"] == 1
