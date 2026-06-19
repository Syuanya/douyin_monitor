from __future__ import annotations

import compileall
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_PARTS = {"__pycache__", ".pytest_cache", "logs", "downloads", "tests"}
SENSITIVE_TOP_LEVEL_DIRS = {"data", "diagnostics"}
SENSITIVE_CONFIGS = {
    "cookies.json",
    "cookies.secure.json",
    "douyin_content_monitor.json",
    "accounts.json",
    "parse_history.json",
    "recordings.json",
    "task_records.json",
    "user_settings.json",
    "web_auth.json",
}


def compile_sources() -> bool:
    ok = True
    for directory in ("app", "crawlers"):
        ok = compileall.compile_dir(str(ROOT / directory), quiet=1) and ok
    return ok


def check_sensitive_files() -> list[str]:
    problems: list[str] = []
    for path in ROOT.rglob("*"):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        rel = path.relative_to(ROOT)
        if rel.parts and rel.parts[0] in SENSITIVE_TOP_LEVEL_DIRS and path.is_file():
            problems.append(str(rel))
            continue
        if path.name == ".env" or (path.parent.name == "config" and path.name in SENSITIVE_CONFIGS):
            problems.append(str(rel))
    return problems


def main() -> int:
    compile_ok = compile_sources()
    sensitive = check_sensitive_files()
    strict = "--strict" in sys.argv or os.environ.get("DOUYIN_MONITOR_STRICT_SMOKE") == "1"
    if compile_ok:
        if sensitive:
            print("smoke_check: runtime-sensitive files present in workspace (exclude them when packaging):")
            for item in sensitive:
                print(f"  {item}")
            if strict:
                print("smoke_check: strict mode failed because runtime-sensitive files are present", file=sys.stderr)
                return 1
        print("smoke_check: OK")
        return 0
    if not compile_ok:
        print("smoke_check: compile failed", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
