from __future__ import annotations

import unittest

from scripts import check_runtime


class RuntimeCheckScriptTest(unittest.TestCase):
    def test_required_modules_are_declared(self) -> None:
        self.assertIn("flet", check_runtime.REQUIRED_MODULES)
        self.assertIn("httpx", check_runtime.REQUIRED_MODULES)
