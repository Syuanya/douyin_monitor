from __future__ import annotations

import unittest

from app.core.errors import classify_failure


class ErrorClassificationTest(unittest.TestCase):
    def test_classify_failure_marks_404_not_retryable(self) -> None:
        advice = classify_failure("HTTP 404 不存在")

        self.assertEqual(advice.category, "作品失效")
        self.assertFalse(advice.retryable)

    def test_classify_failure_detects_cookie_risk(self) -> None:
        advice = classify_failure("Cookie 失效或风控")

        self.assertEqual(advice.category, "登录或风控")
