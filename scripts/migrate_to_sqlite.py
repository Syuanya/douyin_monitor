from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.core.content_monitor.services.account_repository import AccountRepository
from app.core.storage.sqlite_store import SQLiteStore


def migrate(run_path: Path) -> dict[str, int]:
    store = SQLiteStore(str(run_path))
    store.ensure_schema()

    monitor_path = run_path / "config" / "douyin_content_monitor.json"
    account_repo = AccountRepository(str(monitor_path), sqlite_store=store)
    accounts = account_repo._load_accounts_from_json()
    if accounts:
        store.save_monitor_accounts(accounts)

    task_path = run_path / "config" / "task_records.json"
    task_records = []
    if task_path.exists():
        try:
            data = json.loads(task_path.read_text(encoding="utf-8"))
            raw_records = data.get("records", data) if isinstance(data, dict) else data
            task_records = [item for item in raw_records if isinstance(item, dict)] if isinstance(raw_records, list) else []
        except Exception:
            task_records = []
    if task_records:
        store.save_task_records(task_records)

    parse_path = run_path / "config" / "parse_history.json"
    parse_records = []
    if parse_path.exists():
        try:
            data = json.loads(parse_path.read_text(encoding="utf-8"))
            raw_records = data.get("records", data) if isinstance(data, dict) else data
            parse_records = [item for item in raw_records if isinstance(item, dict)] if isinstance(raw_records, list) else []
        except Exception:
            parse_records = []
    if parse_records:
        store.save_parse_history(parse_records)

    download_records = []
    for name in ("download_records.json", "download_history.json", "download_failures.json"):
        path = run_path / "config" / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            raw_records = data.get("records", data) if isinstance(data, dict) else data
            if isinstance(raw_records, list):
                download_records.extend(item for item in raw_records if isinstance(item, dict))
        except Exception:
            continue
    for record in download_records:
        store.upsert_download_record(record)

    return {
        "accounts": store.monitor_account_count(),
        "tasks": store.task_record_count(),
        "parse_history": store.parse_history_count(),
        "downloads": store.download_record_count(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate Douyin Monitor JSON runtime data into SQLite.")
    parser.add_argument("--run-path", default=str(ROOT), help="Project/run directory. Defaults to repository root.")
    args = parser.parse_args()

    result = migrate(Path(args.run_path))
    print(
        "migrate_to_sqlite: "
        f"accounts={result['accounts']} tasks={result['tasks']} "
        f"parse_history={result['parse_history']} downloads={result['downloads']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
