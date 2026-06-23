from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from app.core.update import AutoUpdateService, is_newer_version
from scripts.generate_update_manifest import build_manifest


class DummySettings:
    user_config = {
        "auto_update_enabled": True,
        "auto_update_manifest_url": "https://example.invalid/update_manifest.json",
        "auto_update_install_kind": "installer",
    }


class DummyServices:
    run_path = "."
    settings_config = DummySettings()


def test_version_comparison() -> None:
    assert is_newer_version("1.0.1", "1.0.0")
    assert is_newer_version("v2.0.0", "1.9.9")
    assert not is_newer_version("1.0.0", "1.0.0")


def test_update_manifest_parse_and_best_asset(tmp_path: Path) -> None:
    artifact = tmp_path / "DouyinMonitorSetup-1.2.3.exe"
    artifact.write_bytes(b"installer")
    manifest = build_manifest(
        artifacts=[artifact],
        base_url="https://example.invalid/releases/v1.2.3",
        version="1.2.3",
        channel="stable",
        notes="test",
        mandatory=False,
    )
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    service = AutoUpdateService(DummyServices(), current_version="1.2.2")
    info = service.parse_manifest_file(manifest_path)
    assert info.available
    asset = info.best_asset(preferred_kind="installer")
    assert asset is not None
    assert asset.kind == "installer"
    assert asset.sha256
    assert asset.silent_args


def test_release_automation_scaffold_exists() -> None:
    required = [
        ".github/workflows/ci.yml",
        ".github/workflows/release.yml",
        "scripts/generate_update_manifest.py",
        "scripts/sign_windows_artifacts.py",
        "scripts/release_gate.py",
        "docs/INSTALLER_AUTO_UPDATE_SIGNING_CICD.md",
        "docs/RELEASE_PROCESS.md",
        "app/core/update/updater_service.py",
        "packaging/windows/apply_update.ps1",
    ]
    for item in required:
        assert Path(item).is_file(), item


def test_generate_update_manifest_cli(tmp_path: Path) -> None:
    artifact = tmp_path / "portable.zip"
    artifact.write_bytes(b"zip")
    output = tmp_path / "update_manifest.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/generate_update_manifest.py",
            "--artifact",
            str(artifact),
            "--base-url",
            "https://example.invalid/downloads",
            "--version",
            "9.9.9",
            "--output",
            str(output),
        ],
        text=True,
        capture_output=True,
    )
    assert completed.returncode == 0, completed.stderr
    data = json.loads(output.read_text(encoding="utf-8"))
    assert data["version"] == "9.9.9"
    assert data["assets"][0]["url"].endswith("/portable.zip")
