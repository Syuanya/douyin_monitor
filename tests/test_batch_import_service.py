from __future__ import annotations

from pathlib import Path

from app.core.content_monitor.models import DouyinMonitorAccount
from app.core.content_monitor.services.batch_import_service import parse_batch_import_text, read_batch_import_file


def test_batch_import_preview_normalizes_and_deduplicates_urls():
    text = """
    https://www.douyin.com/user/MS4wLjABAAAAabc?from=copy, 账号A, 分组1
    https://www.douyin.com/user/MS4wLjABAAAAabc/ , 账号A重复, 分组1
    https://www.douyin.com/user/MS4wLjABAAAAdef，账号B，分组2
    not a url
    """
    preview = parse_batch_import_text(text)
    counts = preview.counts()
    assert counts["add"] == 2
    assert counts["duplicate"] == 1
    assert counts["invalid"] == 1
    assert preview.valid_rows[0].normalized_url == "https://www.douyin.com/user/MS4wLjABAAAAabc"


def test_batch_import_preview_marks_existing_as_update():
    existing = DouyinMonitorAccount(account_id="a1", homepage_url="https://www.douyin.com/user/MS4wLjABAAAAabc")
    preview = parse_batch_import_text("https://www.douyin.com/user/MS4wLjABAAAAabc?x=1, 新备注", existing_accounts=[existing])
    assert preview.counts()["update"] == 1
    assert preview.valid_rows[0].action == "update"


def test_read_batch_import_file_supports_csv_and_txt(tmp_path: Path):
    file_path = tmp_path / "accounts.csv"
    file_path.write_text("url,name\nhttps://www.douyin.com/user/MS4wLjABAAAAabc,账号A\n", encoding="utf-8-sig")
    assert "douyin.com" in read_batch_import_file(str(file_path))
