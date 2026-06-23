from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def safe_dict(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    if hasattr(value, "to_dict"):
        try:
            data = value.to_dict()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}
    if is_dataclass(value):
        try:
            return asdict(value)
        except Exception:
            return {}
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key, None))
    }


def account_to_dict(account: Any, *, include_items: bool = False) -> dict[str, Any]:
    data = safe_dict(account)
    items = list(data.get("items") or [])
    new_count = len([item for item in items if str(item.get("status") or "") in {"new", "count_only"}])
    data["new_unhandled_count"] = new_count
    data["item_count"] = len(items)
    if not include_items:
        data.pop("items", None)
        data.pop("monitor_history", None)
        data.pop("known_item_ids", None)
    return data


def item_to_dict(item: Any) -> dict[str, Any]:
    return safe_dict(item)


def parse_event_to_dict(event: Any) -> dict[str, Any]:
    data = safe_dict(event)
    if event.__class__.__name__ == "ParsedVideoResult":
        data["event"] = "success"
    elif event.__class__.__name__ == "ParseFailure":
        data["event"] = "failure"
    elif event.__class__.__name__ == "ParseProgress":
        data["event"] = "progress"
    elif event.__class__.__name__ == "ParseDownloadEvent":
        data["event"] = "download"
    else:
        data.setdefault("event", event.__class__.__name__)
    return data
