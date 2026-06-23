from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

DOUYIN_URL_RE = re.compile(r"https?://[^\s,，\t]+", re.IGNORECASE)
DOUYIN_HOST_RE = re.compile(r"(^|\.)(douyin\.com|iesdouyin\.com|snssdk\.com)$", re.IGNORECASE)
SEC_UID_RE = re.compile(r"/user/([^/?#]+)", re.IGNORECASE)


@dataclass(slots=True)
class BatchImportRow:
    line_no: int
    url: str
    normalized_url: str
    sec_uid: str
    name: str = ""
    group: str = ""
    action: str = "add"  # add | update | duplicate | invalid
    reason: str = ""
    source: str = "text"

    def to_dict(self) -> dict[str, Any]:
        return {
            "line_no": self.line_no,
            "url": self.url,
            "normalized_url": self.normalized_url,
            "sec_uid": self.sec_uid,
            "name": self.name,
            "group": self.group,
            "action": self.action,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass(slots=True)
class BatchImportPreview:
    rows: list[BatchImportRow] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def valid_rows(self) -> list[BatchImportRow]:
        return [row for row in self.rows if row.action in {"add", "update"}]

    @property
    def duplicate_rows(self) -> list[BatchImportRow]:
        return [row for row in self.rows if row.action == "duplicate"]

    @property
    def invalid_count(self) -> int:
        return len(self.errors) + len([row for row in self.rows if row.action == "invalid"])

    def counts(self) -> dict[str, int]:
        counts = {"total": len(self.rows) + len(self.errors), "valid": 0, "add": 0, "update": 0, "duplicate": 0, "invalid": self.invalid_count}
        for row in self.rows:
            if row.action in counts:
                counts[row.action] += 1
            if row.action in {"add", "update"}:
                counts["valid"] += 1
        return counts

    def summary_text(self) -> str:
        counts = self.counts()
        return (
            f"识别 {counts['total']} 行：可导入 {counts['valid']}，新增 {counts['add']}，"
            f"更新 {counts['update']}，重复 {counts['duplicate']}，无效 {counts['invalid']}"
        )


def normalize_douyin_homepage_url(raw_url: str) -> tuple[str, str]:
    text = str(raw_url or "").strip().rstrip("。；;，,)\"")
    if not text:
        raise ValueError("缺少主页链接")
    if not re.match(r"^https?://", text, re.IGNORECASE):
        text = "https://" + text
    parts = urlsplit(text)
    host = (parts.netloc or "").lower()
    if not host or not DOUYIN_HOST_RE.search(host):
        raise ValueError("不是抖音主页链接")
    path = parts.path.rstrip("/") or "/"
    if "/user/" not in path:
        raise ValueError("不是抖音用户主页链接")
    normalized = urlunsplit((parts.scheme or "https", parts.netloc, path, "", ""))
    sec_match = SEC_UID_RE.search(path)
    sec_uid = sec_match.group(1) if sec_match else ""
    return normalized, sec_uid


def _split_line(line: str) -> tuple[str, list[str]]:
    url_match = DOUYIN_URL_RE.search(line)
    if not url_match:
        return "", []
    url = url_match.group(0).strip()
    rest = (line[: url_match.start()] + " " + line[url_match.end() :]).strip(" ,，\t")
    rest = rest.replace("，", ",")
    parts: list[str] = []
    if rest:
        try:
            reader = csv.reader(io.StringIO(rest))
            parts = [str(part or "").strip() for part in next(reader, []) if str(part or "").strip()]
        except Exception:
            parts = [part.strip() for part in re.split(r"[,\t]", rest) if part.strip()]
    return url, parts


def parse_batch_import_text(
    text: str,
    *,
    default_group: str = "",
    existing_accounts: list[Any] | None = None,
    source: str = "text",
) -> BatchImportPreview:
    preview = BatchImportPreview()
    existing_by_key: set[str] = set()
    for account in existing_accounts or []:
        homepage_url = str(getattr(account, "homepage_url", "") or "")
        try:
            normalized, sec_uid = normalize_douyin_homepage_url(homepage_url)
        except Exception:
            normalized, sec_uid = homepage_url.strip().rstrip("/"), ""
        if normalized:
            existing_by_key.add("url:" + normalized)
        if sec_uid:
            existing_by_key.add("sec:" + sec_uid)

    seen_by_key: set[str] = set()
    for line_no, raw_line in enumerate(str(text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        # Ignore common header rows instead of counting them as invalid.
        if line_no == 1 and any(token in line.lower() for token in ("url", "homepage", "主页", "链接")) and not DOUYIN_URL_RE.search(line):
            continue
        url, parts = _split_line(line)
        if not url:
            preview.errors.append({"line_no": line_no, "line": line, "reason": "未找到主页链接"})
            continue
        try:
            normalized, sec_uid = normalize_douyin_homepage_url(url)
        except Exception as exc:
            preview.errors.append({"line_no": line_no, "line": line, "reason": str(exc)})
            continue
        name = parts[0] if parts else ""
        group = parts[1] if len(parts) > 1 else str(default_group or "").strip()
        key = "sec:" + sec_uid if sec_uid else "url:" + normalized
        action = "update" if key in existing_by_key or ("url:" + normalized) in existing_by_key else "add"
        reason = "已存在，将更新设置" if action == "update" else "将新增账号"
        if key in seen_by_key or ("url:" + normalized) in seen_by_key:
            action = "duplicate"
            reason = "本次导入中重复，已跳过"
        seen_by_key.add(key)
        seen_by_key.add("url:" + normalized)
        preview.rows.append(
            BatchImportRow(
                line_no=line_no,
                url=url,
                normalized_url=normalized,
                sec_uid=sec_uid,
                name=name[:80],
                group=group[:80],
                action=action,
                reason=reason,
                source=source,
            )
        )
    return preview


def read_batch_import_file(path: str, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    file_path = Path(str(path or "")).expanduser()
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError("导入文件不存在")
    if file_path.stat().st_size > max_bytes:
        raise ValueError("导入文件过大，请控制在 2MB 内")
    suffix = file_path.suffix.lower()
    if suffix not in {".txt", ".csv"}:
        raise ValueError("当前支持 TXT / CSV 文件导入")
    raw = file_path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def preview_to_report_lines(preview: BatchImportPreview, *, limit: int = 80) -> list[str]:
    lines = [preview.summary_text()]
    for row in preview.rows[:limit]:
        label = {"add": "新增", "update": "更新", "duplicate": "重复", "invalid": "无效"}.get(row.action, row.action)
        display = row.name or row.normalized_url
        suffix = f"，分组：{row.group}" if row.group else ""
        lines.append(f"第 {row.line_no} 行 [{label}] {display}{suffix}｜{row.reason}")
    if len(preview.rows) > limit:
        lines.append(f"... 其余 {len(preview.rows) - limit} 行省略")
    for error in preview.errors[: max(0, limit - len(lines))]:
        lines.append(f"第 {error.get('line_no')} 行 [无效] {error.get('reason')}｜{error.get('line')}")
    return lines
