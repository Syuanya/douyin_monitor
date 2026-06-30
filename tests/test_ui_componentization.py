import unittest
from pathlib import Path


class UIComponentizationTest(unittest.TestCase):
    def test_douyin_content_view_delegates_cards_to_components(self):
        view = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
        self.assertIn("DouyinContentAccountController", view)
        self.assertTrue(Path("app/ui/views/douyin_content_account_controller.py").is_file())
        self.assertIn("content_cards.create_history_item", view)
        self.assertIn("content_cards.create_inbox_item", view)
        self.assertTrue(Path("app/ui/components/business/douyin_content_cards.py").is_file())
        self.assertTrue(Path("app/ui/views/douyin_content_add_account_controller.py").is_file())
        self.assertTrue(Path("app/ui/views/douyin_content_download_complete_controller.py").is_file())
        self.assertTrue(Path("app/ui/views/douyin_content_batch_import_controller.py").is_file())
        self.assertTrue(Path("app/ui/views/douyin_content_global_actions_controller.py").is_file())
        self.assertLess(len(view.splitlines()), 1600)


if __name__ == "__main__":
    unittest.main()
