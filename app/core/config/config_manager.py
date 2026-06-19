import asyncio
import json
import os
import shutil
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from ...utils.logger import logger
from .cookie_vault import CookieVault
from .migrations import migrate_user_config

T = TypeVar("T")


class ConfigManager:
    def __init__(self, run_path):
        self.config_path = os.path.join(run_path, "config")
        self.language_config_path = os.path.join(self.config_path, "language.json")
        self.default_config_path = os.path.join(self.config_path, "default_settings.json")
        self.user_config_path = os.path.join(self.config_path, "user_settings.json")
        self.cookies_config_path = os.path.join(self.config_path, "cookies.json")
        self.cookies_vault_path = os.path.join(self.config_path, "cookies.secure.json")
        self.about_config_path = os.path.join(self.config_path, "version.json")
        self.recordings_config_path = os.path.join(self.config_path, "recordings.json")
        self.accounts_config_path = os.path.join(self.config_path, "accounts.json")
        self.web_auth_config_path = os.path.join(self.config_path, "web_auth.json")

        os.makedirs(os.path.dirname(self.default_config_path), exist_ok=True)
        self.init()

    def init(self):
        self.init_default_config()
        self.init_user_config()
        self.init_cookies_config()
        self.init_accounts_config()
        self.init_recordings_config()
        self.init_web_auth_config()

    @staticmethod
    def _init_config(config_path, default_config=None):
        """Initialize a configuration file with default values if it does not exist."""
        if not os.path.exists(config_path):
            if default_config is None:
                default_config = {}
            try:
                ConfigManager._write_config_sync(config_path, default_config)
                logger.info(f"Initialized configuration file: {config_path}")
            except Exception as e:
                logger.error(f"Failed to initialize configuration file {config_path}: {e}")

    def init_default_config(self):
        default_config = {}
        self._init_config(self.default_config_path, default_config)

    def init_user_config(self):
        """Initialize and migrate user settings.

        Keep user choices, fill missing keys from defaults, and create a
        timestamped backup before writing the migrated file.
        """
        default_config = self.load_default_config() or {}
        default_version = int(default_config.get("config_version", 24) or 24)

        if not os.path.exists(self.user_config_path):
            self._write_config_sync(self.user_config_path, default_config)
            return

        if self._repair_invalid_json_config(self.user_config_path, default_config, reason="invalid_user_settings"):
            return

        user_config = self.load_user_config()
        if not user_config:
            self._backup_file(self.user_config_path, reason="invalid")
            self._write_config_sync(self.user_config_path, default_config)
            return

        migrated_config, changed, current_version, default_version = migrate_user_config(user_config, default_config)

        if changed:
            self._backup_file(self.user_config_path, reason=f"v{current_version}_to_v{default_version}")
            self._write_config_sync(self.user_config_path, migrated_config)
            logger.info(
                f"Migrated user settings: config_version {current_version} -> {default_version}, "
                f"missing keys filled from defaults"
            )

    @staticmethod
    def _write_config_sync(config_path, config):
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        content = json.dumps(config, ensure_ascii=False, indent=4)
        dir_name = os.path.dirname(config_path)
        fd, tmp_path = tempfile.mkstemp(suffix=".tmp", prefix=".cfg_", dir=str(dir_name))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                file.write(content)
            os.replace(tmp_path, config_path)
        except BaseException:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _backup_file(config_path, reason="backup"):
        if not os.path.exists(config_path):
            return ""
        try:
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = f"{config_path}.{reason}.{stamp}.bak"
            shutil.copy2(config_path, backup_path)
            ConfigManager._prune_backups(config_path, keep=30)
            logger.info(f"Backed up configuration file: {backup_path}")
            return backup_path
        except Exception as e:
            logger.warning(f"Failed to backup configuration file {config_path}: {e}")
            return ""

    @staticmethod
    def _prune_backups(config_path: str, keep: int = 30) -> None:
        try:
            base = Path(config_path)
            backups = sorted(base.parent.glob(f"{base.name}.*.bak"), key=lambda item: item.stat().st_mtime, reverse=True)
            for backup in backups[max(1, keep) :]:
                backup.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"Failed to prune configuration backups for {config_path}: {e}")


    @staticmethod
    def _read_json_sync(config_path):
        with open(config_path, encoding="utf-8") as file:
            return json.load(file)

    def _repair_invalid_json_config(self, config_path, default_config=None, reason="invalid_json") -> bool:
        """Backup and reset a corrupted JSON config file.

        This is intentionally conservative: only malformed JSON is replaced.
        Valid user customizations are preserved by the normal migration path.
        """
        if default_config is None:
            default_config = {}
        try:
            if not os.path.exists(config_path):
                return False
            self._read_json_sync(config_path)
            return False
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in {config_path}; backing up and recreating. error={e}")
            self._backup_file(config_path, reason=reason)
            self._write_config_sync(config_path, default_config)
            return True
        except Exception as e:
            logger.error(f"Unable to validate JSON config {config_path}: {e}")
            return False

    def init_cookies_config(self):
        cookies_config = {}
        self._init_config(self.cookies_config_path, cookies_config)
        self._repair_invalid_json_config(self.cookies_config_path, cookies_config, reason="invalid_cookies")
        self._migrate_cookies_to_vault()

    def _migrate_cookies_to_vault(self) -> None:
        try:
            cookies = self._load_config(self.cookies_config_path, "An error occurred while loading cookies config")
            if cookies:
                CookieVault(self.cookies_vault_path).save(cookies)
        except Exception as exc:
            logger.debug(f"Cookie vault migration skipped: {exc}")

    def init_accounts_config(self):
        accounts_config = {}
        self._init_config(self.accounts_config_path, accounts_config)
        self._repair_invalid_json_config(self.accounts_config_path, accounts_config, reason="invalid_accounts")

    def init_recordings_config(self):
        recordings_config = []
        self._init_config(self.recordings_config_path, recordings_config)
        self._repair_invalid_json_config(self.recordings_config_path, recordings_config, reason="invalid_recordings")

    def init_web_auth_config(self):
        web_auth_config = {}
        self._init_config(self.web_auth_config_path, web_auth_config)
        self._repair_invalid_json_config(self.web_auth_config_path, web_auth_config, reason="invalid_web_auth")

    @staticmethod
    def _load_config(config_path, error_message):
        """Load configuration from a JSON file."""
        try:
            with open(config_path, encoding="utf-8") as file:
                return json.load(file)
        except json.JSONDecodeError:
            logger.error(f"Invalid JSON format in file: {config_path}")
            return {}
        except FileNotFoundError:
            logger.error(f"Configuration file not found: {config_path}")
            return {}
        except Exception as e:
            logger.error(f"{error_message}: {e}")
            return {}

    def load_default_config(self):
        return self._load_config(self.default_config_path, "An error occurred while loading default config")

    def load_user_config(self):
        return self._load_config(self.user_config_path, "An error occurred while loading user config")

    def load_recordings_config(self):
        return self._load_config(self.recordings_config_path, "An error occurred while loading recordings config")

    def load_accounts_config(self):
        return self._load_config(self.accounts_config_path, "An error occurred while loading accounts config")

    def load_cookies_config(self):
        try:
            vault_data = CookieVault(self.cookies_vault_path).load()
            if vault_data:
                return vault_data
        except Exception as exc:
            logger.debug(f"Cookie vault load skipped: {exc}")
        return self._load_config(self.cookies_config_path, "An error occurred while loading cookies config")

    def load_about_config(self):
        return self._load_config(self.about_config_path, "An error occurred while loading about config")

    def load_language_config(self):
        return self._load_config(self.language_config_path, "An error occurred while loading language config")

    def load_i18n_config(self, path):
        """Load i18n configuration from a JSON file."""
        return self._load_config(path, "An error occurred while loading i18n config")

    def load_web_auth_config(self):
        return self._load_config(self.web_auth_config_path, "An error occurred while loading web auth config")

    _write_lock = threading.Lock()

    @staticmethod
    async def _save_config(config_path, config, success_message, error_message, backup: bool = True):
        """Save configuration to a JSON file (thread-safe, atomic write)."""
        try:
            content = json.dumps(config, ensure_ascii=False, indent=4)

            def _write_sync():
                with ConfigManager._write_lock:
                    dir_name = os.path.dirname(config_path)
                    if backup and os.path.exists(config_path):
                        ConfigManager._backup_file(config_path, reason="autosave")
                    fd, tmp_path = tempfile.mkstemp(suffix=".tmp", prefix=".cfg_", dir=str(dir_name))
                    try:
                        with os.fdopen(fd, "w", encoding="utf-8") as f:
                            f.write(content)
                        os.replace(tmp_path, config_path)
                    except BaseException:
                        # Clean up temp file on failure.
                        try:
                            os.unlink(tmp_path)
                        except OSError:
                            pass
                        raise

            await asyncio.to_thread(_write_sync)
            logger.info(success_message)
        except Exception as e:
            logger.error(f"{error_message}: {e}")

    async def save_recordings_config(self, config):
        await self._save_config(
            self.recordings_config_path,
            config,
            success_message="Recordings configuration saved.",
            error_message="An error occurred while saving recordings config",
        )

    async def save_accounts_config(self, config):
        await self._save_config(
            self.accounts_config_path,
            config,
            success_message="Accounts configuration saved.",
            error_message="An error occurred while saving accounts config",
        )

    async def save_web_auth_config(self, config):
        await self._save_config(
            self.web_auth_config_path,
            config,
            success_message="Web auth configuration saved.",
            error_message="An error occurred while saving web auth config",
        )

    async def save_user_config(self, config):
        await self._save_config(
            self.user_config_path,
            config,
            success_message="User configuration saved.",
            error_message="An error occurred while saving user config",
        )

    async def save_cookies_config(self, config):
        try:
            CookieVault(self.cookies_vault_path).save(config)
        except Exception as exc:
            logger.debug(f"Cookie vault save skipped: {exc}")
        await self._save_config(
            self.cookies_config_path,
            config,
            success_message="Cookies configuration saved.",
            error_message="An error occurred while saving cookies config",
        )

    def list_config_backups(self, config_name: str = "user_settings", limit: int = 20) -> list[dict[str, str]]:
        path = self._config_path_by_name(config_name)
        base = Path(path)
        backups = sorted(base.parent.glob(f"{base.name}.*.bak"), key=lambda item: item.stat().st_mtime, reverse=True)
        result = []
        for item in backups[: max(1, int(limit or 20))]:
            try:
                result.append(
                    {
                        "path": str(item),
                        "name": item.name,
                        "mtime": datetime.fromtimestamp(item.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                        "size": str(item.stat().st_size),
                    }
                )
            except OSError:
                continue
        return result

    async def restore_config_backup(self, backup_path: str, config_name: str = "user_settings") -> bool:
        target_path = self._config_path_by_name(config_name)
        backup = Path(str(backup_path or ""))
        target = Path(target_path)
        if not backup.exists() or backup.parent != target.parent or not backup.name.startswith(f"{target.name}.") or not backup.name.endswith(".bak"):
            return False

        def _restore_sync() -> None:
            with ConfigManager._write_lock:
                self._backup_file(target_path, reason="before_restore")
                shutil.copy2(str(backup), target_path)

        await asyncio.to_thread(_restore_sync)
        return True

    def _config_path_by_name(self, config_name: str) -> str:
        mapping = {
            "user_settings": self.user_config_path,
            "cookies": self.cookies_config_path,
            "accounts": self.accounts_config_path,
            "recordings": self.recordings_config_path,
            "web_auth": self.web_auth_config_path,
        }
        return mapping.get(str(config_name or "user_settings"), self.user_config_path)

    def get_config_value(self, key: str, default: T = None) -> T:
        user_config = self.load_user_config()
        default_config = self.load_default_config()
        return user_config.get(key, default_config.get(key, default))
