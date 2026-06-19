from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.core.content_monitor.services.account_repository import AccountRepository
from app.core.storage.sqlite_store import SQLiteStore


class AccountRepositoryTest(unittest.TestCase):
    def test_account_repository_loads_and_saves_accounts(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "douyin_content_monitor.json"
            repo = AccountRepository(str(path))

            repo.save_accounts([{"account_id": "a1", "homepage_url": "https://www.douyin.com/user/x"}])
            loaded = repo.load_accounts(lambda item: item)

            self.assertEqual(loaded, [{"account_id": "a1", "homepage_url": "https://www.douyin.com/user/x"}])
            payload = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(payload["version"], 27)
            self.assertEqual(payload["mode"], "public_profile_low_frequency")

    def test_account_repository_recovers_invalid_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "douyin_content_monitor.json"
            path.write_text("{invalid", encoding="utf-8")
            repo = AccountRepository(str(path))

            loaded = repo.load_accounts(lambda item: item)

            self.assertEqual(loaded, [])
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["accounts"], [])
            self.assertTrue(list(Path(temp_dir).glob("douyin_content_monitor.json.invalid.*.bak")))

    def test_account_repository_migrates_json_to_sqlite_and_mirrors_saves(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            path = config_dir / "douyin_content_monitor.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 27,
                        "accounts": [
                            {
                                "account_id": "a1",
                                "homepage_url": "https://www.douyin.com/user/x",
                                "display_name": "demo",
                                "items": [
                                    {
                                        "item_id": "100000001",
                                        "title": "work",
                                        "status": "active",
                                    }
                                ],
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            store = SQLiteStore(str(root))
            repo = AccountRepository(str(path), sqlite_store=store)

            loaded = repo.load_accounts(lambda item: item)

            self.assertEqual(len(loaded), 1)
            self.assertEqual(store.monitor_account_count(), 1)
            self.assertEqual(store.load_monitor_accounts()[0]["items"][0]["item_id"], "100000001")

            repo.save_accounts(
                [
                    {
                        "account_id": "a2",
                        "homepage_url": "https://www.douyin.com/user/y",
                        "display_name": "demo2",
                        "items": [],
                    }
                ]
            )
            self.assertEqual(store.load_monitor_accounts()[0]["account_id"], "a2")
            mirror = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(mirror["accounts"][0]["account_id"], "a2")

    def test_account_repository_can_disable_json_mirror_when_sqlite_is_available(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            config_dir = root / "config"
            config_dir.mkdir()
            path = config_dir / "douyin_content_monitor.json"
            store = SQLiteStore(str(root))
            repo = AccountRepository(str(path), sqlite_store=store, mirror_json=False)

            repo.save_accounts(
                [
                    {
                        "account_id": "a3",
                        "homepage_url": "https://www.douyin.com/user/z",
                        "items": [],
                    }
                ]
            )

            self.assertFalse(path.exists())
            self.assertEqual(store.monitor_account_count(), 1)
            self.assertEqual(repo.load_accounts(lambda item: item)[0]["account_id"], "a3")
