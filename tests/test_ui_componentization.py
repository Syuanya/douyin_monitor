import unittest
from pathlib import Path


class UIComponentizationTest(unittest.TestCase):
    def test_douyin_content_view_delegates_cards_to_components(self):
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
        self.assertIn("content_cards.create_account_card", view)
        self.assertIn("content_cards.create_history_item", view)
        self.assertIn("content_cards.create_inbox_item", view)
        self.assertTrue(Path("app/ui/components/business/douyin_content_cards.py").is_file())


if __name__ == "__main__":
    unittest.main()
