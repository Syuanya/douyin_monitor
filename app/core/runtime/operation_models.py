from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum
from typing import Any


class OperationStatus(str, Enum):
    """Canonical runtime status values used by task/download projections.

    UI code may still display Chinese labels, but service boundaries should use
    these stable values when accepting parameters, serialising API payloads, or
    composing retry/cancel decisions.
    """

    PENDING = "pending"
    WAITING = "waiting"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RECOVERABLE = "recoverable"
    PARTIAL_SUCCESS = "partial_success"
    RETRYING = "retrying"


TASK_STATUS_LABELS: dict[str, str] = {
    OperationStatus.PENDING.value: "等待中",
    OperationStatus.WAITING.value: "等待中",
    OperationStatus.RUNNING.value: "运行中",
    OperationStatus.PAUSED.value: "已暂停",
    OperationStatus.COMPLETED.value: "完成",
    OperationStatus.FAILED.value: "失败",
    OperationStatus.CANCELLED.value: "已取消",
    OperationStatus.RECOVERABLE.value: "可恢复",
    OperationStatus.PARTIAL_SUCCESS.value: "部分成功",
    OperationStatus.RETRYING.value: "重试中",
}

TASK_LABEL_TO_STATUS: dict[str, str] = {label: status for status, label in TASK_STATUS_LABELS.items()}
# Historical aliases used before the operation status model existed.
TASK_LABEL_TO_STATUS.update({"等待中": OperationStatus.WAITING.value, "运行中": OperationStatus.RUNNING.value, "完成": OperationStatus.COMPLETED.value, "失败": OperationStatus.FAILED.value, "已取消": OperationStatus.CANCELLED.value})

DOWNLOAD_STATUS_LABELS: dict[str, str] = {
    OperationStatus.PENDING.value: "等待中",
    OperationStatus.RUNNING.value: "运行中",
    OperationStatus.COMPLETED.value: "完成",
    OperationStatus.FAILED.value: "失败",
    OperationStatus.CANCELLED.value: "已取消",
    OperationStatus.RECOVERABLE.value: "可恢复",
    OperationStatus.RETRYING.value: "重试中",
}

ACTIVE_TASK_STATUS_KEYS = {OperationStatus.PENDING.value, OperationStatus.WAITING.value, OperationStatus.RUNNING.value, OperationStatus.PAUSED.value, OperationStatus.RETRYING.value}
TERMINAL_TASK_STATUS_KEYS = {OperationStatus.COMPLETED.value, OperationStatus.FAILED.value, OperationStatus.CANCELLED.value, OperationStatus.PARTIAL_SUCCESS.value}
RECOVERABLE_DOWNLOAD_STATUS_KEYS = {OperationStatus.PENDING.value, OperationStatus.RUNNING.value, OperationStatus.RECOVERABLE.value, OperationStatus.FAILED.value, OperationStatus.CANCELLED.value}


@dataclass(frozen=True, slots=True)
class FileState:
    key: str
    label: str
    exists: bool = False
    recoverable_hint: bool = False
    missing_completed: bool = False
    part_path: str = ""
    size_bytes: int = 0
    part_size_bytes: int = 0


def task_status_key(status: Any) -> str:
    text = str(status or "").strip()
    if not text:
        return OperationStatus.WAITING.value
    lower = text.lower()
    if lower in TASK_STATUS_LABELS:
        return lower
    return TASK_LABEL_TO_STATUS.get(text, lower)


def task_status_label(status: Any) -> str:
    key = task_status_key(status)
    return TASK_STATUS_LABELS.get(key, str(status or ""))


def normalize_task_status(status: Any) -> str:
    """Return the user-facing task status label used by legacy desktop UI."""

    return task_status_label(status)


def is_active_task_status(status: Any) -> bool:
    return task_status_key(status) in ACTIVE_TASK_STATUS_KEYS


def is_terminal_task_status(status: Any) -> bool:
    return task_status_key(status) in TERMINAL_TASK_STATUS_KEYS


def download_status_key(status: Any) -> str:
    text = str(status or "").strip()
    if not text:
        return OperationStatus.PENDING.value
    lower = text.lower()
    if lower in DOWNLOAD_STATUS_LABELS:
        return lower
    # Accept accidental Chinese statuses at service/API boundaries.
    for key, label in DOWNLOAD_STATUS_LABELS.items():
        if text == label:
            return key
    return lower


def download_status_label(status: Any) -> str:
    key = download_status_key(status)
    return DOWNLOAD_STATUS_LABELS.get(key, str(status or ""))


def normalize_download_status(status: Any) -> str:
    """Return the canonical download status key persisted in SQLite."""

    return download_status_key(status)


def file_size(path: str) -> int:
    try:
        return os.path.getsize(path) if path and os.path.isfile(path) else 0
    except OSError:
        return 0


def inspect_file_state(record: dict[str, Any]) -> FileState:
    save_path = str(record.get("save_path") or "")
    status = download_status_key(record.get("status"))
    if not save_path:
        return FileState(key="no_path", label="无保存路径")
    size = file_size(save_path)
    if size > 0:
        return FileState(key="exists", label="文件存在", exists=True, size_bytes=size)
    part_path = save_path + ".part"
    part_size = file_size(part_path)
    if part_size > 0:
        return FileState(key="partial", label="存在临时文件，可恢复", recoverable_hint=True, part_path=part_path, part_size_bytes=part_size)
    if status == OperationStatus.COMPLETED.value:
        return FileState(key="missing_completed", label="完成记录但文件缺失", missing_completed=True)
    return FileState(key="missing", label="文件不存在")


def is_download_recoverable(record: dict[str, Any]) -> bool:
    """Conservative recoverability check used by UI and recovery service.

    A completed final file is never recoverable. A .part file is recoverable.
    Records without .part but with a URL are treated as re-downloadable, which
    keeps the user action available for failed/cancelled URL downloads.
    """

    state = inspect_file_state(record)
    if state.exists:
        return False
    if state.recoverable_hint:
        return True
    return bool(record.get("url"))
