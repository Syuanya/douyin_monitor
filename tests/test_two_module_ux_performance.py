from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_content_monitor_account_list_is_incrementally_rendered() -> None:
    text = (ROOT / "app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

    assert "self.account_visible_count = 30" in text
    assert "load_more_accounts" in text
    assert "当前显示 {len(visible_accounts)}/{len(accounts)} 个账号" in text
    assert "大量账号会分批渲染" in text


def test_content_monitor_pubsub_refresh_is_throttled_during_heavy_jobs() -> None:
    text = (ROOT / "app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

    assert "if self.batch_job_running or self.download_in_progress" in text
    assert "now - self._last_pubsub_refresh_at < 0.8" in text
    assert "self._pending_monitor_refresh = True" in text


def test_video_parse_results_support_filter_sort_and_safe_visual_cards() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self.result_filter = \"all\"" in text
    assert "self.result_sort = \"input\"" in text
    assert "_filtered_parse_items" in text
    assert "输入顺序" in text
    assert "结果卡片：已切换为稳定文本卡片" in text
    assert "_result_media_box" in text
    assert "self.result_list_text_only = True" in text
    assert "ft.Image(src=" not in text
    assert "create_media_preview" not in text
    assert "显示缩略图" not in text
    assert "ft.ProgressBar(" not in text


def test_video_parse_batch_download_can_be_cancelled_with_progress_panel() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self._batch_download_cancel_requested" in text
    assert "cancel_batch_download" in text
    assert "停止下载" in text
    assert "_batch_download_progress_panel" in text
    assert "_update_result_status_only" in text
    assert "已停止" in text


def test_content_monitor_new_work_cards_keep_bounded_covers() -> None:
    text = (ROOT / "app/ui/components/business/douyin_content_cards.py").read_text(encoding="utf-8")

    assert "def _cover_grid_box" in text
    assert "height=150" in text
    assert "create_inbox_item" in text
    assert "create_history_item" in text
    assert "PERSON_SEARCH" in text
