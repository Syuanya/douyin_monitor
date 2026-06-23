from __future__ import annotations

import unittest
from pathlib import Path


class DouyinInboxBatchResultUITest(unittest.TestCase):
    def test_inbox_uses_independent_visible_count(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

        self.assertIn("self.inbox_visible_count = 12", view)
        self.assertIn("entries[: self.inbox_visible_count]", view)
        self.assertIn("if self.view_mode == \"inbox\":\n            self.inbox_visible_count += self.work_page_size", view)
        self.assertIn("item.status = \"active\"", view)

    def test_new_work_filter_and_inbox_use_pending_item_status(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
        cards = Path("app/ui/components/business/douyin_content_cards.py").read_text(encoding="utf-8")
        presenter = Path("app/ui/views/douyin_content_presenter.py").read_text(encoding="utf-8")

        self.assertIn("def _is_pending_new_work_item", view)
        self.assertIn("{\"new\", \"count_only\"}", view)
        self.assertIn("return [account for account in accounts if self._pending_new_work_count_for_account(account) > 0]", view)
        self.assertIn("新作品箱 {self._pending_new_work_count()}", view)
        self.assertIn("数量变化", cards)
        self.assertIn("重新同步该账号作品", cards)
        self.assertIn("def has_pending_new_work", presenter)

    def test_batch_result_dialog_has_task_center_fallback(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

        self.assertIn("def _batch_result_icon_button", view)
        self.assertIn("self._latest_batch_result_lines()", view)
        self.assertIn("task_center", view)
        self.assertIn("snapshot(limit=30)", view)
        self.assertNotIn("disabled=not self.batch_result_lines", view)


if __name__ == "__main__":
    unittest.main()
