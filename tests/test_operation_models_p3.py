from __future__ import annotations

from pathlib import Path

from app.core.runtime.operation_models import (
    OperationStatus,
    download_status_label,
    inspect_file_state,
    is_download_recoverable,
    normalize_download_status,
    normalize_task_status,
    task_status_key,
)
from app.core.runtime.task_center import TASK_STATUS_RUNNING, TaskCenter


def test_task_status_accepts_legacy_label_and_canonical_key(tmp_path: Path) -> None:
    center = TaskCenter(sqlite_store=None, storage_path=str(tmp_path / "tasks.json"))
    task_id = center.start("demo")
    center.progress(task_id, status=OperationStatus.PENDING.value, detail="waiting")
    snapshot = center.snapshot()

    assert snapshot[0]["status"] == "等待中"
    assert snapshot[0]["status_key"] == OperationStatus.WAITING.value
    assert normalize_task_status(TASK_STATUS_RUNNING) == "运行中"
    assert task_status_key("failed") == OperationStatus.FAILED.value


def test_download_status_and_file_state_are_canonical(tmp_path: Path) -> None:
    final_path = tmp_path / "video.mp4"
    part_path = tmp_path / "video.mp4.part"
    part_path.write_bytes(b"partial")
    record = {"status": "失败", "save_path": str(final_path), "url": "https://example.test/video.mp4"}

    assert normalize_download_status("失败") == OperationStatus.FAILED.value
    assert download_status_label("completed") == "完成"
    state = inspect_file_state(record)
    assert state.key == "partial"
    assert state.recoverable_hint is True
    assert is_download_recoverable(record) is True

    part_path.unlink()
    final_path.write_bytes(b"complete")
    assert inspect_file_state(record).key == "exists"
    assert is_download_recoverable(record) is False
