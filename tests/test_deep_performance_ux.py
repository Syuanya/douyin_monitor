from __future__ import annotations

from pathlib import Path

from app.core.media.parser_models import ParseFailure, ParsedVideoResult, VideoParseBatchResult
from app.core.ui_services.video_parse_workflow import VideoParseWorkflow

ROOT = Path(__file__).resolve().parents[1]


def test_video_parse_history_is_resource_library() -> None:
    result = VideoParseBatchResult(
        input_text="https://www.douyin.com/video/1",
        urls=["https://www.douyin.com/video/1", "https://www.douyin.com/video/2"],
        successes=[
            ParsedVideoResult(
                source_url="https://www.douyin.com/video/1",
                media_type="video",
                platform="douyin",
                item_id="1",
                description="标题A",
                author_nickname="作者A",
                no_watermark_url="https://media.example/a.mp4",
            )
        ],
        failures=[ParseFailure(source_url="https://www.douyin.com/video/2", reason="Cookie 失效", category="cookie", retryable=True)],
    )
    resources = VideoParseWorkflow.build_resource_records(result)
    failures = VideoParseWorkflow.build_failure_records(result)
    assert resources[0]["media_type"] == "视频"
    assert resources[0]["downloadable"] is True
    assert failures[0]["category"] == "cookie"
    assert VideoParseWorkflow.failure_summary(result.failures) == {"cookie": 1}


def test_video_parse_resource_library_contract_in_ui() -> None:
    text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")
    workflow = (ROOT / "app/core/ui_services/video_parse_workflow.py").read_text(encoding="utf-8")

    assert "解析资源库" in text
    assert "复制失败链接" in text
    assert "清空资源库" in text
    assert "HISTORY_LIMIT = 200" in workflow
    assert "build_resource_records" in workflow
    assert "failure_details" in workflow


def test_content_monitor_has_error_repair_and_inbox_summary() -> None:
    view = (ROOT / "app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
    repair = (ROOT / "app/ui/views/douyin_content_error_repair_controller.py").read_text(encoding="utf-8")
    inbox = (ROOT / "app/ui/views/douyin_content_inbox_controller.py").read_text(encoding="utf-8")
    text = "\n".join([view, repair, inbox])

    assert "异常修复中心" in text
    assert "open_error_repair_center" in view
    assert "重新检测异常账号" in text
    assert "同步异常账号" in text
    assert "复制异常摘要" in text
    assert "summary_panel" in inbox
    assert "数量变化提示" in text
