from __future__ import annotations

import unittest
from pathlib import Path


class MonitorNicknameHydrationTest(unittest.TestCase):
    def test_auto_name_prefers_target_public_profile_over_cookie_user_info(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])
        hydrate_block = text.split("async def hydrate_account_display_name", 1)[1].split("def _profile_info_matches_account", 1)[0]

        self.assertLess(hydrate_block.find("fetch_public_profile"), hydrate_block.find("fetch_user_profile_info"))
        self.assertIn("fetch_public_profile(account, include_cookie=False)", hydrate_block)
        self.assertIn("_profile_info_matches_account(account, profile_info)", hydrate_block)
        self.assertNotIn('nickname = str(profile_info.get("douyin_nickname")', hydrate_block)

    def test_user_info_must_match_sec_uid_before_it_can_update_profile(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])

        self.assertIn("def _profile_info_matches_account", text)
        self.assertIn("target_sec_uid = self.extract_sec_uid(account.homepage_url)", text)
        self.assertIn('value and value == target_sec_uid', text)
        self.assertIn("profile_info_matches and profile_info.get(\"douyin_nickname\") and not douyin_nickname", text)

    def test_batch_import_hydrates_missing_names(self) -> None:
        text = Path("app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")

        self.assertIn("if not row.name:", text)
        batch_block = text.split("async def show_batch_import_dialog", 1)[1].split("def _parse_batch_import_rows", 1)[0]
        self.assertIn("hydrate_account_ids.append(account.account_id)", batch_block)
        self.assertIn("self._schedule_batch_name_hydration(hydrate_account_ids)", batch_block)
        self.assertNotIn("await self.manager.hydrate_account_display_name(account.account_id, force=True)", batch_block)
        self.assertIn("async def _hydrate_batch_account_names", text)

    def test_headers_can_disable_cookie_for_identity_fetch(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])

        self.assertIn("def _headers(self, *, include_cookie: bool = True)", text)
        self.assertIn("if include_cookie:", text)
        self.assertIn("headers, cookie = self._headers_for_cookie_request(include_cookie=include_cookie)", text)

    def test_detection_and_sync_do_not_extract_nickname_from_cookie_profile_page(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])
        parser_posts_block = text.split("async def fetch_parser_user_posts", 1)[1].split("async def fetch_external_user_posts", 1)[0]
        sync_block = text.split("async def sync_account_works", 1)[1].split("def _merge_detected_items", 1)[0]
        check_block = text.split("async def check_account", 1)[1].split("async def _notify_new_items", 1)[0]

        self.assertNotIn("_extract_douyin_nickname(page_text)", parser_posts_block)
        self.assertNotIn("_extract_douyin_nickname(page_text)", sync_block)
        self.assertNotIn("_extract_douyin_nickname(page_text)", check_block)
        self.assertIn("identity_result = await self.hydrate_account_display_name(account.account_id)", check_block)
        self.assertIn("await self.hydrate_account_display_name(account.account_id)", sync_block)

    def test_final_url_and_profile_html_must_match_target_before_use(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])
        hydrate_block = text.split("async def hydrate_account_display_name", 1)[1].split("def _profile_info_matches_account", 1)[0]
        sync_block = text.split("async def sync_account_works", 1)[1].split("def _merge_detected_items", 1)[0]
        check_block = text.split("async def check_account", 1)[1].split("async def _notify_new_items", 1)[0]

        self.assertIn("def _safe_update_homepage_from_final_url", text)
        self.assertIn("def _public_profile_page_matches_account", text)
        self.assertIn("self._safe_update_homepage_from_final_url(account, final_url)", hydrate_block)
        self.assertIn("self._public_profile_page_matches_account(account, page_text, final_url)", hydrate_block)
        self.assertNotIn("account.homepage_url = self.normalize_homepage_url(final_url)", sync_block)
        self.assertNotIn("account.homepage_url = self.normalize_homepage_url(final_url)", check_block)
        self.assertIn("profile_page_matches = self._public_profile_page_matches_account(account, page_text, final_url)", check_block)
        self.assertIn("detected_items = self.parse_public_profile_items(page_text) if profile_page_matches else []", check_block)

    def test_force_hydration_clears_old_auto_cookie_nickname_when_target_name_unverified(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/services/account_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/download_service.py").read_text(encoding="utf-8"),
        ])
        hydrate_block = text.split("async def hydrate_account_display_name", 1)[1].split("def _profile_info_matches_account", 1)[0]

        self.assertIn("if force and (not display_name or display_name == \"抖音用户\" or display_name == current_nickname):", hydrate_block)
        self.assertIn("account.douyin_nickname = \"\"", hydrate_block)
        self.assertIn("account.display_name = \"抖音用户\"", hydrate_block)
        self.assertIn("已避免使用 Cookie 账号昵称", hydrate_block)


if __name__ == "__main__":
    unittest.main()
