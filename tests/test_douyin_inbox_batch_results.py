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

    def test_batch_result_dialog_has_task_center_fallback(self) -> None:
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

        self.assertIn("def _batch_result_icon_button", view)
        self.assertIn("self._latest_batch_result_lines()", view)
        self.assertIn("task_center", view)
        self.assertIn("snapshot(limit=30)", view)
        self.assertNotIn("disabled=not self.batch_result_lines", view)


if __name__ == "__main__":
    unittest.main()
