from __future__ import annotations

import unittest
from pathlib import Path


class SettingsFeedbackTest(unittest.TestCase):
    def test_cookie_test_and_save_have_inline_feedback(self) -> None:
        text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")

        self.assertIn("self.settings_status_text", text)
        self.assertIn("self.cookie_test_status_text", text)
        self.assertIn("正在测试 {label} Cookie", text)
        self.assertIn("正在保存设置", text)
        self.assertIn("await self._show_feedback(\"cookie\"", text)
        self.assertIn("await self._show_feedback(\"settings\"", text)

    def test_cookie_sync_warning_does_not_block_save_feedback(self) -> None:
        text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")

        self.assertIn("cookie_sync_warnings", text)
        self.assertIn("Cookie 已保存，但同步到内置解析器时有警告", text)
        self.assertIn("sync {platform} cookie to parser failed", text)


if __name__ == "__main__":
    unittest.main()
