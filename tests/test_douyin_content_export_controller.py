from __future__ import annotations

from types import SimpleNamespace

from app.ui.views.douyin_content_export_controller import DouyinContentExportController


class Manager:
    def __init__(self, accounts):
        self.accounts = accounts


def item(item_id, *, status="new", media_type="video"):
    return SimpleNamespace(
        item_id=item_id,
        title=f"标题{item_id}",
        status=status,
        media_type=media_type,
        image_urls=["https://img"] if media_type == "gallery" else [],
        publish_time="2026-06-30 10:00",
        first_seen_time="2026-06-30 10:01",
        share_url=f"https://example.com/{item_id}",
    )


def account():
    return SimpleNamespace(
        account_id="a1",
        display_name="备注",
        douyin_nickname="昵称",
        group_name="分组",
        homepage_url="https://example.com/user",
        monitor_enabled=True,
        notify_enabled=False,
        auto_download_policy="all",
        last_check_time="2026-06-30 11:00",
        last_success_time="2026-06-30 11:01",
        status="正常",
        last_error="",
        monitor_interval_minutes=30,
        auto_pause_failures=3,
        keep_recent_count=200,
        last_new_count=2,
        total_new_count=9,
        aweme_count=88,
        error_count=1,
        items=[item("v1"), item("c1", status="count_only"), item("g1", media_type="gallery")],
    )


def owner_with(tmp_path):
    owner = SimpleNamespace(
        app=SimpleNamespace(run_path=str(tmp_path), services=SimpleNamespace(run_path=str(tmp_path))),
        manager=Manager([account()]),
        _={"export_success": "诊断包已导出：{path}", "export_failed": "导出失败", "open_failed": "打开失败"},
    )
    owner._auto_download_policy_label = lambda value: {"all": "自动下载全部"}.get(value, value)
    owner._is_gallery_item = lambda target: getattr(target, "media_type", "") == "gallery" or bool(getattr(target, "image_urls", []))
    return owner


def test_export_rows_skip_count_only_and_include_user_facing_labels(tmp_path):
    controller = DouyinContentExportController(owner_with(tmp_path))

    work_rows = controller.work_rows()
    account_rows = controller.account_rows()

    assert len(work_rows) == 2
    assert work_rows[0][0:4] == ["备注", "昵称", "分组", "https://example.com/user"]
    assert {row[13] for row in work_rows} == {"视频", "图集"}
    assert account_rows[0][16] == 2
    assert account_rows[0][17] == 88


def test_write_csv_creates_utf8_sig_file(tmp_path):
    path = tmp_path / "export.csv"
    DouyinContentExportController.write_csv(str(path), ["列"], [["值"]])

    data = path.read_bytes()
    assert data.startswith(b"\xef\xbb\xbf")
    assert "列" in data.decode("utf-8-sig")
