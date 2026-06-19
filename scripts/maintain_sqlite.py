from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.storage.sqlite_store import SQLiteStore


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain Douyin Monitor SQLite runtime database.")
    parser.add_argument("--run-path", default=str(ROOT), help="Project/run directory. Defaults to repository root.")
    parser.add_argument("--backup", action="store_true", help="Create a timestamped database backup.")
    parser.add_argument("--backup-dir", default="", help="Backup directory. Defaults to <run-path>/data/backups.")
    parser.add_argument("--vacuum", action="store_true", help="Run SQLite VACUUM after cleanup.")
    parser.add_argument("--delete-completed-downloads", action="store_true", help="Delete completed download history records.")
    parser.add_argument("--delete-failed-downloads", action="store_true", help="Delete failed/cancelled download history records.")
    parser.add_argument("--older-than-days", type=int, default=None, help="Only delete records older than N days.")
    args = parser.parse_args()

    run_path = Path(args.run_path)
    store = SQLiteStore(str(run_path))
    store.ensure_schema()

    backup_path = ""
    if args.backup:
        backup_dir = Path(args.backup_dir) if args.backup_dir else run_path / "data" / "backups"
        backup_path = store.backup_database(backup_dir)

    deleted = 0
    if args.delete_completed_downloads:
        deleted += store.delete_download_records(statuses=["completed"], older_than_days=args.older_than_days)
    if args.delete_failed_downloads:
        deleted += store.delete_download_records(statuses=["failed", "cancelled"], older_than_days=args.older_than_days)

    if args.vacuum:
        store.vacuum()

    print(
        "maintain_sqlite: "
        f"downloads={store.download_record_count()} deleted={deleted}"
        + (f" backup={backup_path}" if backup_path else "")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
