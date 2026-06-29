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


def test_video_parse_results_support_filter_sort_and_lazy_previews() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self.result_filter = \"all\"" in text
    assert "self.result_sort = \"input\"" in text
    assert "_filtered_parse_items" in text
    assert "输入顺序" in text
    assert "缩略图延迟加载" in text
    assert "self.preview_image_limit = 36" in text


def test_video_parse_batch_download_can_be_cancelled_with_progress_panel() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self._batch_download_cancel_requested" in text
    assert "cancel_batch_download" in text
    assert "停止下载" in text
    assert "_batch_download_progress_panel" in text
    assert "批量下载已停止" in text
