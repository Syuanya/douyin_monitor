from __future__ import annotations

import os
import json
import sqlite3
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 4


class SQLiteStore:
    """Small SQLite foundation for future runtime data migration.

    SQLite is now the primary runtime store for monitor accounts, monitor
    items and task records. JSON files are still maintained as compatibility
    mirrors so existing import/export and manual recovery workflows keep
    working while the app migrates incrementally.
    """

    def __init__(self, run_path: str, relative_path: str = "data/douyin_monitor.sqlite3"):
        self.path = Path(run_path) / relative_path

    def connect(self) -> sqlite3.Connection:
        os.makedirs(self.path.parent, exist_ok=True)
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def ensure_schema(self) -> None:
        with self.connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS app_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            conn.execute(
                """
                INSERT INTO app_metadata(key, value, updated_at)
                VALUES('schema_version', ?, CURRENT_TIMESTAMP)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (str(SCHEMA_VERSION),),
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_accounts (
                    account_id TEXT PRIMARY KEY,
                    homepage_url TEXT NOT NULL DEFAULT '',
                    display_name TEXT NOT NULL DEFAULT '',
                    group_name TEXT NOT NULL DEFAULT '',
                    monitor_enabled INTEGER NOT NULL DEFAULT 0,
                    last_check_time TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monitor_accounts_homepage
                ON monitor_accounts(homepage_url)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS monitor_items (
                    account_id TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    title TEXT NOT NULL DEFAULT '',
                    media_type TEXT NOT NULL DEFAULT 'video',
                    status TEXT NOT NULL DEFAULT 'active',
                    publish_time TEXT NOT NULL DEFAULT '',
                    first_seen_time TEXT NOT NULL DEFAULT '',
                    last_seen_time TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL,
                    PRIMARY KEY(account_id, item_id),
                    FOREIGN KEY(account_id) REFERENCES monitor_accounts(account_id) ON DELETE CASCADE
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monitor_items_account_status
                ON monitor_items(account_id, status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_monitor_items_publish_time
                ON monitor_items(publish_time)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS task_records (
                    task_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_task_records_status
                ON task_records(status)
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS parse_history (
                    history_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL DEFAULT '',
                    source_text TEXT NOT NULL DEFAULT '',
                    success_count INTEGER NOT NULL DEFAULT 0,
                    failed_count INTEGER NOT NULL DEFAULT 0,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    payload_json TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS download_records (
                    download_id TEXT PRIMARY KEY,
                    url TEXT NOT NULL DEFAULT '',
                    save_path TEXT NOT NULL DEFAULT '',
                    kind TEXT NOT NULL DEFAULT '',
                    label TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'pending',
                    bytes_downloaded INTEGER NOT NULL DEFAULT 0,
                    total_bytes INTEGER NOT NULL DEFAULT 0,
                    error TEXT NOT NULL DEFAULT '',
                    task_id TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    finished_at TEXT NOT NULL DEFAULT '',
                    payload_json TEXT NOT NULL
                )
                """
            )
            self._ensure_columns(
                conn,
                "download_records",
                {
                    "bytes_downloaded": "INTEGER NOT NULL DEFAULT 0",
                    "total_bytes": "INTEGER NOT NULL DEFAULT 0",
                    "task_id": "TEXT NOT NULL DEFAULT ''",
                    "finished_at": "TEXT NOT NULL DEFAULT ''",
                },
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_download_records_status
                ON download_records(status)
                """
            )
            conn.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_download_records_path
                ON download_records(save_path)
                """
            )

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: dict[str, str]) -> None:
        existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, definition in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")

    def get_metadata(self, key: str, default: Any = None) -> str | Any:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM app_metadata WHERE key = ?", (key,)).fetchone()
        return row["value"] if row is not None else default

    def monitor_account_count(self) -> int:
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM monitor_accounts").fetchone()
        return int(row["value"] if row is not None else 0)

    def load_monitor_accounts(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as conn:
            account_rows = conn.execute(
                """
                SELECT account_id, payload_json
                FROM monitor_accounts
                ORDER BY rowid ASC
                """
            ).fetchall()
            item_rows = conn.execute(
                """
                SELECT account_id, payload_json
                FROM monitor_items
                ORDER BY account_id ASC, publish_time DESC, first_seen_time DESC, item_id DESC
                """
            ).fetchall()

        items_by_account: dict[str, list[dict[str, Any]]] = {}
        for row in item_rows:
            try:
                item = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(item, dict):
                items_by_account.setdefault(str(row["account_id"]), []).append(item)

        accounts: list[dict[str, Any]] = []
        for row in account_rows:
            try:
                account = json.loads(row["payload_json"])
            except Exception:
                continue
            if not isinstance(account, dict):
                continue
            account_id = str(account.get("account_id") or row["account_id"])
            if account_id in items_by_account:
                account["items"] = items_by_account[account_id]
            accounts.append(account)
        return accounts

    def save_monitor_accounts(self, accounts: list[dict[str, Any]]) -> None:
        self.ensure_schema()
        with self.connect() as conn:
            conn.execute("DELETE FROM monitor_items")
            conn.execute("DELETE FROM monitor_accounts")
            for account in accounts:
                if not isinstance(account, dict):
                    continue
                account_id = str(account.get("account_id") or "").strip()
                if not account_id:
                    continue
                conn.execute(
                    """
                    INSERT INTO monitor_accounts(
                        account_id, homepage_url, display_name, group_name,
                        monitor_enabled, last_check_time, updated_at, payload_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP, ?)
                    """,
                    (
                        account_id,
                        str(account.get("homepage_url") or ""),
                        str(account.get("display_name") or ""),
                        str(account.get("group_name") or ""),
                        1 if bool(account.get("monitor_enabled")) else 0,
                        str(account.get("last_check_time") or ""),
                        json.dumps(account, ensure_ascii=False),
                    ),
                )
                for item in account.get("items", []) if isinstance(account.get("items"), list) else []:
                    if not isinstance(item, dict):
                        continue
                    item_id = str(item.get("item_id") or "").strip()
                    if not item_id:
                        continue
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO monitor_items(
                            account_id, item_id, title, media_type, status,
                            publish_time, first_seen_time, last_seen_time, payload_json
                        )
                        VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            account_id,
                            item_id,
                            str(item.get("title") or ""),
                            str(item.get("media_type") or item.get("type") or "video"),
                            str(item.get("status") or "active"),
                            str(item.get("publish_time") or ""),
                            str(item.get("first_seen_time") or ""),
                            str(item.get("last_seen_time") or ""),
                            json.dumps(item, ensure_ascii=False),
                        ),
                    )

    def task_record_count(self) -> int:
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM task_records").fetchone()
        return int(row["value"] if row is not None else 0)

    def load_task_records(self) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM task_records
                ORDER BY sort_order ASC
                """
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def save_task_records(self, records: list[dict[str, Any]], max_records: int = 200) -> None:
        self.ensure_schema()
        trimmed = [record for record in records if isinstance(record, dict)][: max(1, int(max_records or 200))]
        with self.connect() as conn:
            conn.execute("DELETE FROM task_records")
            for index, record in enumerate(trimmed):
                task_id = str(record.get("task_id") or "").strip()
                if not task_id:
                    continue
                conn.execute(
                    """
                    INSERT OR REPLACE INTO task_records(
                        task_id, title, category, status, updated_at, sort_order, payload_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        str(record.get("title") or ""),
                        str(record.get("category") or ""),
                        str(record.get("status") or ""),
                        str(record.get("updated_at") or ""),
                        index,
                        json.dumps(record, ensure_ascii=False),
                    ),
                )

    def parse_history_count(self) -> int:
        self.ensure_schema()
        with self.connect() as conn:
            row = conn.execute("SELECT COUNT(*) AS value FROM parse_history").fetchone()
        return int(row["value"] if row is not None else 0)

    def load_parse_history(self, limit: int = 50) -> list[dict[str, Any]]:
        self.ensure_schema()
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT payload_json
                FROM parse_history
                ORDER BY sort_order ASC
                LIMIT ?
                """,
                (max(1, int(limit or 50)),),
            ).fetchall()
        records: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                records.append(payload)
        return records

    def save_parse_history(self, records: list[dict[str, Any]], max_records: int = 50) -> None:
        self.ensure_schema()
        trimmed = [record for record in records if isinstance(record, dict)][: max(1, int(max_records or 50))]
        with self.connect() as conn:
            conn.execute("DELETE FROM parse_history")
            for index, record in enumerate(trimmed):
                history_id = str(record.get("history_id") or record.get("id") or uuid.uuid4().hex)
                record = dict(record)
                record["history_id"] = history_id
                conn.execute(
                    """
                    INSERT OR REPLACE INTO parse_history(
                        history_id, created_at, source_text, success_count,
                        failed_count, sort_order, payload_json
                    )
                    VALUES(?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        history_id,
                        str(record.get("time") or record.get("created_at") or ""),
                        str(record.get("input_text") or record.get("source_text") or ""),
                        _safe_int(record.get("success", record.get("success_count")), 0),
                        _safe_int(record.get("failed", record.get("failed_count")), 0),
                        index,
                        json.dumps(record, ensure_ascii=False),
                    ),
                )

    def upsert_download_record(self, record: dict[str, Any]) -> str:
        self.ensure_schema()
        download_id = str(record.get("download_id") or uuid.uuid4().hex)
        payload = dict(record)
        payload["download_id"] = download_id
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO download_records(
                    download_id, url, save_path, kind, label, status,
                    bytes_downloaded, total_bytes, error, task_id,
                    created_at, updated_at, finished_at, payload_json
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, COALESCE(?, CURRENT_TIMESTAMP), CURRENT_TIMESTAMP, ?, ?)
                ON CONFLICT(download_id) DO UPDATE SET
                    url = excluded.url,
                    save_path = excluded.save_path,
                    kind = excluded.kind,
                    label = excluded.label,
                    status = excluded.status,
                    bytes_downloaded = excluded.bytes_downloaded,
                    total_bytes = excluded.total_bytes,
                    error = excluded.error,
                    task_id = excluded.task_id,
                    updated_at = CURRENT_TIMESTAMP,
                    finished_at = excluded.finished_at,
                    payload_json = excluded.payload_json
                """,
                (
                    download_id,
                    str(payload.get("url") or ""),
                    str(payload.get("save_path") or ""),
                    str(payload.get("kind") or ""),
                    str(payload.get("label") or ""),
                    str(payload.get("status") or "pending"),
                    _safe_int(payload.get("bytes_downloaded"), 0),
                    _safe_int(payload.get("total_bytes"), 0),
                    str(payload.get("error") or ""),
                    str(payload.get("task_id") or ""),
                    str(payload.get("created_at") or ""),
                    str(payload.get("finished_at") or ""),
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
        return download_id

    def get_download_record(self, download_id: str) -> dict[str, Any] | None:
        records = self.load_download_records(limit=1, download_id=download_id)
        return records[0] if records else None

    def update_download_record(self, download_id: str, **updates: Any) -> None:
        records = self.load_download_records(limit=1, download_id=download_id)
        payload = dict(records[0]) if records else {"download_id": download_id}
        payload.update(updates)
        self.upsert_download_record(payload)

    def mark_interrupted_downloads_recoverable(self) -> int:
        """Move incomplete in-flight downloads to a recoverable state.

        This is intended to run on application startup. It prevents records
        left as ``running`` or ``pending`` after a process crash from being
        mistaken for active downloads.
        """

        self.ensure_schema()
        changed = 0
        records = self.load_download_records(statuses=["running", "pending"], limit=1000)
        for record in records:
            download_id = str(record.get("download_id") or "")
            if not download_id:
                continue
            self.update_download_record(
                download_id,
                status="recoverable",
                error=str(record.get("error") or "interrupted before completion"),
            )
            changed += 1
        return changed

    def load_download_records(
        self,
        *,
        statuses: list[str] | None = None,
        limit: int = 200,
        offset: int = 0,
        download_id: str = "",
        query: str = "",
    ) -> list[dict[str, Any]]:
        self.ensure_schema()
        params: list[Any] = []
        where: list[str] = []
        if download_id:
            where.append("download_id = ?")
            params.append(download_id)
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if query:
            where.append("(url LIKE ? OR save_path LIKE ? OR kind LIKE ? OR label LIKE ? OR error LIKE ?)")
            like = f"%{query}%"
            params.extend([like, like, like, like, like])
        clause = " WHERE " + " AND ".join(where) if where else ""
        params.append(max(1, int(limit or 200)))
        params.append(max(0, int(offset or 0)))
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT payload_json
                FROM download_records
                {clause}
                ORDER BY updated_at DESC
                LIMIT ? OFFSET ?
                """,
                params,
            ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            try:
                payload = json.loads(row["payload_json"])
            except Exception:
                continue
            if isinstance(payload, dict):
                result.append(payload)
        return result

    def download_record_count(self, statuses: list[str] | None = None) -> int:
        self.ensure_schema()
        params: list[Any] = []
        where = ""
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where = f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        with self.connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS value FROM download_records{where}", params).fetchone()
        return int(row["value"] if row is not None else 0)

    def delete_download_records(
        self,
        *,
        statuses: list[str] | None = None,
        download_ids: list[str] | None = None,
        older_than_days: int | None = None,
    ) -> int:
        self.ensure_schema()
        where: list[str] = []
        params: list[Any] = []
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            where.append(f"status IN ({placeholders})")
            params.extend(statuses)
        if download_ids:
            placeholders = ",".join("?" for _ in download_ids)
            where.append(f"download_id IN ({placeholders})")
            params.extend(download_ids)
        if older_than_days is not None:
            cutoff = datetime.now() - timedelta(days=max(0, int(older_than_days)))
            where.append("updated_at < ?")
            params.append(cutoff.isoformat(timespec="seconds"))
        clause = " WHERE " + " AND ".join(where) if where else ""
        with self.connect() as conn:
            cursor = conn.execute(f"DELETE FROM download_records{clause}", params)
            return int(cursor.rowcount or 0)

    def vacuum(self) -> None:
        self.ensure_schema()
        conn = self.connect()
        try:
            conn.isolation_level = None
            conn.execute("VACUUM")
        finally:
            conn.close()

    def backup_database(self, destination_dir: str | os.PathLike[str]) -> str:
        self.ensure_schema()
        target_dir = Path(destination_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = target_dir / f"douyin_monitor_sqlite_backup_{stamp}.sqlite3"
        shutil.copy2(self.path, out_path)
        return str(out_path)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
