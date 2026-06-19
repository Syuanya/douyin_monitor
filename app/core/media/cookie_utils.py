from __future__ import annotations


def sanitize_cookie_header(cookie: str) -> str:
    """Return a valid Cookie header string and drop malformed fragments."""
    parts: list[str] = []
    seen: set[str] = set()
    for raw_part in str(cookie or "").replace("\r", ";").replace("\n", ";").split(";"):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip()
        if not key or key.lower() in seen:
            continue
        seen.add(key.lower())
        parts.append(f"{key}={value.strip()}")
    return "; ".join(parts)


def cookie_looks_usable(cookie: str) -> bool:
    sanitized = sanitize_cookie_header(cookie)
    return bool(sanitized and "=" in sanitized and len(sanitized) >= 20)
