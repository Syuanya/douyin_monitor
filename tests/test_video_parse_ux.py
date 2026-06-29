from __future__ import annotations

from app.core.media.video_parser_service import VideoParserService


def test_url_report_cleans_tracking_query_and_counts_duplicates() -> None:
    parser = VideoParserService(parse_concurrency=1)
    report = parser.extract_url_report(
        "https://www.iesdouyin.com/share/slides/7655691094730930865/?region=CN&share_sign=abc "
        "https://www.iesdouyin.com/share/slides/7655691094730930865/?region=US&share_sign=def "
        "v.douyin.com/AbCdE/"
    )

    assert report["raw_count"] == 3
    assert report["duplicate_count"] == 1
    assert report["urls"] == [
        "https://www.iesdouyin.com/share/slides/7655691094730930865",
        "https://v.douyin.com/AbCdE",
    ]
