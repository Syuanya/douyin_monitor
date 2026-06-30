from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class StorageInspectionResult:
    path: str
    ok: bool
    writable: bool
    exists: bool
    free_gb: float | None = None
    total_gb: float | None = None
    message: str = ""

    def summary(self) -> str:
        if not self.ok:
            return self.message or f"存储目录不可用：{self.path}"
        free = f"，剩余 {self.free_gb:.1f} GB" if self.free_gb is not None else ""
        total = f" / 总计 {self.total_gb:.1f} GB" if self.total_gb is not None else ""
        return f"存储目录可用：可写{free}{total}"


@dataclass(slots=True)
class StorageMaintenanceResult:
    path: str
    ok: bool
    scanned_files: int = 0
    temp_files: int = 0
    temp_bytes: int = 0
    zero_byte_files: int = 0
    empty_dirs: int = 0
    deleted_files: int = 0
    deleted_bytes: int = 0
    skipped: int = 0
    message: str = ""

    @property
    def temp_mb(self) -> float:
        return self.temp_bytes / 1024 / 1024

    @property
    def deleted_mb(self) -> float:
        return self.deleted_bytes / 1024 / 1024

    def summary(self) -> str:
        if not self.ok:
            return self.message or f"存储维护检查失败：{self.path}"
        if self.deleted_files:
            return f"已清理临时残留 {self.deleted_files} 个，释放 {self.deleted_mb:.1f} MB。跳过 {self.skipped} 个。"
        return (
            f"已扫描 {self.scanned_files} 个文件；临时残留 {self.temp_files} 个"
            f"（{self.temp_mb:.1f} MB），0 字节文件 {self.zero_byte_files} 个，空目录 {self.empty_dirs} 个。"
        )


class SettingsStorageService:
    """Storage path inspection and maintenance used by settings UI.

    It keeps directory permission, disk-space and temporary-residue checks out
    of the Flet view so desktop/web settings endpoints can reuse the same
    behavior without duplicating file-system logic.
    """

    TEMP_SUFFIXES = {".tmp", ".part", ".download", ".crdownload"}
    TEMP_NAME_MARKERS = {".tmp", ".part", "partial", "incomplete"}
    MAX_SCAN_FILES = 20000

    def __init__(self, app: Any):
        self.app = app

    async def inspect(self, path: str) -> StorageInspectionResult:
        return await asyncio.to_thread(self._inspect_sync, path)

    async def scan_maintenance(self, path: str) -> StorageMaintenanceResult:
        return await asyncio.to_thread(self._scan_maintenance_sync, path)

    async def cleanup_temp_files(self, path: str) -> StorageMaintenanceResult:
        return await asyncio.to_thread(self._cleanup_temp_files_sync, path)

    def _inspect_sync(self, path: str) -> StorageInspectionResult:
        target = self._defaulted_path(path)
        try:
            directory = Path(target).expanduser()
            directory.mkdir(parents=True, exist_ok=True)
            exists = directory.exists() and directory.is_dir()
            if not exists:
                return StorageInspectionResult(target, False, False, False, message=f"存储目录不存在或不是文件夹：{target}")
            writable = self._can_write(directory)
            usage = shutil.disk_usage(str(directory))
            free_gb = usage.free / 1024 / 1024 / 1024
            total_gb = usage.total / 1024 / 1024 / 1024
            if not writable:
                return StorageInspectionResult(target, False, False, True, free_gb, total_gb, f"存储目录不可写：{target}")
            return StorageInspectionResult(target, True, True, True, free_gb, total_gb)
        except Exception as exc:
            return StorageInspectionResult(target, False, False, False, message=f"检查存储目录失败：{exc}")

    def _scan_maintenance_sync(self, path: str) -> StorageMaintenanceResult:
        target = self._defaulted_path(path)
        try:
            root = Path(target).expanduser().resolve()
            if not root.exists() or not root.is_dir():
                return StorageMaintenanceResult(target, False, message=f"存储目录不存在或不是文件夹：{target}")
            result = StorageMaintenanceResult(str(root), True)
            for item in self._iter_paths(root):
                if item.is_dir():
                    if self._is_empty_dir(item):
                        result.empty_dirs += 1
                    continue
                if not item.is_file():
                    continue
                result.scanned_files += 1
                try:
                    size = item.stat().st_size
                except OSError:
                    result.skipped += 1
                    continue
                if size == 0:
                    result.zero_byte_files += 1
                if self._is_temp_residue(item):
                    result.temp_files += 1
                    result.temp_bytes += size
            return result
        except Exception as exc:
            return StorageMaintenanceResult(target, False, message=f"扫描存储残留失败：{exc}")

    def _cleanup_temp_files_sync(self, path: str) -> StorageMaintenanceResult:
        target = self._defaulted_path(path)
        result = self._scan_maintenance_sync(target)
        if not result.ok:
            return result
        try:
            root = Path(result.path).expanduser().resolve()
            deleted_files = 0
            deleted_bytes = 0
            skipped = result.skipped
            for item in self._iter_paths(root):
                if not item.is_file() or not self._is_temp_residue(item):
                    continue
                try:
                    size = item.stat().st_size
                    item.unlink()
                    deleted_files += 1
                    deleted_bytes += size
                except OSError:
                    skipped += 1
            result.deleted_files = deleted_files
            result.deleted_bytes = deleted_bytes
            result.skipped = skipped
            return result
        except Exception as exc:
            return StorageMaintenanceResult(target, False, message=f"清理临时残留失败：{exc}")

    def _defaulted_path(self, path: str) -> str:
        target = str(path or "").strip()
        if not target:
            target = str(Path(self.app.run_path, "downloads", "douyin_content"))
        return target

    @classmethod
    def _iter_paths(cls, root: Path):
        count = 0
        for item in root.rglob("*"):
            yield item
            if item.is_file():
                count += 1
                if count >= cls.MAX_SCAN_FILES:
                    break

    @classmethod
    def _is_temp_residue(cls, path: Path) -> bool:
        name = path.name.lower()
        if path.suffix.lower() in cls.TEMP_SUFFIXES:
            return True
        return any(marker in name for marker in cls.TEMP_NAME_MARKERS)

    @staticmethod
    def _is_empty_dir(path: Path) -> bool:
        try:
            return path.is_dir() and not any(path.iterdir())
        except OSError:
            return False

    @staticmethod
    def _can_write(directory: Path) -> bool:
        try:
            with tempfile.NamedTemporaryFile(prefix="douyin_monitor_write_test_", dir=str(directory), delete=False) as file:
                file.write(b"ok")
                temp_path = file.name
            os.remove(temp_path)
            return True
        except Exception:
            return False
