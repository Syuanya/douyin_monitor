from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_video_parse_has_selection_mode_failure_summary_and_download_rules() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self.result_select_mode = False" in text
    assert "selected_result_keys" in text
    assert "下载选中" in text
    assert "_failure_summary_panel" in text
    assert "失败集中处理" in text
    assert "_download_rules_panel" in text
    assert "保存规则" in text


def test_video_parse_input_summary_uses_link_digest() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")

    assert "self.input_preview_text" in text
    assert "链接摘要" in text
    assert "_short_url" in text


def test_content_monitor_batch_settings_are_checkbox_guarded() -> None:
    text = (ROOT / "app/ui/views/douyin_content_batch_settings_controller.py").read_text(encoding="utf-8")

    assert "修改分组" in text
    assert "修改自动下载策略" in text
    assert "修改通知策略" in text
    assert "只会修改已勾选的项目" in text
    assert "未勾选项目保持不变" in text
