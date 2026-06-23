from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from pathlib import Path

from app.core.config.config_manager import ConfigManager


class ConfigManagerCookieSecurityTest(unittest.TestCase):
    def test_secure_cookie_save_does_not_leave_plaintext_cookie_mirror(self) -> None:
        async def run_case() -> None:
            with tempfile.TemporaryDirectory() as temp_dir:
                config_dir = Path(temp_dir) / "config"
                config_dir.mkdir(parents=True, exist_ok=True)
                (config_dir / "default_settings.json").write_text(
                    json.dumps({"secure_cookie_storage_enabled": True}),
                    encoding="utf-8",
                )
                manager = ConfigManager(temp_dir)
                await manager.save_cookies_config({"douyin_cookie": "sessionid=secret; ttwid=value"})

                plaintext = json.loads((config_dir / "cookies.json").read_text(encoding="utf-8"))
                self.assertEqual(plaintext, {})
                self.assertEqual(manager.load_cookies_config()["douyin_cookie"], "sessionid=secret; ttwid=value")

        asyncio.run(run_case())
