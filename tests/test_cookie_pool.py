from __future__ import annotations

import unittest
from pathlib import Path

from app.core.media.cookie_utils import parse_cookie_pool


class CookiePoolTest(unittest.TestCase):
    def test_parse_cookie_pool_accepts_one_cookie_per_line(self) -> None:
        pool = parse_cookie_pool("sid=aaa; uid=1\nsid=bbb; uid=2\nsid=aaa; uid=1")

        self.assertEqual(pool, ["sid=aaa; uid=1", "sid=bbb; uid=2"])

    def test_settings_persists_douyin_cookie_pool_and_primary_cookie(self) -> None:
        text = Path("app/ui/views/settings_view.py").read_text(encoding="utf-8")

        self.assertIn("parse_cookie_pool(raw_douyin_cookie)", text)
        self.assertIn("cookies_config[\"douyin_cookie_pool\"] = douyin_cookie_pool", text)
        self.assertIn("douyin_cookie = douyin_cookie_pool[0] if douyin_cookie_pool else \"\"", text)
        self.assertIn("已识别 Cookie 池", text)

    def test_monitor_uses_cookie_pool_rotation_and_cooldown(self) -> None:
        text = "\n".join([
            Path("app/core/content_monitor/douyin_content_monitor.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/facade.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/base_service.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/cookie_runtime.py").read_text(encoding="utf-8"),
            Path("app/core/content_monitor/services/profile_sync_service.py").read_text(encoding="utf-8"),
        ])

        self.assertIn("self._douyin_cookie_cursor = 0", text)
        self.assertIn("self._douyin_cookie_cooldowns", text)
        self.assertIn("def _headers_for_cookie_request", text)
        self.assertIn("def _douyin_cookie_pool", text)
        self.assertIn("def _select_douyin_cookie", text)
        self.assertIn("def _cooldown_douyin_cookie", text)
        self.assertIn("headers, cookie = self._headers_for_cookie_request(include_cookie=include_cookie)", text)
        self.assertIn("headers, cookie = self._headers_for_cookie_request(include_cookie=True)", text)
        self.assertIn("self._record_cookie_response_health(cookie, response=response)", text)


if __name__ == "__main__":
    unittest.main()
