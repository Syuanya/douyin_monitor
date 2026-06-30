from __future__ import annotations

from types import SimpleNamespace

from app.core.content_monitor.models import DouyinContentItem, DouyinMonitorAccount
from app.ui.views.douyin_content_insights_controller import DouyinContentInsightsController


class _Manager:
    def __init__(self):
        self.accounts = [
            DouyinMonitorAccount(
                account_id="a1",
                homepage_url="https://www.douyin.com/user/a1",
                display_name="健康账号",
                group_name="A组",
                monitor_enabled=True,
                last_success_time="2099-01-01 00:00:00",
                items=[DouyinContentItem(item_id="100", title="新视频", status="new", share_url="https://v/100", first_seen_time="2099-01-01 00:00:00")],
            ),
            DouyinMonitorAccount(
                account_id="a2",
                homepage_url="https://www.douyin.com/user/a2",
                display_name="风险账号",
                group_name="B组",
                monitor_enabled=True,
                last_error="Cookie 失效",
                error_count=3,
                items=[DouyinContentItem(item_id="200", title="失败图集", media_type="gallery", image_urls=["https://img/1"], status="download_failed", failure_category="作品失效", failure_next_step="打开原链接确认", share_url="https://v/200", first_seen_time="2099-01-02 00:00:00")],
            ),
        ]

    def content_monitor_health_summary(self):
        from app.core.content_monitor.insights import health_summary

        return health_summary(self.accounts, now_ts=4102444800.0)

    def content_monitor_group_statistics(self):
        from app.core.content_monitor.insights import group_statistics

        return group_statistics(self.accounts, now_ts=4102444800.0)

    def content_monitor_time_window_digest(self, *, days=1):
        from app.core.content_monitor.insights import time_window_digest

        return time_window_digest(self.accounts, days=days, now_ts=4070995200.0)

    def content_monitor_material_collection(self, **kwargs):
        from app.core.content_monitor.insights import material_collection

        return material_collection(self.accounts, **kwargs)

    def export_content_monitor_material_links(self, **kwargs):
        return {"success": True, "path": "/tmp/materials.csv", "total": 1, "filters": kwargs}


def _owner():
    return SimpleNamespace(manager=_Manager())


def test_insights_controller_health_and_groups():
    controller = DouyinContentInsightsController(_owner())

    health = controller.health_summary()
    assert health["total"] == 2
    assert health["counts"]["risk"] >= 1
    assert health["priority_accounts"][0]["account_id"] == "a2"

    groups = controller.group_statistics()
    names = {row["group_name"] for row in groups["groups"]}
    assert names == {"A组", "B组"}
    assert any(row["download_failed"] == 1 for row in groups["groups"])


def test_insights_controller_material_filters_and_label():
    controller = DouyinContentInsightsController(_owner())

    failed = controller.material_collection(status="failed", media_type="gallery")
    assert failed["total"] == 1
    assert failed["items"][0]["item_id"] == "200"

    pending = controller.material_collection(status="pending", media_type="all")
    assert {item["item_id"] for item in pending["items"]} == {"100", "200"}

    label = controller.material_filter_label(status="pending", media_type="video", group_name="A组", query="新")
    assert "待处理" in label
    assert "视频" in label
    assert "A组" in label
    assert "新" in label


def test_insights_controller_digest_and_export_default_material_links():
    owner = _owner()
    owner.app = SimpleNamespace(snack_bar=SimpleNamespace(show_snack_bar=lambda *a, **k: None))
    controller = DouyinContentInsightsController(owner)

    digest = controller.digest(days=7)
    assert digest["new_items"] >= 2
    assert digest["failed"] == 1

    result = controller.owner.manager.export_content_monitor_material_links(status="pending", media_type="all", limit=1000)
    assert result["success"] is True
    assert result["filters"]["status"] == "pending"


def test_insights_controller_compact_text_and_health_labels():
    controller = DouyinContentInsightsController(_owner())
    assert controller.health_level_label("warning") == "需关注"
    assert controller.health_level_label("missing") == "未知"
    assert controller.compact_text("abcdef", max_len=4) == "abc…"
