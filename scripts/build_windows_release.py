from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
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
}
RUNTIME_DIRS = {"data", "logs", "downloads", "diagnostics", "__pycache__"}


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    print("+ " + " ".join(cmd))
    return subprocess.run(cmd, cwd=ROOT, text=True, check=check)


def ensure_windows() -> None:
    if os.name != "nt":
        raise SystemExit("build_windows_release.py must be run on Windows to produce .exe/.installer artifacts.")


def preflight(skip_tests: bool) -> None:
    run([sys.executable, "scripts/check_runtime.py"])
    run([sys.executable, "-m", "compileall", "-q", "app", "crawlers", "scripts", "tests", "main.py"])
    if not skip_tests:
        run([sys.executable, "scripts/run_tests.py"])
    run([sys.executable, "scripts/smoke_check.py"])


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


def build_installer() -> None:
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    if not iscc:
        raise SystemExit("Inno Setup compiler (ISCC.exe) not found. Install Inno Setup or omit --installer.")
    run([iscc, str(ISS_PATH)])


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Windows portable exe and optional installer.")
    parser.add_argument("--installer", action="store_true", help="Also build Inno Setup installer.")
    parser.add_argument("--skip-tests", action="store_true", help="Skip unit tests during preflight.")
    parser.add_argument("--no-clean", action="store_true", help="Do not remove previous build output.")
    args = parser.parse_args()

    ensure_windows()
    preflight(skip_tests=args.skip_tests)
    out_dir = build_portable(clean=not args.no_clean)
    print(f"Windows portable build OK: {out_dir}")
    if args.installer:
        build_installer()
        print("Windows installer build OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
