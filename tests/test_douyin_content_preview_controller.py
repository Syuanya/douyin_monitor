from __future__ import annotations

from app.ui.views.douyin_content_preview_controller import DouyinContentPreviewController


def test_format_size_for_detail_dialog():
    assert DouyinContentPreviewController.format_size(0) == "-"
    assert DouyinContentPreviewController.format_size(1024) == "1.0 KB"
    assert DouyinContentPreviewController.format_size(1024 * 1024 * 3) == "3.0 MB"
