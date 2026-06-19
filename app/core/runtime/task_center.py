from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


TASK_STATUS_WAITING = "等待中"
TASK_STATUS_RUNNING = "运行中"
TASK_STATUS_COMPLETED = "完成"
TASK_STATUS_FAILED = "失败"
TASK_STATUS_CANCELLED = "已取消"


@dataclass(slots=True)
class TaskRecord:
    task_id: str
    title: str
    category: str = "任务"
    status: str = TASK_STATUS_WAITING
    detail: str = ""
    total: int = 0
    completed: int = 0
    success_count: int = 0
    failed_count: int = 0
    started_at: str = ""
    updated_at: str = ""
    finished_at: str = ""
    retry_action: str = ""
    retry_payload: dict[str, Any] = field(default_factory=dict)


def classify_failure(reason: str) -> dict[str, str]:
    advice = classify_failure_advice(reason)
    return {"category": advice.category, "next_step": advice.next_step}


class TaskCenter:
    def __init__(self, max_records: int = 200, storage_path: str = "", sqlite_store: Any | None = None):
        self.max_records = max(20, int(max_records or 200))
        self._records: list[TaskRecord] = []
        self._lock = threading.Lock()
        self.storage_path = str(storage_path or "")
        self.sqlite_store = sqlite_store
        self._last_save_at = 0.0
        self._save_interval_seconds = 1.0
        self._dirty = False
        self._load()

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def start(
        self,
        title: str,
        category: str = "任务",
        detail: str = "",
        total: int = 0,
        retry_action: str = "",
        retry_payload: dict[str, Any] | None = None,
    ) -> str:
        now = self._now()
        record = TaskRecord(
            task_id=uuid.uuid4().hex,
            title=str(title or "未命名任务"),
            category=str(category or "任务"),
            status=TASK_STATUS_RUNNING,
            detail=str(detail or ""),
            total=max(0, int(total or 0)),
            started_at=now,
            updated_at=now,
            retry_action=str(retry_action or ""),
            retry_payload=dict(retry_payload or {}),
        )
        with self._lock:
            self._records.insert(0, record)
            if len(self._records) > self.max_records:
                self._records = self._records[: self.max_records]
            self._save_locked(force=True)
        return record.task_id

    def progress(self, task_id: str, **updates: Any) -> None:
        with self._lock:
            record = self._find_locked(task_id)
            if record is None:
                return
            for key in ("status", "detail"):
                if key in updates and updates[key] is not None:
                    setattr(record, key, str(updates[key]))
            for key in ("total", "completed", "success_count", "failed_count"):
                if key in updates and updates[key] is not None:
                    try:
                        setattr(record, key, max(0, int(updates[key])))
                    except (TypeError, ValueError):
                        pass
            if isinstance(updates.get("retry_payload"), dict):
                record.retry_payload = dict(updates["retry_payload"])
            record.updated_at = self._now()
            self._save_locked()

    def update_retry_payload(self, task_id: str, retry_payload: dict[str, Any]) -> None:
        with self._lock:
            record = self._find_locked(task_id)
            if record is None:
                return
            record.retry_payload = dict(retry_payload or {})
            record.updated_at = self._now()
            self._save_locked(force=True)

    def finish(self, task_id: str, success: bool = True, detail: str = "") -> None:
        now = self._now()
        with self._lock:
            record = self._find_locked(task_id)
            if record is None:
                return
            record.status = TASK_STATUS_COMPLETED if success else TASK_STATUS_FAILED
            if detail:
                record.detail = str(detail)
            if success and record.total and record.completed < record.total:
                record.completed = record.total
            record.updated_at = now
            record.finished_at = now
            self._save_locked(force=True)

    def cancel(self, task_id: str, detail: str = "任务已取消") -> None:
        now = self._now()
        with self._lock:
            record = self._find_locked(task_id)
            if record is None:
                return
            record.status = TASK_STATUS_CANCELLED
            record.detail = str(detail or "任务已取消")
            record.updated_at = now
            record.finished_at = now
            self._save_locked(force=True)

    def snapshot(self, limit: int = 80) -> list[dict[str, Any]]:
        with self._lock:
            records = list(self._records[: max(1, int(limit or 80))])
            if self._dirty and time.monotonic() - self._last_save_at >= self._save_interval_seconds:
                self._save_locked(force=True)
        return [asdict(record) for record in records]

    def clear_completed(self) -> None:
        with self._lock:
            self._records = [record for record in self._records if record.status != TASK_STATUS_COMPLETED]
            self._save_locked(force=True)

    def clear_failed(self) -> None:
        with self._lock:
            self._records = [record for record in self._records if record.status != TASK_STATUS_FAILED]
            self._save_locked(force=True)

    def clear_cancelled(self) -> None:
        with self._lock:
            self._records = [record for record in self._records if record.status != TASK_STATUS_CANCELLED]
            self._save_locked(force=True)

    def clear_all(self) -> None:
        with self._lock:
            self._records = []
            self._save_locked(force=True)

    def _find_locked(self, task_id: str) -> TaskRecord | None:
        for record in self._records:
            if record.task_id == task_id:
                return record
        return None

    def _load(self) -> None:
        if self._load_from_sqlite():
            return
        if not self.storage_path or not os.path.isfile(self.storage_path):
            return
        try:
            with open(self.storage_path, "r", encoding="utf-8") as file:
                data = json.load(file)
            records = data.get("records", data) if isinstance(data, dict) else data
            loaded: list[TaskRecord] = []
            for raw in records if isinstance(records, list) else []:
                if not isinstance(raw, dict):
                    continue
                values = {field_name: raw.get(field_name) for field_name in TaskRecord.__dataclass_fields__}
                values["task_id"] = str(values.get("task_id") or uuid.uuid4().hex)
                values["title"] = str(values.get("title") or "未命名任务")
                values["retry_payload"] = values.get("retry_payload") if isinstance(values.get("retry_payload"), dict) else {}
                for key in ("total", "completed", "success_count", "failed_count"):
                    try:
                        values[key] = max(0, int(values.get(key) or 0))
                    except (TypeError, ValueError):
                        values[key] = 0
                loaded.append(TaskRecord(**values))
            self._records = loaded[: self.max_records]
            self._save_sqlite_locked()
        except Exception:
            self._records = []

    def _load_from_sqlite(self) -> bool:
        store = self.sqlite_store
        if store is None:
            return False
        try:
            if store.task_record_count() <= 0:
                return False
            records = store.load_task_records()
            loaded: list[TaskRecord] = []
            for raw in records:
                if not isinstance(raw, dict):
                    continue
                values = {field_name: raw.get(field_name) for field_name in TaskRecord.__dataclass_fields__}
                values["task_id"] = str(values.get("task_id") or uuid.uuid4().hex)
                values["title"] = str(values.get("title") or "未命名任务")
                values["retry_payload"] = values.get("retry_payload") if isinstance(values.get("retry_payload"), dict) else {}
                for key in ("total", "completed", "success_count", "failed_count"):
                    try:
                        values[key] = max(0, int(values.get(key) or 0))
                    except (TypeError, ValueError):
                        values[key] = 0
                loaded.append(TaskRecord(**values))
            self._records = loaded[: self.max_records]
            return True
        except Exception:
            return False

    def _save_locked(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last_save_at < self._save_interval_seconds:
            self._dirty = True
            return
        self._save_sqlite_locked()
        if not self.storage_path:
            self._last_save_at = now
            self._dirty = False
            return
        try:
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)
            tmp_path = self.storage_path + ".tmp"
            with open(tmp_path, "w", encoding="utf-8") as file:
                json.dump({"records": [asdict(record) for record in self._records[: self.max_records]]}, file, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self.storage_path)
            self._last_save_at = now
            self._dirty = False
        except Exception:
            pass

    def _save_sqlite_locked(self) -> None:
        store = self.sqlite_store
        if store is None:
            return
        try:
            store.save_task_records([asdict(record) for record in self._records[: self.max_records]], self.max_records)
        except Exception:
            pass
from ..errors import classify_failure as classify_failure_advice
