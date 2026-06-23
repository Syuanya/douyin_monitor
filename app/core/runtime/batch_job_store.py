from __future__ import annotations

import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(slots=True)
class BatchJobRecord:
    job_id: str
    batch_key: str
    title: str
    status: str = "running"
    total: int = 0
    completed_ids: list[str] = field(default_factory=list)
    failed_ids: list[str] = field(default_factory=list)
    skipped_ids: list[str] = field(default_factory=list)
    failure_reasons: dict[str, str] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BatchJobRecord":
        now = time.time()
        return cls(
            job_id=str(data.get("job_id") or uuid.uuid4().hex),
            batch_key=str(data.get("batch_key") or ""),
            title=str(data.get("title") or "批量任务"),
            status=str(data.get("status") or "running"),
            total=max(0, int(data.get("total") or 0)),
            completed_ids=[str(item) for item in data.get("completed_ids", []) if str(item or "")],
            failed_ids=[str(item) for item in data.get("failed_ids", []) if str(item or "")],
            skipped_ids=[str(item) for item in data.get("skipped_ids", []) if str(item or "")],
            failure_reasons={str(key): str(value)[:500] for key, value in (data.get("failure_reasons") or {}).items()} if isinstance(data.get("failure_reasons"), dict) else {},
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
            created_at=float(data.get("created_at") or now),
            updated_at=float(data.get("updated_at") or now),
        )

    def item_ids(self) -> list[str]:
        values = self.payload.get("item_ids") if isinstance(self.payload, dict) else []
        return [str(item) for item in values or [] if str(item or "")]

    def remaining_item_ids(self) -> list[str]:
        completed = set(self.completed_ids) | set(self.skipped_ids)
        return [item for item in self.item_ids() if item not in completed]


class BatchJobStore:
    """Small durable store for resumable batch jobs."""

    def __init__(self, run_path: str, relative_path: str = "config/batch_jobs.json", max_records: int = 200):
        self.path = os.path.join(str(run_path or "."), relative_path)
        self.max_records = max(20, int(max_records or 200))
        self._lock = threading.RLock()
        self._jobs: dict[str, BatchJobRecord] = {}
        self.load()

    def load(self) -> None:
        if not os.path.isfile(self.path):
            return
        try:
            with open(self.path, "r", encoding="utf-8") as file:
                data = json.load(file)
            records = data.get("jobs", []) if isinstance(data, dict) else []
            jobs: dict[str, BatchJobRecord] = {}
            for raw in records:
                if isinstance(raw, dict):
                    job = BatchJobRecord.from_dict(raw)
                    jobs[job.job_id] = job
            with self._lock:
                self._jobs = jobs
        except Exception:
            return

    def save(self) -> None:
        with self._lock:
            records = sorted(self._jobs.values(), key=lambda job: job.updated_at, reverse=True)[: self.max_records]
            data = {"version": 1, "jobs": [job.to_dict() for job in records]}
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as file:
                json.dump(data, file, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def start_or_resume(
        self,
        batch_key: str,
        title: str = "批量任务",
        total: int = 0,
        payload: dict[str, Any] | None = None,
        item_ids: list[str] | tuple[str, ...] | None = None,
    ) -> BatchJobRecord:
        now = time.time()
        merged_payload = dict(payload or {})
        if item_ids is not None:
            merged_payload["item_ids"] = [str(item) for item in item_ids if str(item or "")]
        with self._lock:
            existing = next((job for job in self._jobs.values() if job.batch_key == batch_key and job.status in {"running", "paused", "failed"}), None)
            if existing is not None:
                existing.status = "running"
                existing.title = title or existing.title
                existing.total = max(existing.total, int(total or 0))
                existing.payload = dict(merged_payload or existing.payload or {})
                existing.updated_at = now
                job = existing
            else:
                job = BatchJobRecord(
                    job_id=uuid.uuid4().hex,
                    batch_key=str(batch_key or uuid.uuid4().hex),
                    title=str(title or "批量任务"),
                    total=max(0, int(total or 0)),
                    payload=dict(merged_payload or {}),
                    created_at=now,
                    updated_at=now,
                )
                self._jobs[job.job_id] = job
        self.save()
        return job

    def mark_item(self, job_id: str, item_id: str, status: str, reason: str = "") -> BatchJobRecord | None:
        text = str(item_id or "")
        if not text:
            return self.get(job_id)
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return None
            for bucket in (job.completed_ids, job.failed_ids, job.skipped_ids):
                while text in bucket:
                    bucket.remove(text)
            job.failure_reasons.pop(text, None)
            if status == "completed":
                job.completed_ids.append(text)
            elif status == "skipped":
                job.skipped_ids.append(text)
            else:
                job.failed_ids.append(text)
                if reason:
                    job.failure_reasons[text] = str(reason)[:500]
            job.updated_at = time.time()
        self.save()
        return job

    def finish(self, job_id: str, success: bool) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            job.status = "completed" if success else "failed"
            job.updated_at = time.time()
        self.save()

    def pause(self, job_id: str) -> None:
        self.set_status(job_id, "paused")

    def resume(self, job_id: str) -> None:
        self.set_status(job_id, "running")

    def cancel(self, job_id: str, reason: str = "") -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = "cancelled"
                if reason:
                    job.failure_reasons["__cancelled__"] = str(reason)[:500]
                job.updated_at = time.time()
        self.save()

    def set_status(self, job_id: str, status: str) -> None:
        value = str(status or "").strip().lower()
        if value not in {"running", "paused", "failed", "completed", "cancelled"}:
            value = "running"
        with self._lock:
            job = self._jobs.get(job_id)
            if job is not None:
                job.status = value
                job.updated_at = time.time()
        self.save()

    def is_paused(self, job_id: str) -> bool:
        job = self.get(job_id)
        return bool(job and job.status == "paused")

    def is_cancelled(self, job_id: str) -> bool:
        job = self.get(job_id)
        return bool(job and job.status == "cancelled")

    def snapshot(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock:
            jobs = sorted(self._jobs.values(), key=lambda job: job.updated_at, reverse=True)[: max(1, int(limit or 100))]
            return [self._summarize(job) for job in jobs]

    def detail(self, job_id: str) -> dict[str, Any]:
        job = self.get(job_id)
        return self._summarize(job, include_items=True) if job is not None else {}

    @staticmethod
    def _summarize(job: BatchJobRecord, *, include_items: bool = False) -> dict[str, Any]:
        completed = len(job.completed_ids)
        failed = len(job.failed_ids)
        skipped = len(job.skipped_ids)
        done = completed + failed + skipped
        remaining = max(0, int(job.total or len(job.item_ids())) - done)
        data = {
            "job_id": job.job_id,
            "batch_key": job.batch_key,
            "title": job.title,
            "status": job.status,
            "total": int(job.total or len(job.item_ids())),
            "completed": completed,
            "failed": failed,
            "skipped": skipped,
            "remaining": remaining,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
            "payload": dict(job.payload or {}),
            "failure_reasons": dict(job.failure_reasons or {}),
        }
        if include_items:
            data.update({
                "completed_ids": list(job.completed_ids),
                "failed_ids": list(job.failed_ids),
                "skipped_ids": list(job.skipped_ids),
                "remaining_ids": job.remaining_item_ids(),
                "item_ids": job.item_ids(),
            })
        return data

    def get(self, job_id: str) -> BatchJobRecord | None:
        with self._lock:
            return self._jobs.get(job_id)

    def pending_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return [self._summarize(job, include_items=True) for job in self._jobs.values() if job.status in {"running", "paused", "failed"}]
