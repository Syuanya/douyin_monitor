from __future__ import annotations

import os
from pathlib import Path
from typing import Any


def app_services(app: Any) -> Any:
    return getattr(app, "services", None)


def format_bytes(value: int) -> str:
    size = float(max(0, int(value or 0)))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}" if unit != "B" else f"{int(size)} B"
        size /= 1024
    return f"{size:.1f} TB"


def default_douyin_download_path(app: Any) -> str:
    run_path = str(getattr(app, "run_path", "") or getattr(app_services(app), "run_path", "") or ".")
    return os.path.join(run_path, "downloads", "douyin_content")


def storage_writable(path: str) -> bool:
    try:
        target = Path(path)
        target.mkdir(parents=True, exist_ok=True)
        return target.exists() and os.access(target, os.W_OK)
    except Exception:
        return False
