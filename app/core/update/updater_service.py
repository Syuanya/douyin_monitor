from __future__ import annotations

import asyncio
import hashlib
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from ..version import APP_VERSION
from .versioning import is_newer_version, normalize_version

ProgressCallback = Callable[[int, int], Awaitable[None] | None]


@dataclass(frozen=True)
class UpdateAsset:
    name: str
    url: str
    sha256: str = ""
    size: int = 0
    kind: str = "portable"
    platform: str = "windows-x64"
    silent_args: str = ""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UpdateAsset":
        return cls(
            name=str(data.get("name") or data.get("filename") or "update.bin"),
            url=str(data.get("url") or data.get("browser_download_url") or ""),
            sha256=str(data.get("sha256") or "").lower(),
            size=int(data.get("size") or 0),
            kind=str(data.get("kind") or "portable"),
            platform=str(data.get("platform") or "windows-x64"),
            silent_args=str(data.get("silent_args") or ""),
        )


@dataclass(frozen=True)
class UpdateInfo:
    current_version: str
    latest_version: str
    release_notes: str
    manifest_url: str
    assets: tuple[UpdateAsset, ...]
    mandatory: bool = False

    @property
    def available(self) -> bool:
        return is_newer_version(self.latest_version, self.current_version)

    def best_asset(self, *, preferred_kind: str | None = None, system: str | None = None) -> UpdateAsset | None:
        system_key = _platform_key(system or platform.system())
        candidates = [asset for asset in self.assets if asset.url]
        platform_matches = [asset for asset in candidates if asset.platform in {system_key, "any", "windows", "windows-x64"}]
        if platform_matches:
            candidates = platform_matches
        if preferred_kind:
            for asset in candidates:
                if asset.kind == preferred_kind:
                    return asset
        for kind in ("installer", "portable", "source"):
            for asset in candidates:
                if asset.kind == kind:
                    return asset
        return candidates[0] if candidates else None


