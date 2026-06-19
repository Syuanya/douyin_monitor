from __future__ import annotations

import json
import os
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

try:
    from ....utils.logger import logger
except Exception:  # pragma: no cover - fallback for minimal test environments.
    class _FallbackLogger:
        def debug(self, *_args, **_kwargs) -> None:
            return None

        def error(self, *_args, **_kwargs) -> None:
            return None

    logger = _FallbackLogger()


T = TypeVar("T")


class AccountRepository:
    """Repository for monitor accounts with SQLite primary storage.

    SQLite is used as the primary runtime store when available. The original
    JSON file remains a compatibility mirror for backup/export/manual recovery.
    """

    def __init__(
        self,
        config_path: str,
        version: int = 27,
        mode: str = "public_profile_low_frequency",
        sqlite_store: Any | None = None,
        mirror_json: bool = True,
    ):
        self.config_path = str(config_path)
        self.version = int(version)
        self.mode = str(mode)
        self.sqlite_store = sqlite_store
        self.mirror_json = bool(mirror_json)

    def load_accounts(self, factory: Callable[[dict[str, Any]], T]) -> list[T]:
        raw_accounts = self._load_account_dicts()
        accounts: list[T] = []
        for item in raw_accounts:
            if not isinstance(item, dict):
                continue
            try:
                accounts.append(factory(item))
            except Exception as exc:
                logger.debug(f"Skipped invalid monitor account record: {exc}")
        return accounts

    def _load_account_dicts(self) -> list[dict[str, Any]]:
        sqlite_accounts = self._load_accounts_from_sqlite()
        if sqlite_accounts:
            return sqlite_accounts

        json_accounts = self._load_accounts_from_json()
        if json_accounts:
            self._save_accounts_to_sqlite(json_accounts)
        return json_accounts

    def _load_accounts_from_sqlite(self) -> list[dict[str, Any]]:
        store = self.sqlite_store
        if store is None:
            return []
        try:
            if store.monitor_account_count() <= 0:
                return []
            return store.load_monitor_accounts()
        except Exception as exc:
            logger.error(f"Failed to load monitor accounts from SQLite, fallback to JSON: {exc}")
            return []

    def _load_accounts_from_json(self) -> list[dict[str, Any]]:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        if not os.path.exists(self.config_path):
            self.save_accounts([])
        try:
            with open(self.config_path, encoding="utf-8") as file:
                data = json.load(file)
        except json.JSONDecodeError as exc:
            backup = self._backup_invalid_file()
            logger.error(f"Invalid Douyin monitor config; reset. backup={backup}, error={exc}")
            self.save_accounts([])
            data = {"version": self.version, "accounts": []}
        except FileNotFoundError:
            data = {"version": self.version, "accounts": []}
        except Exception as exc:
            logger.error(f"Failed to load Douyin monitor config: {exc}")
            data = {"version": self.version, "accounts": []}

        raw_accounts = data.get("accounts", data if isinstance(data, list) else []) if isinstance(data, (dict, list)) else []
        accounts: list[dict[str, Any]] = []
        for item in raw_accounts if isinstance(raw_accounts, list) else []:
            if not isinstance(item, dict):
                continue
            accounts.append(item)
        return accounts

    def save_accounts(self, accounts: Iterable[dict[str, Any]]) -> None:
        account_list = list(accounts)
        self._save_accounts_to_sqlite(account_list)
        if self.mirror_json:
            self._save_accounts_to_json(account_list)

    def _save_accounts_to_sqlite(self, accounts: list[dict[str, Any]]) -> None:
        store = self.sqlite_store
        if store is None:
            return
        try:
            store.save_monitor_accounts(accounts)
        except Exception as exc:
            logger.error(f"Failed to save monitor accounts to SQLite; JSON mirror will still be written: {exc}")

    def _save_accounts_to_json(self, accounts: list[dict[str, Any]]) -> None:
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
        payload = {
            "version": self.version,
            "mode": self.mode,
            "accounts": accounts,
        }
        tmp = f"{self.config_path}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        try:
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=4)
            last_exc: Exception | None = None
            for attempt in range(5):
                try:
                    os.replace(tmp, self.config_path)
                    return
                except OSError as exc:
                    last_exc = exc
                    time.sleep(0.05 * (attempt + 1))
            if last_exc:
                raise last_exc
        finally:
            try:
                if os.path.exists(tmp):
                    os.remove(tmp)
            except Exception:
                pass

    def _backup_invalid_file(self) -> str:
        if not os.path.exists(self.config_path):
            return ""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup = f"{self.config_path}.invalid.{stamp}.bak"
        try:
            os.replace(self.config_path, backup)
            return backup
        except Exception:
            try:
                Path(self.config_path).rename(backup)
                return backup
            except Exception:
                return ""
