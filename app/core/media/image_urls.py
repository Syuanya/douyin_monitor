from __future__ import annotations

from pathlib import PurePosixPath
from urllib.parse import unquote, urlsplit

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}


def image_identity_key(url: str) -> str:
    parts = urlsplit(str(url or ""))
    path = unquote(parts.path or "").lower()
    if "~" in path:
        path = path.split("~", 1)[0]
    suffix = PurePosixPath(path).suffix
    if suffix in IMAGE_SUFFIXES:
        path = path[: -len(suffix)]
    if path:
        return path
    return str(url or "").strip()


def deduplicate_image_urls(urls: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        text = str(url or "").strip()
        if not text:
            continue
        key = image_identity_key(text)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(text)
    return deduped


def infer_image_suffix(url: str, fallback: str = ".jpg") -> str:
    """Infer a safe image file suffix from a URL path.

    The URL may contain query strings or percent-encoded paths. If the platform
    returns an extensionless image endpoint, fall back to JPEG so users can open
    the saved file directly in common viewers.
    """
    parts = urlsplit(str(url or ""))
    path = unquote(parts.path or "").lower()
    suffix = PurePosixPath(path).suffix
    if suffix in IMAGE_SUFFIXES:
        return suffix
    fallback = str(fallback or ".jpg").strip().lower()
    if not fallback.startswith("."):
        fallback = f".{fallback}"
    return fallback if fallback in IMAGE_SUFFIXES else ".jpg"
