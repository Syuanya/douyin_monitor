import json
import platform
import re
import shutil
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ...utils.logger import logger


SENSITIVE_KEYS = (
    "cookie",
    "token",
    "key",
    "secret",
    "password",
    "sign",
    "auth",
    "webhook",
    "sendkey",
    "ticket",
    "session",
    "credential",
    "wssecret",
    "txsecret",
    "fm",
    "seqid",
)
URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)
WINDOWS_USER_PATH_RE = re.compile(r"([A-Za-z]:\\\\Users\\\\)([^\\\\\s]+)", re.IGNORECASE)
POSIX_HOME_RE = re.compile(r"(/home/)([^/\s]+)")


def _is_sensitive_key(key: str) -> bool:
    key_l = str(key).lower()
    return any(k in key_l for k in SENSITIVE_KEYS)


def _mask_value(key: str, value: Any) -> Any:
    if _is_sensitive_key(key):
        if value in (None, "", False):
            return value
        return "***masked***"
    if isinstance(value, dict):
        return {k: _mask_value(k, v) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask_value(key, v) for v in value]
    if isinstance(value, str):
        return sanitize_text(value)
    return value


def sanitize_url(url: str | None, *, hide_query: bool = False) -> str:
    if not url:
        return ""
    text = str(url).strip()
    try:
        parts = urlsplit(text)
        if not parts.scheme or not parts.netloc:
            return text
        if hide_query:
            query = "***" if parts.query else ""
        else:
            query_pairs = []
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if _is_sensitive_key(key):
                    query_pairs.append((key, "***"))
                else:
                    query_pairs.append((key, value if len(value) <= 64 else value[:12] + "***"))
            query = urlencode(query_pairs, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except Exception:
        if "?" not in text:
            return text
        base, _query = text.split("?", 1)
        return base + "?***"


def sanitize_text(text: str | None, *, hide_url_query: bool = True) -> str:
    if not text:
        return ""
    redacted = str(text)
    redacted = URL_RE.sub(lambda m: sanitize_url(m.group(0), hide_query=hide_url_query), redacted)
    redacted = WINDOWS_USER_PATH_RE.sub(r"\1***", redacted)
    redacted = POSIX_HOME_RE.sub(r"\1***", redacted)
    for key in SENSITIVE_KEYS:
        redacted = re.sub(
            rf"({re.escape(key)}\s*[=:]\s*)([^\s,&;]+)",
            rf"\1***",
            redacted,
            flags=re.IGNORECASE,
        )
    return redacted


def read_recent_error_text(services, max_lines: int = 80) -> str:
    log_dir = Path(services.run_path) / "logs"
    candidates = [log_dir / "streamget.log", log_dir / "play_url.log", log_dir / "operations.log", log_dir / "douyin_monitor.log"]
    lines: list[str] = []
    for path in candidates:
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line in text.splitlines():
            lower = line.lower()
            if any(token in lower for token in ("error", "warning", "failed", "forbidden", "timeout", "exception")):
                lines.append(f"{path.name}: {sanitize_text(line)}")
    return "\n".join(lines[-max_lines:])


def _copy_recent_file(src: Path, dst: Path, max_kb: int = 512) -> None:
    if not src.exists() or not src.is_file():
        return
    max_bytes = max(1, int(max_kb)) * 1024
    data = src.read_bytes()
    if len(data) > max_bytes:
        data = data[-max_bytes:]
    dst.write_text(sanitize_text(data.decode("utf-8", errors="replace")), encoding="utf-8")


def export_diagnostic_bundle(services, recent_log_kb: int = 512) -> str:
    run_path = Path(services.run_path)
    out_dir = run_path / "diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = out_dir / f"douyin_monitor_diagnostic_{stamp}.zip"
    temp_dir = out_dir / f".diag_{stamp}"
    temp_dir.mkdir(parents=True, exist_ok=True)

    try:
        summary: dict[str, Any] = {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "python": sys.version,
            "platform": platform.platform(),
            "executable": sanitize_text(sys.executable),
            "run_path": sanitize_text(str(run_path)),
            "redaction": "URLs, tokens, signed query strings and local usernames are masked.",
        }
        mq = getattr(services, "media_task_queue", None)
        if mq is not None:
            summary["media_task_queue"] = mq.snapshot()
        dm = getattr(services, "douyin_content_monitor", None)
        if dm is not None:
            try:
                summary["douyin_content_monitor"] = dm.snapshot()
            except Exception:
                pass
        recent_errors = read_recent_error_text(services, max_lines=120)
        if recent_errors:
            summary["recent_errors_excerpt"] = recent_errors
        (temp_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=4), encoding="utf-8")

        cm = getattr(services, "config_manager", None)
        if cm is not None:
            config_files = {
                "default_settings.json": cm.default_config_path,
                "user_settings.sanitized.json": cm.user_config_path,
                "accounts.sanitized.json": cm.accounts_config_path,
                "cookies.sanitized.json": cm.cookies_config_path,
            }
            dm = getattr(services, "douyin_content_monitor", None)
            if dm is not None:
                config_files["douyin_content_monitor.sanitized.json"] = getattr(dm, "config_path", "")
            config_dir = temp_dir / "config"
            config_dir.mkdir(exist_ok=True)
            for name, path in config_files.items():
                try:
                    data = json.load(open(path, encoding="utf-8"))
                    if "sanitized" in name:
                        data = _mask_value(name, data)
                    (config_dir / name).write_text(json.dumps(data, ensure_ascii=False, indent=4), encoding="utf-8")
                except Exception as exc:
                    (config_dir / f"{name}.error.txt").write_text(sanitize_text(str(exc)), encoding="utf-8")

        logs_dir = run_path / "logs"
        out_logs = temp_dir / "logs"
        out_logs.mkdir(exist_ok=True)
        for log_name in ("streamget.log", "play_url.log", "operations.log", "douyin_monitor.log"):
            _copy_recent_file(logs_dir / log_name, out_logs / log_name, max_kb=recent_log_kb)

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file in temp_dir.rglob("*"):
                if file.is_file():
                    zf.write(file, arcname=str(file.relative_to(temp_dir)))
        logger.info(f"Exported diagnostic bundle: {zip_path}")
        return str(zip_path)
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
