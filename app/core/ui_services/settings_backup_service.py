from __future__ import annotations

import json
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from ...utils.logger import logger


@dataclass(slots=True)
class ImportResult:
    success: bool
    message: str
    files: list[str]


class SettingsBackupService:
    """Configuration import/export operations for the settings page."""

    CONFIG_PACKAGE_FILES = {"user_settings.json", "language.json", "default_settings.json"}
    FULL_BACKUP_FILES = {
        "user_settings.json",
        "language.json",
        "default_settings.json",
        "cookies.json",
        "douyin_content_monitor.json",
        "accounts.json",
        "recordings.json",
        "web_auth.json",
    }
    SENSITIVE_FILES = {"cookies.json", "web_auth.json"}

    def __init__(self, app: Any):
        self.app = app

    async def export_config_package(self) -> Path:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "config_exports")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_config_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in self.CONFIG_PACKAGE_FILES:
                    zf.write(file, arcname=file.name)
        return path

    async def export_full_backup(self) -> Path:
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "backups")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_full_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        manifest = {
            "type": "douyin_monitor_full_backup",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contains_sensitive_files": True,
            "files": [],
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in self.FULL_BACKUP_FILES and file.exists():
                    arcname = f"config/{file.name}"
                    zf.write(file, arcname=arcname)
                    manifest["files"].append(arcname)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return path

    async def export_sanitized_backup(self) -> Path:
        """Export a GitHub/share-safe backup without cookies or web auth tokens."""
        config_dir = Path(self.app.run_path, "config")
        export_dir = Path(self.app.run_path, "downloads", "backups")
        export_dir.mkdir(parents=True, exist_ok=True)
        path = export_dir / f"douyin_monitor_sanitized_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
        manifest = {
            "type": "douyin_monitor_sanitized_backup",
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "contains_sensitive_files": False,
            "removed_files": sorted(self.SENSITIVE_FILES),
            "files": [],
        }
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in config_dir.glob("*.json"):
                if file.name in self.FULL_BACKUP_FILES and file.name not in self.SENSITIVE_FILES and file.exists():
                    arcname = f"config/{file.name}"
                    zf.write(file, arcname=arcname)
                    manifest["files"].append(arcname)
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        return path

    async def import_config_package(self, path: Path) -> ImportResult:
        if not path.exists() or path.suffix.lower() != ".zip":
            return ImportResult(False, "请选择有效的 ZIP 配置包路径", [])
        parsed = self._read_config_zip(path, self.CONFIG_PACKAGE_FILES, nested=False)
        if not parsed:
            return ImportResult(False, "导入失败：配置包中没有可用配置", [])
        manager = self.app.services.config_manager
        settings = self.app.services.settings_config
        if "user_settings.json" in parsed:
            await manager.save_user_config(parsed["user_settings.json"])
            settings.adopt_user_config(parsed["user_settings.json"])
        config_dir = Path(self.app.run_path, "config")
        for name in ("language.json", "default_settings.json"):
            if name in parsed:
                await manager._save_config(str(config_dir / name), parsed[name], success_message=f"{name} imported.", error_message=f"Import {name} failed")
        self._refresh_loaded_config(parsed)
        return ImportResult(True, "配置包已导入，已刷新可即时生效的配置；下载线程等运行中设置建议重启后完全生效", sorted(parsed))

    async def import_full_backup(self, path: Path) -> ImportResult:
        if not path.exists() or path.suffix.lower() != ".zip":
            return ImportResult(False, "请选择有效的完整备份 ZIP 路径", [])
        parsed = self._read_config_zip(path, self.FULL_BACKUP_FILES, nested=True)
        if not parsed:
            return ImportResult(False, "恢复失败：备份包内没有可恢复配置", [])
        manager = self.app.services.config_manager
        config_dir = Path(self.app.run_path, "config")
        for name, value in parsed.items():
            await manager._save_config(str(config_dir / name), value, success_message=f"{name} restored.", error_message=f"Restore {name} failed")
        self._refresh_loaded_config(parsed)
        monitor = getattr(self.app.services, "douyin_content_monitor", None)
        if monitor is not None and "douyin_content_monitor.json" in parsed:
            try:
                monitor._load_accounts()
            except Exception as exc:
                logger.debug(f"reload monitor accounts after full restore failed: {exc}")
        return ImportResult(True, "完整备份已恢复，建议重启应用确保所有运行中服务重新加载。", sorted(parsed))

    def _read_config_zip(self, path: Path, allowed: set[str], *, nested: bool) -> dict[str, dict[str, Any]]:
        parsed: dict[str, dict[str, Any]] = {}
        try:
            with zipfile.ZipFile(path, "r") as zf:
                for name in zf.namelist():
                    parts = Path(name).parts
                    if nested:
                        if len(parts) != 2 or parts[0] != "config" or parts[1] not in allowed:
                            continue
                        clean_name = parts[1]
                    else:
                        clean_name = Path(name).name
                        if clean_name not in allowed:
                            continue
                    with zf.open(name) as file:
                        value = json.loads(file.read().decode("utf-8"))
                    if isinstance(value, dict):
                        parsed[clean_name] = value
        except Exception as exc:
            logger.debug(f"read settings zip failed: {path}: {exc}")
            return {}
        return parsed

    def _refresh_loaded_config(self, parsed: dict[str, dict[str, Any]]) -> None:
        settings = self.app.services.settings_config
        if "user_settings.json" in parsed:
            settings.adopt_user_config(parsed["user_settings.json"])
        if "cookies.json" in parsed:
            settings.adopt_cookies_config(parsed["cookies.json"])
        if "accounts.json" in parsed:
            settings.adopt_accounts_config(parsed["accounts.json"])
        if "language.json" in parsed:
            settings.language_option = parsed["language.json"]
            self.app.language_manager.load()
            self.app.language_manager.notify_observers()
        if "default_settings.json" in parsed:
            settings.default_config = parsed["default_settings.json"]
        if hasattr(self.app, "refresh_nav"):
            self.app.refresh_nav()
