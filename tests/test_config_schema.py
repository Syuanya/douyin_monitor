from __future__ import annotations

import unittest

from app.core.config.schema import validate_user_config


class ConfigSchemaTest(unittest.TestCase):
    def test_validate_user_config_clamps_and_normalizes_values(self) -> None:
        config = validate_user_config(
            {
                "douyin_parser_backend": "bad",
                "max_parallel_downloads": 999,
                "video_parse_concurrency": "0",
                "enable_proxy": "yes",
                "sqlite_json_mirror_enabled": "off",
                "douyin_content_request_timeout_seconds": "1",
            },
            {
                "douyin_parser_backend": "internal",
                "max_parallel_downloads": 2,
                "video_parse_concurrency": 4,
                "enable_proxy": False,
                "sqlite_json_mirror_enabled": True,
                "douyin_content_request_timeout_seconds": 15,
            },
        )

        self.assertEqual(config["douyin_parser_backend"], "internal")
        self.assertEqual(config["max_parallel_downloads"], 64)
        self.assertEqual(config["video_parse_concurrency"], 1)
        self.assertTrue(config["enable_proxy"])
        self.assertFalse(config["sqlite_json_mirror_enabled"])
        self.assertEqual(config["douyin_content_request_timeout_seconds"], 5.0)