class AutoUpdateService:
    """Manifest-based update checker/downloader for packaged releases.

    The service is deliberately conservative. It never updates silently by
    default; callers can check for updates, download a verified artifact, and
    then explicitly launch the installer. Portable zip updates are staged for
    manual installation because replacing a running PyInstaller directory is
    unsafe on Windows.
    """

    def __init__(self, services: Any, *, current_version: str | None = None) -> None:
        self.services = services
        self.current_version = normalize_version(current_version or APP_VERSION)
        self.run_path = Path(getattr(services, "run_path", os.getcwd()))
        self.settings = getattr(services, "settings_config", None)
        self.update_dir = self.run_path / "downloads" / "updates"
        self.update_dir.mkdir(parents=True, exist_ok=True)
        self.last_check_path = self.run_path / "config" / "update_state.json"

    def configured_manifest_url(self) -> str:
        config = getattr(self.settings, "user_config", {}) if self.settings is not None else {}
        return str(config.get("auto_update_manifest_url") or "").strip()

    def is_enabled(self) -> bool:
        config = getattr(self.settings, "user_config", {}) if self.settings is not None else {}
        return bool(config.get("auto_update_enabled", False))

    async def check_for_updates(self, manifest_url: str | None = None, *, timeout: float = 15.0) -> UpdateInfo | None:
        url = str(manifest_url or self.configured_manifest_url() or "").strip()
        if not url:
            return None
        async with httpx.AsyncClient(follow_redirects=True, timeout=timeout) as client:
            response = await client.get(url)
            response.raise_for_status()
            manifest = response.json()
        info = self._parse_manifest(manifest, url)
        self._write_last_check(info, error="")
        return info

    def parse_manifest_file(self, path: str | os.PathLike[str]) -> UpdateInfo:
        source = Path(path)
        data = json.loads(source.read_text(encoding="utf-8"))
        return self._parse_manifest(data, source.as_uri() if source.is_absolute() else str(source))

    def _parse_manifest(self, manifest: dict[str, Any], manifest_url: str) -> UpdateInfo:
        latest = normalize_version(str(manifest.get("version") or manifest.get("latest_version") or "0.0.0"))
        assets_raw = manifest.get("assets") or []
        if isinstance(assets_raw, dict):
            assets_raw = list(assets_raw.values())
        assets = tuple(UpdateAsset.from_dict(item) for item in assets_raw if isinstance(item, dict))
        return UpdateInfo(
            current_version=self.current_version,
            latest_version=latest,
            release_notes=str(manifest.get("release_notes") or manifest.get("notes") or ""),
            manifest_url=manifest_url,
            assets=assets,
            mandatory=bool(manifest.get("mandatory", False)),
        )

    async def download_asset(self, asset: UpdateAsset, *, progress: ProgressCallback | None = None) -> Path:
        if not asset.url:
            raise ValueError("update asset URL is empty")
        target = self.update_dir / _safe_filename(asset.name)
        tmp = target.with_suffix(target.suffix + ".download")
        expected_size = max(0, int(asset.size or 0))
        downloaded = 0
        digest = hashlib.sha256()
        async with httpx.AsyncClient(follow_redirects=True, timeout=None) as client:
            async with client.stream("GET", asset.url) as response:
                response.raise_for_status()
                total = expected_size or int(response.headers.get("Content-Length") or 0)
                with tmp.open("wb") as fh:
                    async for chunk in response.aiter_bytes(1024 * 512):
                        if not chunk:
                            continue
                        fh.write(chunk)
                        digest.update(chunk)
                        downloaded += len(chunk)
                        if progress is not None:
                            result = progress(downloaded, total)
                            if asyncio.iscoroutine(result):
                                await result
        actual_hash = digest.hexdigest().lower()
        if asset.sha256 and actual_hash != asset.sha256.lower():
            tmp.unlink(missing_ok=True)
            raise ValueError(f"update artifact sha256 mismatch: expected {asset.sha256}, got {actual_hash}")
        if expected_size and tmp.stat().st_size != expected_size:
            tmp.unlink(missing_ok=True)
            raise ValueError(f"update artifact size mismatch: expected {expected_size}, got {tmp.stat().st_size}")
        os.replace(tmp, target)
        return target

    def build_install_command(self, artifact: str | os.PathLike[str], asset: UpdateAsset | None = None, *, silent: bool = False) -> list[str]:
        path = Path(artifact)
        kind = (asset.kind if asset is not None else _guess_asset_kind(path.name)).lower()
        if platform.system().lower() != "windows":
            return [str(path)]
        if kind == "installer" or path.suffix.lower() == ".exe":
            args = [str(path)]
            if silent:
                silent_args = asset.silent_args if asset is not None and asset.silent_args else "/VERYSILENT /NORESTART /CLOSEAPPLICATIONS"
                args.extend(silent_args.split())
            return args
        # Zip/portable updates are intentionally not applied over the running directory.
        return ["explorer.exe", str(path.parent)]

    def launch_installer(self, artifact: str | os.PathLike[str], asset: UpdateAsset | None = None, *, silent: bool = False) -> subprocess.Popen[Any]:
        cmd = self.build_install_command(artifact, asset, silent=silent)
        return subprocess.Popen(cmd, cwd=str(Path(artifact).parent))

    def _write_last_check(self, info: UpdateInfo | None, *, error: str) -> None:
        self.last_check_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "checked_at": time.time(),
            "current_version": self.current_version,
            "latest_version": info.latest_version if info else "",
            "available": bool(info.available) if info else False,
            "error": error,
        }
        tmp = self.last_check_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.last_check_path)


def _platform_key(system: str) -> str:
    text = str(system or "").lower()
    if text.startswith("win"):
        return "windows-x64"
    if text.startswith("darwin") or text.startswith("mac"):
        return "macos"
    if text.startswith("linux"):
        return "linux"
    return "any"


def _guess_asset_kind(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".exe") or "setup" in lower or "installer" in lower:
        return "installer"
    if lower.endswith(".zip"):
        return "portable"
    return "artifact"


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch for ch in str(name or "update.bin") if ch not in '<>:"/\\|?*').strip()
    return cleaned or "update.bin"
