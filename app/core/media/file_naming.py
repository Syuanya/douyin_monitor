from __future__ import annotations

import re
from datetime import datetime
from typing import Any

DEFAULT_FILENAME_TEMPLATE = "{item_id}_{title}"
INVALID_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n]+')


def safe_filename(value: Any, fallback: str = "untitled", limit: int = 120) -> str:
    text = str(value or "").strip()
    text = INVALID_FILENAME_CHARS.sub("_", text).strip(" .")
    return (text or fallback)[:limit]


def format_media_filename(template: str | None, context: dict[str, Any], *, fallback: str = "media") -> str:
    pattern = (template or DEFAULT_FILENAME_TEMPLATE).strip() or DEFAULT_FILENAME_TEMPLATE
    values = {
        "platform": context.get("platform") or "douyin",
        "author": context.get("author") or "",
        "item_id": context.get("item_id") or "",
        "title": context.get("title") or "",
        "date": context.get("date") or datetime.now().strftime("%Y%m%d"),
    }
    try:
        rendered = pattern.format(**values)
    except Exception:
        rendered = DEFAULT_FILENAME_TEMPLATE.format(**values)
    return safe_filename(rendered, fallback=fallback)
