from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(cmd: list[str], *, optional: bool = False) -> bool:
    print("+ " + " ".join(cmd))
    completed = subprocess.run(cmd, cwd=str(ROOT), text=True)
    if completed.returncode == 0:
        return True
    if optional:
        print(f"release_gate: optional step failed with {completed.returncode}: {' '.join(cmd)}")
        return False
    raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run release-quality checks before publishing Douyin Monitor.")
    parser.add_argument("--skip-tests", action="store_true")
    parser.add_argument("--package", action="store_true", help="Build safe source release zip after checks.")
    parser.add_argument("--name", default="douyin_monitor_release.zip")
    parser.add_argument("--windows-zip", default="", help="Validate a Windows/source release zip after packaging.")
    parser.add_argument("--with-ruff", action="store_true", help="Run ruff check if installed.")
    args = parser.parse_args()

    run([sys.executable, "-m", "compileall", "-q", "app", "crawlers", "scripts", "tests", "main.py"])
    if args.with_ruff:
        run([sys.executable, "-m", "ruff", "check", "app", "crawlers", "scripts", "tests"], optional=True)
    if not args.skip_tests:
        run([sys.executable, "scripts/run_tests.py"])
    run([sys.executable, "scripts/smoke_check.py", "--strict"])
    run([sys.executable, "scripts/ui_static_check.py"])
    run([sys.executable, "scripts/ui_layout_regression_check.py"])
    run([sys.executable, "scripts/verify_legacy_migration.py"])
    run([sys.executable, "scripts/live_douyin_benchmark.py", "--parse"])
    if args.package:
        run([sys.executable, "scripts/package_release.py", "--name", args.name])
        zip_path = ROOT / "dist" / args.name
    else:
        zip_path = Path(args.windows_zip) if args.windows_zip else None
    if zip_path:
        run([sys.executable, "scripts/verify_windows_package.py", "--release-zip", str(zip_path)])
    print("release_gate: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
