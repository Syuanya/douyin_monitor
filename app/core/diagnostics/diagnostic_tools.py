from __future__ import annotations

import json
import os
import platform
import re
import sys
import time
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...utils.logger import sanitize_log_text

SENSITIVE_KEYS = (
    "cookie",
    "token",
    "key",
    "secret",
    "password",
    "sign",
    "auth",
    "ticket",
    "session",
    "credential",
    "wssecret",
    "txsecret",
    "a_bogus",
    "msToken",
    "ttwid",
)
URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key or "").lower()
    return any(marker.lower() in lowered for marker in SENSITIVE_KEYS)


def sanitize_url(url: str | None, *, hide_query: bool = True) -> str:
    """Return a log-safe URL with credentials and risk-control params redacted."""

    text = str(url or "").strip()
    if not text:
        return ""
    try:
        parts = urlsplit(text)
        if not parts.scheme or not parts.netloc:
            return text[:180] + "..." if len(text) > 180 else text
        if hide_query:
            query = "***" if parts.query else ""
        else:
            query_pairs: list[tuple[str, str]] = []
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if _is_sensitive_key(key):
                    safe_value = "***"
                elif len(value) > 48:
                    safe_value = value[:12] + "***"
                else:
                    safe_value = value
                query_pairs.append((key, safe_value))
            query = urlencode(query_pairs, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except Exception:
        if "?" in text:
            return text.split("?", 1)[0] + "?***"
        return text[:180] + "..." if len(text) > 180 else text


def sanitize_text(text: Any, *, hide_url_query: bool = True, limit: int = 4000) -> str:
    """Redact cookies, tokens, URLs and local user paths from diagnostic text."""

    if text is None:
        return ""
    value = str(text)
    try:
        value = sanitize_log_text(value, hide_url_query=hide_url_query)
    except Exception:
        value = URL_RE.sub(lambda match: sanitize_url(match.group(0), hide_query=hide_url_query), value)
    for key in SENSITIVE_KEYS:
        value = re.sub(rf"({re.escape(key)}\s*[=:]\s*)([^\s,&;]+)", rf"\1***", value, flags=re.IGNORECASE)
    if limit > 0 and len(value) > limit:
        return value[:limit] + "...[truncated]"
    return value


def _safe_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, default=str)


def _redact_mapping(data: Any) -> Any:
    if isinstance(data, dict):
        result: dict[str, Any] = {}
        for key, value in data.items():
            if _is_sensitive_key(str(key)):
                result[str(key)] = "***" if value else ""
            else:
                result[str(key)] = _redact_mapping(value)
        return result
    if isinstance(data, list):
        return [_redact_mapping(item) for item in data]
    if isinstance(data, str):
        return sanitize_text(data, limit=2000)
    return data


def _read_tail(path: Path, max_bytes: int) -> str:
    try:
        if not path.is_file() or max_bytes <= 0:
            return ""
        size = path.stat().st_size
        with path.open("rb") as file:
            if size > max_bytes:
                file.seek(-max_bytes, os.SEEK_END)
            raw = file.read(max_bytes)
        return raw.decode("utf-8", errors="replace")
    except Exception as exc:
        return f"<failed to read log: {exc}>"


def _setting(services: Any, key: str, default: Any) -> Any:
    settings = getattr(services, "settings_config", None)
    user_config = getattr(settings, "user_config", {}) if settings is not None else {}
    default_config = getattr(settings, "default_config", {}) if settings is not None else {}
    return user_config.get(key, default_config.get(key, default))


def export_diagnostic_bundle(services: Any, *, output_dir: str | os.PathLike[str] | None = None) -> str:
    """Create a redacted diagnostic zip and return its absolute path.

    The bundle intentionally contains only sanitized configuration metadata,
    recent sanitized log tails and runtime facts. It does not include raw cookie
    files, databases, downloads or monitor data.
    """

    run_path = Path(str(getattr(services, "run_path", "."))).resolve()
    target_dir = Path(output_dir) if output_dir is not None else run_path / "diagnostics"
    target_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = target_dir / f"douyin_monitor_diagnostics_{stamp}.zip"

    try:
        recent_log_kb = int(_setting(services, "diagnostic_export_recent_log_kb", 512) or 512)
    except (TypeError, ValueError):
        recent_log_kb = 512
    recent_log_kb = max(64, min(recent_log_kb, 10240))
    max_log_bytes = recent_log_kb * 1024
    hide_url_query = bool(_setting(services, "diagnostic_redact_sensitive_urls", True))

    settings = getattr(services, "settings_config", None)
    manifest = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "run_path": sanitize_text(str(run_path), hide_url_query=hide_url_query),
        "python": sys.version,
        "executable": sanitize_text(sys.executable, hide_url_query=hide_url_query),
        "platform": platform.platform(),
        "pid": os.getpid(),
    }
    settings_snapshot = {
        "user_config": _redact_mapping(getattr(settings, "user_config", {}) if settings is not None else {}),
        "default_config_keys": sorted((getattr(settings, "default_config", {}) or {}).keys()) if settings is not None else [],
        "cookies_config_present": bool(getattr(settings, "cookies_config", {}) if settings is not None else {}),
        "accounts_config_present": bool(getattr(settings, "accounts_config", {}) if settings is not None else {}),
    }
    service_snapshot = {
        "sqlite_store": bool(getattr(services, "sqlite_store", None)),
        "video_parser": bool(getattr(services, "video_parser", None)),
        "media_task_queue": bool(getattr(services, "media_task_queue", None)),
        "douyin_content_monitor": bool(getattr(services, "douyin_content_monitor", None)),
    }

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", _safe_json(manifest))
        zf.writestr("settings_redacted.json", _safe_json(settings_snapshot))
        zf.writestr("services.json", _safe_json(service_snapshot))
        log_dir = run_path / "logs"
        if log_dir.is_dir():
            for log_file in sorted(log_dir.glob("*.log")):
                tail = _read_tail(log_file, max_log_bytes)
                zf.writestr(f"logs/{log_file.name}", sanitize_text(tail, hide_url_query=hide_url_query, limit=max_log_bytes))
        else:
            zf.writestr("logs/README.txt", "No logs directory found.\n")
        zf.writestr("export_completed_at.txt", datetime.now().isoformat(timespec="seconds") + "\n")
    try:
        os.utime(zip_path, (time.time(), time.time()))
    except OSError:
        pass
    return str(zip_path)
