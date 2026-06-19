from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from app.core.config.cookie_vault import CookieVault


class CookieVaultTest(unittest.TestCase):
    def test_cookie_vault_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "cookies.secure.json"
            vault = CookieVault(str(path))

            provider = vault.save({"douyin_cookie": "a=b; c=d"})
            loaded = vault.load()

            self.assertIn(provider, {"windows-dpapi", "base64-compat"})
            self.assertEqual(loaded["douyin_cookie"], "a=b; c=d")
