from __future__ import annotations

import unittest
from pathlib import Path


class DouyinInboxBatchResultUITest(unittest.TestCase):
    def test_inbox_uses_independent_visible_count(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
        state = Path("app/ui/views/douyin_content_state.py").read_text(encoding="utf-8")
        inbox = Path("app/ui/views/douyin_content_inbox_controller.py").read_text(encoding="utf-8")
        work = Path("app/ui/views/douyin_content_work_controller.py").read_text(encoding="utf-8")

        self.assertIn("DEFAULT_WORK_PAGE_SIZE = 20", state)
        self.assertIn("self.inbox_visible_count = content_state.DEFAULT_WORK_PAGE_SIZE", view)
        self.assertIn("entries[: owner.inbox_visible_count]", inbox)
        self.assertIn("if owner.view_mode == \"inbox\":\n            owner.inbox_visible_count += owner.work_page_size", work)
        self.assertIn("item.status = \"active\"", inbox)

    def test_new_work_filter_and_inbox_use_pending_item_status(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
        toolbar = Path("app/ui/views/douyin_content_toolbar.py").read_text(encoding="utf-8")
        state = Path("app/ui/views/douyin_content_state.py").read_text(encoding="utf-8")
        cards = Path("app/ui/components/business/douyin_content_cards.py").read_text(encoding="utf-8")
        presenter = Path("app/ui/views/douyin_content_presenter.py").read_text(encoding="utf-8")

        self.assertIn("def _is_pending_new_work_item", view)
        core_status = Path("app/core/content_monitor/status_rules.py").read_text(encoding="utf-8")
        self.assertIn('PENDING_NEW_WORK_STATUSES = {NEW_STATUS, COUNT_ONLY_STATUS, DOWNLOAD_FAILED_STATUS}', core_status)
        self.assertIn('PENDING_NEW_WORK_STATUSES = status_rules.PENDING_NEW_WORK_STATUSES', state)
        self.assertIn("return content_state.visible_accounts", view)
        self.assertIn("新作品箱 {owner._pending_new_work_count()}", toolbar)
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
