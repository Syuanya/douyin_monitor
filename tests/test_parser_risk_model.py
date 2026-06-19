from __future__ import annotations

import unittest

from app.core.parser.risk_model import classify_parser_failure


class ParserRiskModelTest(unittest.TestCase):
    def test_classifies_risk_control_as_non_retryable_user_action(self) -> None:
        result = classify_parser_failure("429 too many requests captcha verify")

        self.assertEqual(result.category, "risk_control")
        self.assertFalse(result.retryable)
        self.assertTrue(result.user_action_required)

    def test_classifies_network_as_retryable(self) -> None:
        result = classify_parser_failure("connection timeout")

        self.assertEqual(result.category, "network")
        self.assertTrue(result.retryable)
        self.assertFalse(result.user_action_required)

    def test_classifies_deleted_or_private_content(self) -> None:
        result = classify_parser_failure("404 private not found")

        self.assertEqual(result.category, "not_found_or_private")
        self.assertFalse(result.retryable)
