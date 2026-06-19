from __future__ import annotations

import unittest

from app.core.config.migrations import migrate_user_config


class ConfigMigrationsTest(unittest.TestCase):
    def test_migrate_user_config_adds_v3_and_v4_fields(self) -> None:
        migrated, changed, old, new = migrate_user_config(
            {"config_version": 1, "douyin_external_api_base_url": "http://127.0.0.1:8000"},
            {"config_version": 4, "douyin_parser_backend": "internal", "douyin_parser_max_pages": 20},
        )

        self.assertTrue(changed)
        self.assertEqual(old, 1)
        self.assertEqual(new, 4)
        self.assertEqual(migrated["douyin_parser_backend"], "external")
        self.assertTrue(migrated["secure_cookie_storage_enabled"])
        self.assertTrue(migrated["download_resume_enabled"])
        self.assertTrue(migrated["sqlite_json_mirror_enabled"])
