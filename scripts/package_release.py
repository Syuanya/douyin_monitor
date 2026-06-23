from __future__ import annotations

import argparse
import os
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"

EXCLUDED_ANYWHERE_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
}

# Runtime output directories may be created below scripts/ or other helper
# folders when tools are executed from source. Exclude these at any depth,
# while keeping source packages such as app/core/diagnostics.
EXCLUDED_RUNTIME_DIRS_ANYWHERE = {
    "data",
    "downloads",
    "logs",
}

EXCLUDED_TOP_LEVEL_DIRS = {
    "cache",
    "build",
    "data",
    "diagnostics",
    "dist",
    "downloads",
    "logs",
}

EXCLUDED_SUFFIXES = {
    ".bak",
    ".download",
    ".pyc",
    ".tmp",
}

RUNTIME_CONFIG_FILES = {
    "accounts.json",
    "cookies.json",
    "cookies.secure.json",
    "douyin_content_monitor.json",
    "parse_history.json",
    "recordings.json",
    "task_records.json",
    "user_settings.json",
    "web_auth.json",
}

ALWAYS_EXCLUDE_FILES = {
    ".env",
}


def should_include(path: Path) -> bool:
    rel = path.relative_to(ROOT)
    parts = set(rel.parts)
    if parts & EXCLUDED_ANYWHERE_DIRS:
        return False
    if parts & EXCLUDED_RUNTIME_DIRS_ANYWHERE:
        return False
    if rel.parts and rel.parts[0] in EXCLUDED_TOP_LEVEL_DIRS:
        return False
    if path.name in ALWAYS_EXCLUDE_FILES:
        return False
    if path.suffix in EXCLUDED_SUFFIXES:
        return False
    if path.suffix == ".spec" and rel.parts[:2] != ("packaging", "windows"):
        return False
    if path.parent.name == "config" and path.name in RUNTIME_CONFIG_FILES:
        return False
    return True


def build_release_zip(name: str) -> Path:
    DIST_DIR.mkdir(parents=True, exist_ok=True)
    out_path = DIST_DIR / name
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    with zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob("*")):
            if not path.is_file() or not should_include(path):
                continue
            zf.write(path, arcname=str(path.relative_to(ROOT)))
    os.replace(tmp_path, out_path)
    return out_path


def inspect_zip(zip_path: Path) -> list[str]:
    problems: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            item = Path(name)
            if item.name in ALWAYS_EXCLUDE_FILES:
                problems.append(name)
            if len(item.parts) >= 2 and item.parts[0] == "config" and item.name in RUNTIME_CONFIG_FILES:
                problems.append(name)
            if item.parts and item.parts[0] in {"data", "logs", "downloads", "diagnostics"}:
                problems.append(name)
            if set(item.parts) & EXCLUDED_RUNTIME_DIRS_ANYWHERE:
                problems.append(name)
            if item.suffix == ".bak":
                problems.append(name)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a safe Douyin Monitor release archive.")
    parser.add_argument("--name", default="douyin_monitor_release.zip", help="Output zip filename inside dist/")
    args = parser.parse_args()

    if not args.name.endswith(".zip"):
        print("package_release: output name must end with .zip", file=sys.stderr)
        return 2

    out_path = build_release_zip(args.name)
    problems = inspect_zip(out_path)
    if problems:
        print("package_release: unsafe files found in release archive:", file=sys.stderr)
        for item in problems:
            print(f"  {item}", file=sys.stderr)
        try:
            out_path.unlink()
        except OSError:
            pass
        return 1
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"package_release: OK {out_path} ({size_mb:.2f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
