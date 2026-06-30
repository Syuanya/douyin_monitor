from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.core.ui_services.settings_proxy_service import SettingsProxyService
from app.core.ui_services.settings_validator import SettingsValidator


class SettingsProxyServiceTest(unittest.TestCase):
    def test_validate_normalizes_proxy_without_scheme(self) -> None:
        result = SettingsProxyService.validate("127.0.0.1:7890", enabled=True)
        self.assertTrue(result.ok)
        self.assertEqual(result.normalized, "http://127.0.0.1:7890")
        self.assertIn("http", result.summary())

    def test_validate_rejects_missing_port(self) -> None:
        result = SettingsProxyService.validate("http://127.0.0.1", enabled=True)
        self.assertFalse(result.ok)
        self.assertIn("端口", result.summary())

    def test_validator_reports_proxy_format_and_normalizes(self) -> None:
        validation = SettingsValidator.validate({"enable_proxy": True, "proxy_address": "127.0.0.1:7890"}, {})
        self.assertEqual(validation.values["proxy_address"], "http://127.0.0.1:7890")
        self.assertTrue(any("http" in message for message in validation.messages))


if __name__ == "__main__":
    unittest.main()
