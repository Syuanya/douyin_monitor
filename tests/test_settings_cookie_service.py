from __future__ import annotations

import time
import unittest
from types import SimpleNamespace

from app.core.network.cookie_health_store import CookieHealthStore
from app.core.ui_services.settings_cookie_service import SettingsCookieService


class SettingsCookieServiceTest(unittest.TestCase):
    def test_analyze_masks_cookies_and_reports_duplicates(self) -> None:
        app = SimpleNamespace(services=SimpleNamespace(cookie_health_store=None))
        service = SettingsCookieService(app)
        raw = "sessionid=abcdef1234567890; ttwid=abcdef\nsessionid=abcdef1234567890; ttwid=abcdef\ninvalid"

        inventory = service.analyze("douyin", raw)

        self.assertEqual(len(inventory.items), 1)
        self.assertGreaterEqual(inventory.duplicate_or_invalid, 1)
        self.assertIn("sessionid", inventory.items[0].masked)
        self.assertNotIn("abcdef1234567890", inventory.items[0].masked)
        self.assertIn("抖音 Cookie", inventory.summary())

    def test_analyze_merges_cookie_health_status(self) -> None:
        cookie = "sessionid=abcdef1234567890; ttwid=abcdef"
        store = CookieHealthStore(run_path="/tmp/nonexistent", enabled=False)
        key = store.cookie_hash(cookie)
        future = time.time() + 300
        store._states["douyin"][key] = __import__("app.core.network.cookie_health_store", fromlist=["CookieHealthState"]).CookieHealthState(
            cookie_hash=key,
            platform="douyin",
            failure=4.0,
            cooldown_until=future,
            last_reason="响应内容为空",
        )
        app = SimpleNamespace(services=SimpleNamespace(cookie_health_store=store))
        service = SettingsCookieService(app)

        inventory = service.analyze("douyin", cookie)

        self.assertEqual(inventory.items[0].status, "cooldown")
        self.assertGreater(inventory.items[0].cooldown_seconds, 0)
        self.assertEqual(inventory.cooldown_count, 1)


if __name__ == "__main__":
    unittest.main()
