from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_MODULES = [
    "flet",
    "flet_video",
    "httpx",
    "yaml",
    "loguru",
    "PIL",
    "qrcode",
    "pydantic",
    "gmssl",
    "browser_cookie3",
    "tenacity",
    "rich",
]


def main() -> int:
    errors: list[str] = []
    version = sys.version_info
    if version < (3, 10):
        errors.append(f"Python version too old: {version.major}.{version.minor}.{version.micro}; require >= 3.10")
    if version >= (3, 13):
        errors.append(f"Python version too new for validated desktop runtime: {version.major}.{version.minor}.{version.micro}; use 3.10-3.12")

    for module in REQUIRED_MODULES:
        try:
            importlib.import_module(module)
        except Exception as exc:
            errors.append(f"Missing dependency {module}: {exc}")

    writable_dirs = [ROOT / "config", ROOT / "data", ROOT / "logs"]
    for folder in writable_dirs:
        try:
            folder.mkdir(parents=True, exist_ok=True)
            probe = folder / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
        except Exception as exc:
            errors.append(f"Directory not writable: {folder} ({exc})")

    if errors:
        print("runtime_check: failed")
        for error in errors:
            print(f"  {error}")
        return 1
    print("runtime_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
