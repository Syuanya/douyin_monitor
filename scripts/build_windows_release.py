from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "packaging" / "windows" / "douyin_monitor.spec"
ISS_PATH = ROOT / "packaging" / "windows" / "installer.iss"
RUNTIME_CONFIG_FILES = {
    "cookies.json",
    "cookies.secure.json",
    "douyin_content_monitor.json",
    "parse_history.json",
    "task_center.json",
    "user_settings.json",
}
RUNTIME_DIRS = {"data", "logs", "downloads", "diagnostics", "__pycache__"}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check)


def ensure_windows() -> None:
    if os.name != "nt":
        raise SystemExit("build_windows_release.py must be run on Windows to produce .exe/.installer artifacts.")


def read_version() -> str:
    version_file = ROOT / "VERSION"
    if version_file.exists():
        text = version_file.read_text(encoding="utf-8").strip()
        if text:
            return text.lstrip("vV")
    namespace: dict[str, str] = {}
    exec((ROOT / "app" / "core" / "version.py").read_text(encoding="utf-8"), namespace)
    return str(namespace.get("APP_VERSION") or "0.0.0").lstrip("vV")


def preflight(skip_tests: bool) -> None:
    run([sys.executable, "scripts/check_runtime.py"])
    run([sys.executable, "-m", "compileall", "-q", "app", "crawlers", "scripts", "tests", "main.py"])
    if not skip_tests:
        run([sys.executable, "scripts/run_tests.py"])
    run([sys.executable, "scripts/smoke_check.py", "--strict"])


def build_portable(clean: bool) -> Path:
    if clean:
        shutil.rmtree(ROOT / "build", ignore_errors=True)
        shutil.rmtree(ROOT / "dist" / "DouyinMonitor", ignore_errors=True)
    try:
        import PyInstaller.__main__  # type: ignore
    except Exception:
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])
        import PyInstaller.__main__  # type: ignore

    PyInstaller.__main__.run([str(SPEC_PATH), "--noconfirm"])
    out_dir = ROOT / "dist" / "DouyinMonitor"
    if not out_dir.exists():
        raise SystemExit(f"PyInstaller output missing: {out_dir}")
    remove_runtime_data(out_dir)
    return out_dir


def remove_runtime_data(out_dir: Path) -> None:
    """Remove local runtime/private data from the portable release folder."""

    for relative_dir in RUNTIME_DIRS:
        target = out_dir / relative_dir
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
    config_dir = out_dir / "config"
    for filename in RUNTIME_CONFIG_FILES:
        target = config_dir / filename
        try:
            target.unlink(missing_ok=True)
        except OSError:
            pass


def build_portable_zip(out_dir: Path, version: str) -> Path:
    zip_path = ROOT / "dist" / f"DouyinMonitor-{version}-windows-x64-portable.zip"
    tmp_path = zip_path.with_suffix(zip_path.suffix + ".tmp")
    tmp_path.unlink(missing_ok=True)
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(out_dir.rglob("*")):
            if not path.is_file():
                continue
            zf.write(path, arcname=str(Path(out_dir.name) / path.relative_to(out_dir)))
    os.replace(tmp_path, zip_path)
    return zip_path


def build_installer(version: str) -> Path:
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not iscc:
        raise SystemExit("Inno Setup compiler (ISCC.exe) not found. Install Inno Setup or omit --installer.")
    run([iscc, f"/DMyAppVersion={version}", str(ISS_PATH)])
    output = ROOT / "dist" / "installer" / f"DouyinMonitorSetup-{version}.exe"
    legacy_output = ROOT / "dist" / "installer" / "DouyinMonitorSetup.exe"
    if legacy_output.exists() and not output.exists():
        legacy_output.rename(output)
    if not output.exists():
        candidates = sorted((ROOT / "dist" / "installer").glob("*.exe"))
        if candidates:
            return candidates[-1]
        raise SystemExit("Inno Setup did not create an installer exe.")
    return output


def sign_artifacts(paths: list[Path], *, strict: bool) -> None:
    if not paths:
        return
    cmd = [sys.executable, "scripts/sign_windows_artifacts.py", *[str(path) for path in paths]]
    if strict:
        cmd.append("--strict")
    run(cmd)


def generate_update_manifest(artifacts: list[Path], *, version: str, base_url: str, channel: str) -> Path:
    manifest = ROOT / "dist" / "update_manifest.json"
    cmd = [
        sys.executable,
        "scripts/generate_update_manifest.py",
        "--version",
        version,
        "--channel",
        channel,
        "--output",
        str(manifest),
    ]
    if base_url:
        cmd.extend(["--base-url", base_url])
    for artifact in artifacts:
        cmd.extend(["--artifact", str(artifact)])
    run(cmd)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows portable exe, installer, signing and update manifest artifacts.")
    parser.add_argument("--installer", action="store_true", help="Also build Inno Setup installer.")
    parser.add_argument("--portable-zip", action="store_true", help="Create a portable zip for GitHub Releases / auto-update manifests.")
    parser.add_argument("--manifest", action="store_true", help="Generate update_manifest.json for built artifacts.")
    parser.add_argument("--update-base-url", default=os.environ.get("UPDATE_BASE_URL", ""), help="Public base URL for update artifacts.")
    parser.add_argument("--update-channel", default=os.environ.get("UPDATE_CHANNEL", "stable"), choices=["stable", "beta", "dev"])
    parser.add_argument("--sign", action="store_true", help="Sign exe/installer artifacts with signtool when certificate env vars are configured.")
    parser.add_argument("--strict-sign", action="store_true", help="Fail when signing is requested but no certificate/signtool is available.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unit tests during preflight.")
    parser.add_argument("--no-clean", action="store_true", help="Do not remove previous build output.")
    args = parser.parse_args()

    ensure_windows()
    version = read_version()
    preflight(skip_tests=args.skip_tests)
    out_dir = build_portable(clean=not args.no_clean)
    print(f"Windows portable build OK: {out_dir}")
    artifacts: list[Path] = []
    exe_path = out_dir / "DouyinMonitor.exe"
    if exe_path.exists():
        artifacts.append(exe_path)
    if args.sign:
        sign_artifacts([out_dir], strict=args.strict_sign)
    if args.portable_zip:
        artifacts.append(build_portable_zip(out_dir, version))
    if args.installer:
        installer_path = build_installer(version)
        artifacts.append(installer_path)
        if args.sign:
            sign_artifacts([installer_path], strict=args.strict_sign)
        print(f"Windows installer build OK: {installer_path}")
    publish_artifacts = [path for path in artifacts if path.suffix.lower() in {".zip", ".exe"} and path.name != "DouyinMonitor.exe"]
    if args.manifest:
        manifest = generate_update_manifest(publish_artifacts or artifacts, version=version, base_url=args.update_base_url, channel=args.update_channel)
        print(f"Update manifest OK: {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
