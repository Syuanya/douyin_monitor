from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.privacy.local_data_cleaner import LocalDataCleaner


def main() -> int:
    parser = argparse.ArgumentParser(description="Preview or clear local runtime/sensitive Douyin Monitor data.")
    parser.add_argument("--run-path", default=str(ROOT), help="Project/run directory.")
    parser.add_argument("--yes", action="store_true", help="Actually delete files. Without this flag it is dry-run only.")
    parser.add_argument("--include-database", action="store_true", help="Also delete SQLite runtime database files.")
    parser.add_argument("--include-logs", action="store_true", help="Also delete log files.")
    args = parser.parse_args()

    cleaner = LocalDataCleaner(args.run_path)
    result = cleaner.clean(
        dry_run=not args.yes,
        include_database=args.include_database,
        include_logs=args.include_logs,
    )
    mode = "deleted" if args.yes else "dry-run"
    print(f"clear_local_data: {mode} scanned={result.scanned} matched={result.removed} failed={result.failed}")
    for path in result.paths:
        print(f"  {path}")
    for error in result.errors:
        print(f"ERROR: {error}", file=sys.stderr)
    return 1 if result.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
