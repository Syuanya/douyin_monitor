import os
import re
import sys
import tempfile
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from loguru import logger

script_path = os.path.split(os.path.realpath(sys.argv[0]))[0]
log_dir = os.environ.get("DOUYIN_MONITOR_LOG_DIR") or os.path.join(script_path, "logs")
console_level = os.environ.get("DOUYIN_MONITOR_CONSOLE_LEVEL", "INFO").upper()
try:
    message_limit = int(os.environ.get("DOUYIN_MONITOR_LOG_MESSAGE_LIMIT", "2000") or 2000)
except (TypeError, ValueError):
    message_limit = 2000
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
WINDOWS_USER_PATH_RE = re.compile(r"([A-Za-z]:\\\\Users\\\\)([^\\\\\s]+)", re.IGNORECASE)
POSIX_HOME_RE = re.compile(r"(/home/)([^/\s]+)")


def _ensure_log_dir(path: str) -> str:
    try:
        os.makedirs(path, exist_ok=True)
        test_path = os.path.join(path, ".write_test")
        with open(test_path, "w", encoding="utf-8") as f:
            f.write("ok")
        try:
            os.remove(test_path)
        except OSError:
            pass
        return path
    except Exception:
        fallback = os.path.join(tempfile.gettempdir(), "douyin_monitor_logs")
        os.makedirs(fallback, exist_ok=True)
        return fallback


log_dir = _ensure_log_dir(log_dir)


def _is_sensitive_key(key: str) -> bool:
    key_l = str(key or "").lower()
    return any(item.lower() in key_l for item in SENSITIVE_KEYS)


def _sanitize_url(url: str, *, hide_query: bool = False) -> str:
    text = str(url or "").strip()
    if not text:
        return ""
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
                    query_pairs.append((key, value if len(value) <= 48 else value[:12] + "***"))
            query = urlencode(query_pairs, doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except Exception:
        if "?" in text:
            return text.split("?", 1)[0] + "?***"
        return text[:180] + "..." if len(text) > 180 else text


def sanitize_log_text(text: str | None, *, hide_url_query: bool = True) -> str:
    if not text:
        return ""
    redacted = str(text)
    redacted = URL_RE.sub(lambda match: _sanitize_url(match.group(0), hide_query=hide_url_query), redacted)
    redacted = WINDOWS_USER_PATH_RE.sub(r"\1***", redacted)
    redacted = POSIX_HOME_RE.sub(r"\1***", redacted)
    for key in SENSITIVE_KEYS:
        redacted = re.sub(
            rf"({re.escape(key)}\s*[=:]\s*)([^\s,&;]+)",
            rf"\1***",
            redacted,
            flags=re.IGNORECASE,
        )
    if message_limit > 0 and len(redacted) > message_limit:
        redacted = redacted[:message_limit] + "...[truncated]"
    return redacted


def _sanitize_record(record) -> bool:
    try:
        record["message"] = sanitize_log_text(record.get("message", ""))
    except Exception:
        pass
    return True


def _cleanup_legacy_timestamp_logs(path: str) -> None:
    pattern = re.compile(r"^\d{4}-\d{2}-\d{2}-\d{2}-\d{2}-\d{2}\.log$")
    try:
        for name in os.listdir(path):
            if pattern.match(name):
                try:
                    os.remove(os.path.join(path, name))
                except OSError:
                    pass
    except OSError:
        pass


_cleanup_legacy_timestamp_logs(log_dir)

logger.remove()

try:
    logger.add(
        sys.stderr,
        level=console_level,
        format="<green>{time:HH:mm:ss}</green> | <level>{level: <7}</level> | {message}",
        filter=_sanitize_record,
        colorize=True,
        enqueue=True,
    )
except Exception:
    pass

try:
    logger.add(
        os.path.join(log_dir, "streamget.log"),
        level="DEBUG",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        filter=lambda i: _sanitize_record(i) and i["level"].name != "STREAM",
        serialize=False,
        enqueue=True,
        retention=3,
        rotation="3 MB",
        encoding="utf-8",
    )
except Exception as exc:
    logger.warning(f"File logger disabled: {exc}; log_dir={log_dir}")

logger.level("STREAM", no=22, color="<blue>")
try:
    logger.add(
        os.path.join(log_dir, "play_url.log"),
        level="STREAM",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {message}",
        filter=lambda i: _sanitize_record(i) and i["level"].name == "STREAM",
        serialize=False,
        enqueue=True,
        retention=1,
        rotation="500 KB",
        encoding="utf-8",
    )
except Exception as exc:
    logger.warning(f"Play URL logger disabled: {exc}; log_dir={log_dir}")

try:
    logger.add(
        os.path.join(log_dir, "operations.log"),
        level="INFO",
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {message}",
        filter=lambda i: _sanitize_record(i) and bool(i["extra"].get("douyin_monitor_event")),
        serialize=False,
        enqueue=True,
        retention=5,
        rotation="1 MB",
        encoding="utf-8",
    )
except Exception as exc:
    logger.warning(f"Operations logger disabled: {exc}; log_dir={log_dir}")
