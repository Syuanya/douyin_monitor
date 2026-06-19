from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    version_file = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    code = (ROOT / "app/core/version.py").read_text(encoding="utf-8")
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', code)
    code_version = match.group(1) if match else ""
    if not version_file or version_file != code_version:
        print(f"version_check: mismatch VERSION={version_file!r} APP_VERSION={code_version!r}", file=sys.stderr)
        return 1
    print(f"version_check: OK {version_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
