from __future__ import annotations

from app.ui.views.douyin_content_download_complete_controller import DouyinContentDownloadCompleteController


def test_file_count_text_for_download_complete_dialog():
    assert DouyinContentDownloadCompleteController.file_count_text(None) == ""
    assert DouyinContentDownloadCompleteController.file_count_text([]) == ""
    assert DouyinContentDownloadCompleteController.file_count_text(["a.mp4", "b.jpg"]) == "\n文件数：2"
