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


def parse_cookie_pool(raw_cookie_text: str | list[str] | tuple[str, ...]) -> list[str]:
    """Parse one or more Cookie header strings.

    Input is intentionally conservative: a single Cookie may contain many
    semicolon-separated key/value pairs, while multiple Cookies should be pasted
    one per line or separated by blank lines.  Invalid/duplicate entries are
    dropped, preserving order.
    """

    raw_items: list[str]
    if isinstance(raw_cookie_text, (list, tuple)):
        raw_items = [str(item or "") for item in raw_cookie_text]
    else:
        text = str(raw_cookie_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        if not text:
            raw_items = []
        else:
            blocks = [block.strip() for block in re_split_blank_lines(text) if block.strip()]
            if len(blocks) > 1:
                raw_items = blocks
            else:
                lines = [line.strip() for line in text.split("\n") if line.strip()]
                raw_items = lines if len(lines) > 1 else [text]

    cookies: list[str] = []
    seen: set[str] = set()
    for raw in raw_items:
        cookie = sanitize_cookie_header(raw)
        if not cookie or cookie in seen:
            continue
        seen.add(cookie)
        cookies.append(cookie)
    return cookies


def re_split_blank_lines(text: str) -> list[str]:
    blocks: list[str] = []
    current: list[str] = []
    for line in str(text or "").split("\n"):
        if line.strip():
            current.append(line)
            continue
        if current:
            blocks.append("\n".join(current))
            current = []
    if current:
        blocks.append("\n".join(current))
    return blocks


def cookie_looks_usable(cookie: str) -> bool:
    sanitized = sanitize_cookie_header(cookie)
    return bool(sanitized and "=" in sanitized and len(sanitized) >= 20)
