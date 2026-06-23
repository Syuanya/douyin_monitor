from __future__ import annotations

import os
import json
import secrets
import shutil
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.core.application.service_container import DouyinMonitorServices
from app.core.content_monitor.services.batch_import_service import parse_batch_import_text
from app.core.ui_services.home_dashboard_service import HomeDashboardService
from app.core.ui_services.performance_observability_service import PerformanceObservabilityService
from app.core.ui_services.download_history_service import DownloadHistoryService
from app.core.ui_services.diagnostic_workflow import DiagnosticWorkflow, HealthCheckResult
from app.core.ui_services.storage_browser_service import StorageBrowserService
from app.core.ui_services.settings_workflow import SettingsWorkflow
from app.core.ui_services.task_center_service import TaskCenterFacadeService
from app.core.update.versioning import normalize_version
from app.core.version import APP_VERSION

from .jobs import WebJobRegistry
from .serializers import account_to_dict, item_to_dict


@dataclass(slots=True)
class WebAppShim:
    services: DouyinMonitorServices


class WebRuntime:
    """Headless runtime used by the Linux web server."""

    def __init__(self, run_path: str):
        self.run_path = str(Path(run_path).expanduser().resolve())
        Path(self.run_path).mkdir(parents=True, exist_ok=True)
        self.services = DouyinMonitorServices(self.run_path)
        self.app_shim = WebAppShim(self.services)
        self.jobs = WebJobRegistry()
        self.dashboard = HomeDashboardService(self.app_shim)
        self.observability = PerformanceObservabilityService(self.app_shim)
        self.download_history = DownloadHistoryService(self.app_shim)
        self.diagnostics = DiagnosticWorkflow(self.app_shim)
        self.storage_browser = StorageBrowserService(self.app_shim)
        self.settings_workflow = SettingsWorkflow(self.app_shim)
        self.task_center = TaskCenterFacadeService(self.app_shim)

    @property
    def monitor(self):
        return self.services.douyin_content_monitor

    @property
    def parser(self):
        return self.services.video_parser

    async def close(self) -> None:
        try:
            await self.monitor.stop_periodic_check()
        except Exception:
            pass
        pool = getattr(self.services, "download_http_client_pool", None)
        if pool is not None and hasattr(pool, "aclose"):
            try:
                await pool.aclose()
            except Exception:
                pass

    def accounts(self, *, include_items: bool = False) -> list[dict[str, Any]]:
        return [account_to_dict(account, include_items=include_items) for account in list(self.monitor.accounts)]

    def account_detail(self, account_id: str) -> dict[str, Any] | None:
        account = self.monitor.find_account(account_id)
        return account_to_dict(account, include_items=True) if account else None

    def items(self, account_id: str, *, status: str = "") -> list[dict[str, Any]]:
        account = self.monitor.find_account(account_id)
        if not account:
            return []
        items = [item_to_dict(item) for item in list(getattr(account, "items", []) or [])]
        if status:
            items = [item for item in items if str(item.get("status") or "") == status]
        return items


    def new_items(self, *, query: str = "") -> list[dict[str, Any]]:
        needle = str(query or "").strip().lower()
        rows: list[dict[str, Any]] = []
        for account in list(self.monitor.accounts):
            account_data = account_to_dict(account, include_items=False)
            account_name = account_data.get("display_name") or account_data.get("douyin_nickname") or "抖音用户"
            for item in list(getattr(account, "items", []) or []):
                status = str(getattr(item, "status", "") or "")
                if status not in {"new", "count_only"}:
                    continue
                row = item_to_dict(item)
                row["account_id"] = account.account_id
                row["account_name"] = account_name
                row["account_homepage_url"] = account_data.get("homepage_url") or ""
                text = " ".join(str(row.get(key) or "") for key in ("title", "description", "share_url", "item_id", "account_name")).lower()
                if needle and needle not in text:
                    continue
                rows.append(row)
        return sorted(rows, key=lambda row: str(row.get("create_time") or row.get("detected_at") or ""), reverse=True)

    async def mark_items_seen(self, pairs: list[dict[str, Any]]) -> dict[str, Any]:
        normalized: list[tuple[str, str]] = []
        for pair in pairs or []:
            account_id = str(pair.get("account_id") or "").strip()
            item_id = str(pair.get("item_id") or "").strip()
            if account_id and item_id:
                normalized.append((account_id, item_id))
        return await self.monitor.mark_items_seen_batch(normalized)

    async def download_items(self, pairs: list[dict[str, Any]]) -> dict[str, Any]:
        grouped: dict[str, list[str]] = {}
        for pair in pairs or []:
            account_id = str(pair.get("account_id") or "").strip()
            item_id = str(pair.get("item_id") or "").strip()
            if account_id and item_id:
                grouped.setdefault(account_id, []).append(item_id)
        results: list[dict[str, Any]] = []
        for account_id, item_ids in grouped.items():
            results.append(await self.monitor.download_items_batch(account_id, item_ids, title_prefix="Web批量下载"))
        return {"success": all(item.get("success") for item in results) if results else True, "total_accounts": len(grouped), "results": results}

    async def check_accounts_batch(self, account_ids: list[str]) -> dict[str, Any]:
        ids = [str(item) for item in account_ids if str(item or "").strip()]
        if not ids:
            return await self.monitor.check_all_enabled()
        results: list[dict[str, Any]] = []
        for account_id in ids:
            result = await self.monitor.check_account(account_id)
            results.append({"account_id": account_id, **result})
        return {"success": all(item.get("success") for item in results), "total": len(results), "results": results}

    def download_history_records(self, *, status: str = "all", limit: int = 100) -> dict[str, Any]:
        records = self.download_history.records(status_filter=status, limit=limit)
        return {"counts": self.download_history.counts(), "records": records}

    def batch_import_preview(self, text: str, default_group: str = "", source: str = "web") -> dict[str, Any]:
        preview = parse_batch_import_text(
            text,
            default_group=default_group,
            existing_accounts=list(self.monitor.accounts),
            source=source,
        )
        return {
            "summary": preview.summary_text(),
            "counts": preview.counts(),
            "rows": [row.to_dict() for row in preview.rows],
            "errors": list(preview.errors),
        }

    async def commit_batch_import(
        self,
        text: str,
        *,
        default_group: str = "",
        auto_download_policy: str = "none",
        notify_enabled: bool = True,
        start_monitor: bool = False,
        source: str = "web",
    ) -> dict[str, Any]:
        preview = parse_batch_import_text(
            text,
            default_group=default_group,
            existing_accounts=list(self.monitor.accounts),
            source=source,
        )
        added = updated = failed = started = 0
        failures: list[dict[str, Any]] = []
        changed_ids: list[str] = []
        for row in preview.valid_rows:
            try:
                before_ids = {account.account_id for account in self.monitor.accounts}
                account = await self.monitor.add_account(row.normalized_url, row.name)
                if account.account_id in before_ids:
                    updated += 1
                else:
                    added += 1
                await self.monitor.update_account_settings(
                    account.account_id,
                    display_name=row.name or account.display_name,
                    group_name=row.group,
                    auto_download_policy=auto_download_policy,
                    notify_enabled=bool(notify_enabled),
                )
                if start_monitor:
                    ok = await self.monitor.start_monitor(account.account_id)
                    started += 1 if ok else 0
                changed_ids.append(account.account_id)
            except Exception as exc:
                failed += 1
                failures.append({"line_no": row.line_no, "url": row.normalized_url, "reason": str(exc)})
        counts = preview.counts()
        return {
            "success": failed == 0,
            "summary": f"导入完成：新增 {added}，更新 {updated}，启动监控 {started}，失败 {failed}",
            "preview_counts": counts,
            "added": added,
            "updated": updated,
            "failed": failed,
            "started": started,
            "duplicate": counts.get("duplicate", 0),
            "invalid": counts.get("invalid", 0),
            "account_ids": changed_ids,
            "failures": failures,
            "errors": list(preview.errors),
        }


    async def diagnostic_results(self, *, include_network: bool = False, include_douyin: bool = False) -> dict[str, Any]:
        checks = [
            self.diagnostics.check_python_runtime,
            self.diagnostics.check_dependencies,
            self.diagnostics.check_sqlite,
            self.diagnostics.check_disk_space,
            self.diagnostics.check_cookie,
            self.diagnostics.check_parser,
            self.diagnostics.check_parser_backend,
            self.diagnostics.check_parser_registry,
            self.diagnostics.check_parser_latency,
            self.diagnostics.check_download_strategy,
            self.diagnostics.check_storage_permission,
            self.diagnostics.check_temp_files,
            self.diagnostics.check_task_queue,
            self.diagnostics.check_cookie_health_observability,
            self.diagnostics.check_rate_limiter_observability,
            self.diagnostics.check_batch_jobs,
            self.diagnostics.check_segmented_download,
        ]
        if include_network:
            checks.append(self.diagnostics.check_network)
            checks.append(self.diagnostics.check_proxy)
        if include_douyin:
            checks.append(self.diagnostics.check_douyin_access)
        results: list[dict[str, Any]] = []
        counts: dict[str, int] = {}
        for check in checks:
            try:
                result = await check()
            except Exception as exc:
                result = HealthCheckResult(getattr(check, "__name__", "检查项"), "异常", str(exc), "请导出诊断信息并检查日志。")
            row = {"name": result.name, "status": result.status, "detail": result.detail, "next_step": result.next_step}
            counts[result.status] = counts.get(result.status, 0) + 1
            results.append(row)
        return {"total": len(results), "counts": counts, "results": results}

    def export_diagnostics_bundle(self) -> str:
        from app.core.diagnostics import export_diagnostic_bundle
        return export_diagnostic_bundle(self.services, output_dir=Path(self.run_path) / "diagnostics")

    def cookie_management(self, platform: str = "douyin") -> dict[str, Any]:
        settings = getattr(self.services, "settings_config", None)
        cookies_config = getattr(settings, "cookies_config", {}) if settings is not None else {}
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        disabled = set(str(x) for x in user_config.get(f"{platform}_disabled_cookie_hashes", []) if x)
        pool = []
        try:
            from app.core.media.cookie_utils import parse_cookie_pool
            pool = parse_cookie_pool(cookies_config.get(f"{platform}_cookie_pool") or cookies_config.get(f"{platform}_cookie") or "")
        except Exception:
            raw = str(cookies_config.get(f"{platform}_cookie") or "")
            pool = [raw] if raw else []
        health_store = getattr(self.services, "cookie_health_store", None)
        health = health_store.snapshot(platform) if health_store is not None and hasattr(health_store, "snapshot") else {}
        rows = []
        for index, cookie in enumerate(pool, start=1):
            key = self._cookie_hash(cookie)
            state = health.get(key, {}) if isinstance(health, dict) else {}
            rows.append({
                "index": index,
                "hash": key,
                "masked": self._mask_cookie(cookie),
                "disabled": key in disabled,
                "success_count": state.get("success_count", 0),
                "failure_count": state.get("failure_count", 0),
                "empty_response_count": state.get("empty_response_count", 0),
                "cooldown_until": state.get("cooldown_until", 0),
                "last_reason": state.get("last_reason", ""),
                "score": state.get("score", 1.0),
            })
        return {"platform": platform, "total": len(rows), "rows": rows, "summary": self.observability.cookie_health_summary(platform)}

    def _cookie_pool(self, platform: str) -> list[str]:
        settings = getattr(self.services, "settings_config", None)
        cookies_config = getattr(settings, "cookies_config", {}) if settings is not None else {}
        try:
            from app.core.media.cookie_utils import parse_cookie_pool
            return parse_cookie_pool(cookies_config.get(f"{platform}_cookie_pool") or cookies_config.get(f"{platform}_cookie") or "")
        except Exception:
            raw = str(cookies_config.get(f"{platform}_cookie") or "")
            return [raw] if raw else []

    async def set_cookie_disabled(self, platform: str, cookie_hash: str, disabled: bool) -> dict[str, Any]:
        settings = getattr(self.services, "settings_config", None)
        manager = getattr(self.services, "config_manager", None)
        if settings is None or manager is None:
            return {"success": False, "reason": "设置服务不可用"}
        key = f"{platform}_disabled_cookie_hashes"
        values = set(str(x) for x in settings.user_config.get(key, []) if x)
        if disabled:
            values.add(cookie_hash)
        else:
            values.discard(cookie_hash)
        settings.user_config[key] = sorted(values)
        await manager.save_user_config(settings.user_config)
        settings.adopt_user_config(settings.user_config)
        return {"success": True, "disabled": disabled, "hash": cookie_hash}

    async def delete_cookie(self, platform: str, cookie_hash: str) -> dict[str, Any]:
        pool = self._cookie_pool(platform)
        remaining = [cookie for cookie in pool if self._cookie_hash(cookie) != cookie_hash]
        if len(remaining) == len(pool):
            return {"success": False, "reason": "未找到 Cookie"}
        return await self.update_cookie_config(platform, "\n".join(remaining))

    def test_cookie(self, platform: str, cookie_hash: str) -> dict[str, Any]:
        pool = self._cookie_pool(platform)
        cookie = next((item for item in pool if self._cookie_hash(item) == cookie_hash), "")
        if not cookie:
            return {"success": False, "reason": "未找到 Cookie"}
        required_markers = ["sessionid", "ttwid", "passport_csrf_token", "sid_guard", "odin_tt"]
        found = [marker for marker in required_markers if marker.lower() in cookie.lower()]
        score = min(1.0, 0.25 + len(found) * 0.2)
        return {"success": True, "hash": cookie_hash, "score": round(score, 2), "found_markers": found, "reason": "结构检查完成；真实可用性需联网检测。"}

    async def update_cookie_config(self, platform: str, raw_cookie_text: str) -> dict[str, Any]:
        settings = getattr(self.services, "settings_config", None)
        manager = getattr(self.services, "config_manager", None)
        if settings is None or manager is None:
            return {"success": False, "reason": "设置服务不可用"}
        from app.core.media.cookie_utils import parse_cookie_pool, sanitize_cookie_header
        cookies_config = dict(getattr(settings, "cookies_config", {}) or {})
        pool = parse_cookie_pool(raw_cookie_text)
        cookies_config[f"{platform}_cookie_pool"] = pool
        cookies_config[f"{platform}_cookie"] = pool[0] if pool else sanitize_cookie_header(raw_cookie_text)
        await manager.save_cookies_config(cookies_config)
        settings.adopt_cookies_config(cookies_config)
        try:
            self.services._sync_saved_cookies_to_parser()
        except Exception:
            pass
        return {"success": True, "count": len(pool), "summary": f"已保存 {len(pool)} 条 Cookie"}

    def media_library(self, *, account_id: str = "", query: str = "", status: str = "all", media_type: str = "all", limit: int = 300) -> dict[str, Any]:
        q = str(query or "").lower().strip()
        rows: list[dict[str, Any]] = []
        for account in list(self.monitor.accounts):
            if account_id and account.account_id != account_id:
                continue
            account_data = account_to_dict(account, include_items=False)
            account_name = account_data.get("display_name") or account_data.get("douyin_nickname") or "抖音用户"
            for item in list(getattr(account, "items", []) or []):
                row = item_to_dict(item)
                row["account_id"] = account.account_id
                row["account_name"] = account_name
                row["account_homepage_url"] = account_data.get("homepage_url") or ""
                item_status = str(row.get("status") or "")
                if status and status != "all" and item_status != status:
                    continue
                kind = str(row.get("media_type") or row.get("item_type") or row.get("type") or "").lower()
                if media_type != "all" and media_type and media_type not in kind and str(row.get("status")) != media_type:
                    continue
                text = " ".join(str(row.get(key) or "") for key in ("title", "description", "share_url", "item_id", "account_name")).lower()
                if q and q not in text:
                    continue
                rows.append(row)
        rows.sort(key=lambda row: str(row.get("create_time") or row.get("detected_at") or row.get("item_id") or ""), reverse=True)
        counts: dict[str, int] = {}
        for row in rows:
            key = str(row.get("status") or "unknown")
            counts[key] = counts.get(key, 0) + 1
        return {"total": len(rows), "counts": counts, "items": rows[: max(1, int(limit or 300))]}

    def media_item_detail(self, account_id: str, item_id: str) -> dict[str, Any] | None:
        for item in self.items(account_id):
            if str(item.get("item_id") or "") == str(item_id):
                item["account_id"] = account_id
                item["local_files"] = self._find_local_media_files(item)
                return item
        return None

    def storage_snapshot(self, *, path: str = "", query: str = "", media_filter: str = "all", sort_mode: str = "name_asc") -> dict[str, Any]:
        root, target = self.storage_browser.resolve_target(path or None)
        folders, files = self.storage_browser.scan(target, query=query, media_filter=media_filter, sort_mode=sort_mode)
        def row(p: Path, kind: str) -> dict[str, Any]:
            rel = str(p.relative_to(root)) if self.storage_browser.is_inside_root(p, root) else p.name
            return {"name": p.name, "path": str(p), "relative_path": rel, "kind": kind, "size": self.storage_browser.safe_file_size(p), "is_video": self.storage_browser.is_video_file(p), "is_image": self.storage_browser.is_image_file(p)}
        try:
            current_relative = str(target.relative_to(root)) if target != root else ""
        except ValueError:
            current_relative = ""
        parent_relative = "/".join(Path(current_relative).parts[:-1]) if current_relative else ""
        return {
            "root": str(root),
            "current": str(target),
            "current_relative": current_relative,
            "parent_relative": parent_relative,
            "folders": [row(p, "folder") for p in folders],
            "files": [row(p, "file") for p in files],
        }

    def storage_stats(self) -> dict[str, Any]:
        root = self.storage_browser.root_path()
        total_files = total_size = videos = images = temp_files = 0
        by_folder: dict[str, dict[str, Any]] = {}
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                size = self.storage_browser.safe_file_size(path)
                total_files += 1
                total_size += size
                if self.storage_browser.is_video_file(path):
                    videos += 1
                if self.storage_browser.is_image_file(path):
                    images += 1
                if path.suffix.lower() in {".tmp", ".part", ".download", ".segment"}:
                    temp_files += 1
                top = path.relative_to(root).parts[0] if path.relative_to(root).parts else "根目录"
                bucket = by_folder.setdefault(top, {"name": top, "files": 0, "size": 0})
                bucket["files"] += 1
                bucket["size"] += size
        except Exception:
            pass
        folders = sorted(by_folder.values(), key=lambda row: row.get("size", 0), reverse=True)[:20]
        return {"root": str(root), "total_files": total_files, "total_size": total_size, "videos": videos, "images": images, "temp_files": temp_files, "folders": folders}


    def resolve_storage_file(self, relative_path: str) -> Path | None:
        """Resolve a downloadable/previewable storage file safely under the download root."""
        root, target = self.storage_browser.resolve_target(relative_path or None)
        if not self.storage_browser.is_inside_root(target, root):
            return None
        if not target.exists() or not target.is_file():
            return None
        if not self.storage_browser.is_media_file(target):
            return None
        return target

    def delete_storage_path(self, relative_path: str) -> dict[str, Any]:
        root, target = self.storage_browser.resolve_target(relative_path or None)
        if not self.storage_browser.is_inside_root(target, root) or target == root:
            return {"success": False, "reason": "拒绝删除下载根目录或越界路径"}
        if not target.exists():
            return {"success": False, "reason": "路径不存在"}
        try:
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
            return {"success": True, "path": str(target)}
        except Exception as exc:
            return {"success": False, "reason": str(exc)}

    def cleanup_temp_files(self) -> dict[str, Any]:
        root = self.storage_browser.root_path()
        suffixes = {".tmp", ".part", ".download", ".segment"}
        deleted = 0
        bytes_deleted = 0
        errors: list[str] = []
        try:
            for path in root.rglob("*"):
                if path.is_file() and path.suffix.lower() in suffixes:
                    try:
                        size = self.storage_browser.safe_file_size(path)
                        path.unlink()
                        deleted += 1
                        bytes_deleted += size
                    except Exception as exc:
                        errors.append(f"{path.name}: {exc}")
        except Exception as exc:
            errors.append(str(exc))
        return {"success": not errors, "deleted": deleted, "bytes_deleted": bytes_deleted, "errors": errors[:20]}

    def log_files(self) -> dict[str, Any]:
        candidates = []
        for folder in [Path(self.run_path) / "logs", Path(self.run_path) / "config", Path.cwd() / "logs", Path.cwd() / "scripts" / "logs"]:
            if folder.exists():
                for path in folder.glob("*.log"):
                    try:
                        candidates.append({"name": path.name, "path": str(path), "size": path.stat().st_size, "mtime": path.stat().st_mtime})
                    except OSError:
                        pass
        candidates.sort(key=lambda row: row.get("mtime", 0), reverse=True)
        return {"total": len(candidates), "files": candidates[:50]}

    def read_log_tail(self, name: str, *, lines: int = 200) -> dict[str, Any]:
        files = self.log_files().get("files", [])
        match = next((row for row in files if row.get("name") == name or row.get("path") == name), None)
        if not match:
            return {"success": False, "reason": "日志文件不存在", "content": ""}
        path = Path(str(match["path"]))
        try:
            data = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(lines or 200)):]
            return {"success": True, "name": path.name, "content": "\n".join(data)}
        except Exception as exc:
            return {"success": False, "reason": str(exc), "content": ""}

    def resolve_log_file(self, name: str) -> Path | None:
        files = self.log_files().get("files", [])
        match = next((row for row in files if row.get("name") == name or row.get("path") == name), None)
        if not match:
            return None
        path = Path(str(match["path"]))
        return path if path.exists() and path.is_file() else None

    def search_logs(self, query: str = "", level: str = "", *, lines: int = 500) -> dict[str, Any]:
        needle = str(query or "").lower().strip()
        level = str(level or "").upper().strip()
        matches: list[dict[str, Any]] = []
        for row in self.log_files().get("files", []):
            path = Path(str(row.get("path") or ""))
            try:
                content = path.read_text(encoding="utf-8", errors="replace").splitlines()[-max(1, int(lines or 500)):]
            except Exception:
                continue
            for idx, line in enumerate(content, start=1):
                hay = line.lower()
                if needle and needle not in hay:
                    continue
                if level and level not in line.upper():
                    continue
                matches.append({"file": path.name, "line": idx, "content": line})
                if len(matches) >= 300:
                    return {"total": len(matches), "matches": matches}
        return {"total": len(matches), "matches": matches}

    def list_backups(self) -> dict[str, Any]:
        folders = [Path(self.run_path) / "backups", Path(self.run_path) / "config" / "backups"]
        rows: list[dict[str, Any]] = []
        for folder in folders:
            if not folder.exists():
                continue
            for path in folder.glob("*.zip"):
                try:
                    rows.append({"name": path.name, "path": str(path), "size": path.stat().st_size, "mtime": path.stat().st_mtime})
                except OSError:
                    pass
        rows.sort(key=lambda row: row.get("mtime", 0), reverse=True)
        return {"total": len(rows), "backups": rows[:100]}

    def resolve_backup_file(self, name: str) -> Path | None:
        for row in self.list_backups().get("backups", []):
            if row.get("name") == name or row.get("path") == name:
                path = Path(str(row.get("path")))
                if path.exists() and path.is_file():
                    return path
        return None

    def resolve_media_file(self, account_id: str, item_id: str, index: int = 0) -> Path | None:
        detail = self.media_item_detail(account_id, item_id)
        files = detail.get("local_files", []) if isinstance(detail, dict) else []
        try:
            row = files[int(index)]
            path = Path(str(row.get("path") or ""))
        except Exception:
            return None
        root = self.storage_browser.root_path()
        if path.exists() and path.is_file() and self.storage_browser.is_inside_root(path, root):
            return path
        return None


    def create_media_archive(self, account_id: str, item_id: str) -> Path | None:
        """Create a temporary zip archive for all local files attached to a media item."""
        detail = self.media_item_detail(account_id, item_id)
        files = detail.get("local_files", []) if isinstance(detail, dict) else []
        if not files:
            return None
        root = self.storage_browser.root_path()
        export_dir = Path(self.run_path) / "exports" / "media"
        export_dir.mkdir(parents=True, exist_ok=True)
        safe_item = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(item_id or "media"))[:80]
        archive_path = export_dir / f"media_{safe_item}_{int(time.time())}.zip"
        written = 0
        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for row in files:
                path = Path(str(row.get("path") or ""))
                if not path.exists() or not path.is_file():
                    continue
                if not self.storage_browser.is_inside_root(path, root):
                    continue
                arcname = path.name
                # Avoid duplicate names inside the archive.
                if arcname in zf.namelist():
                    arcname = f"{written + 1}_{arcname}"
                zf.write(path, arcname=arcname)
                written += 1
        if written <= 0:
            try:
                archive_path.unlink(missing_ok=True)
            except Exception:
                pass
            return None
        return archive_path

    def storage_scan_empty(self) -> dict[str, Any]:
        root = self.storage_browser.root_path()
        rows: list[dict[str, Any]] = []
        try:
            for path in root.rglob("*"):
                if path.is_file() and self.storage_browser.safe_file_size(path) == 0:
                    rows.append({"name": path.name, "path": str(path), "relative_path": str(path.relative_to(root)), "size": 0})
                    if len(rows) >= 500:
                        break
        except Exception as exc:
            return {"success": False, "reason": str(exc), "items": rows}
        return {"success": True, "total": len(rows), "items": rows}

    def storage_scan_duplicates(self, *, max_files: int = 2000) -> dict[str, Any]:
        """Find likely duplicate files by size and sha256 within the download root."""
        root = self.storage_browser.root_path()
        by_size: dict[int, list[Path]] = {}
        scanned = 0
        try:
            for path in root.rglob("*"):
                if not path.is_file():
                    continue
                size = self.storage_browser.safe_file_size(path)
                if size <= 0:
                    continue
                by_size.setdefault(size, []).append(path)
                scanned += 1
                if scanned >= max(1, int(max_files or 2000)):
                    break
        except Exception as exc:
            return {"success": False, "reason": str(exc), "groups": []}
        groups = []
        for size, paths in by_size.items():
            if len(paths) < 2:
                continue
            by_hash: dict[str, list[Path]] = {}
            for path in paths:
                try:
                    h = hashlib.sha256()
                    with path.open("rb") as fh:
                        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
                            h.update(chunk)
                    by_hash.setdefault(h.hexdigest(), []).append(path)
                except Exception:
                    continue
            for digest, matches in by_hash.items():
                if len(matches) < 2:
                    continue
                groups.append({
                    "hash": digest,
                    "size": size,
                    "count": len(matches),
                    "files": [{"name": p.name, "path": str(p), "relative_path": str(p.relative_to(root)), "size": size} for p in matches],
                })
                if len(groups) >= 100:
                    return {"success": True, "scanned": scanned, "groups": groups}
        return {"success": True, "scanned": scanned, "groups": groups}

    def delete_storage_paths(self, relative_paths: list[str]) -> dict[str, Any]:
        deleted = 0
        errors: list[str] = []
        for relative_path in relative_paths or []:
            result = self.delete_storage_path(str(relative_path))
            if result.get("success"):
                deleted += 1
            else:
                errors.append(f"{relative_path}: {result.get('reason') or '删除失败'}")
        return {"success": not errors, "deleted": deleted, "errors": errors[:50]}

    def network_risk_summary(self) -> dict[str, Any]:
        cookie = self.observability.cookie_health_summary("douyin")
        limiter = self.observability.rate_limiter_summary()
        risk_accounts = []
        for account in list(self.monitor.accounts):
            last_error = str(getattr(account, "last_error", "") or "")
            status = str(getattr(account, "status", "") or "")
            combined = f"{last_error} {status}"
            if any(key in combined for key in ("风控", "空响应", "Cookie", "登录", "验证", "risk", "empty")):
                risk_accounts.append({"account_id": account.account_id, "name": account.display_name or account.douyin_nickname, "status": status, "last_error": last_error})
        suggestions = []
        if float(limiter.get("global_delay", 0) or 0) > 0:
            suggestions.append("当前处于全局退避，建议等待冷却结束后再检测。")
        if int(cookie.get("cooldown", 0) or 0) > 0:
            suggestions.append("存在冷却中的 Cookie，建议降低并发或更换 Cookie。")
        if not suggestions:
            suggestions.append("当前未发现明显风控信号。批量同步仍建议分批执行。")
        return {"cookie": cookie, "rate_limiter": limiter, "risk_accounts": risk_accounts, "suggestions": suggestions}

    def notification_state(self) -> dict[str, Any]:
        settings = getattr(self.services, "settings_config", None)
        user_config = dict(getattr(settings, "user_config", {}) or {}) if settings else {}
        rows = []
        for account in list(self.monitor.accounts):
            rows.append({"account_id": account.account_id, "name": account.display_name or account.douyin_nickname or account.account_id, "notify_enabled": bool(getattr(account, "notify_enabled", True)), "notify_mode": getattr(account, "notify_mode", "default")})
        return {"global": {key: user_config.get(key) for key in ("notification_enabled", "notify_on_new_work", "notify_on_download_complete", "notify_on_download_failed", "webhook_url")}, "accounts": rows}

    async def update_notification_state(self, values: dict[str, Any]) -> dict[str, Any]:
        global_values = values.get("global") if isinstance(values.get("global"), dict) else {}
        accounts = values.get("accounts") if isinstance(values.get("accounts"), list) else []
        settings = getattr(self.services, "settings_config", None)
        if global_values and settings is not None:
            settings.user_config.update(global_values)
            await self.services.config_manager.save_user_config(settings.user_config)
            settings.adopt_user_config(settings.user_config)
        updated = 0
        for row in accounts:
            account_id = str(row.get("account_id") or "")
            if not account_id:
                continue
            kwargs = {}
            if "notify_enabled" in row:
                kwargs["notify_enabled"] = bool(row.get("notify_enabled"))
            if "notify_mode" in row:
                kwargs["notify_mode"] = str(row.get("notify_mode") or "default")
            if kwargs:
                ok = await self.monitor.update_account_settings(account_id, **kwargs)
                updated += 1 if ok else 0
        return {"success": True, "updated_accounts": updated}

    def update_state(self) -> dict[str, Any]:
        service = getattr(self.services, "auto_update_service", None)
        settings = getattr(self.services, "settings_config", None)
        config = dict(getattr(settings, "user_config", {}) or {}) if settings else {}
        state_path = getattr(service, "last_check_path", None)
        state = {}
        try:
            if state_path and Path(state_path).exists():
                import json
                state = json.loads(Path(state_path).read_text(encoding="utf-8"))
        except Exception as exc:
            state = {"error": str(exc)}
        return {"current_version": normalize_version(APP_VERSION), "enabled": bool(config.get("auto_update_enabled", False)), "manifest_url": config.get("auto_update_manifest_url", ""), "channel": config.get("auto_update_channel", "stable"), "last_check": state}

    async def check_updates(self, *, allow_network: bool = False) -> dict[str, Any]:
        service = getattr(self.services, "auto_update_service", None)
        if service is None:
            return {"success": False, "reason": "自动更新服务不可用"}
        if not allow_network:
            return {"success": True, "dry_run": True, "state": self.update_state(), "reason": "未启用网络检查；传 allow_network=true 才会访问 manifest。"}
        info = await service.check_for_updates()
        if info is None:
            return {"success": False, "reason": "未配置更新清单 URL"}
        asset = info.best_asset()
        return {"success": True, "available": info.available, "current_version": info.current_version, "latest_version": info.latest_version, "release_notes": info.release_notes, "asset": asset.__dict__ if asset else None}

    async def create_backup(self, *, full: bool = True) -> dict[str, Any]:
        path = await (self.settings_workflow.export_full_backup() if full else self.settings_workflow.export_config_package())
        return {"success": True, "path": str(path), "name": Path(path).name}


    def account_insights(self, account_id: str) -> dict[str, Any] | None:
        account = self.monitor.find_account(account_id)
        if account is None:
            return None
        detail = account_to_dict(account, include_items=True)
        items = list(getattr(account, "items", []) or [])
        status_counts: dict[str, int] = {}
        type_counts: dict[str, int] = {}
        for item in items:
            status = str(getattr(item, "status", "") or "unknown")
            media_type = str(getattr(item, "media_type", "") or getattr(item, "item_type", "") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            type_counts[media_type] = type_counts.get(media_type, 0) + 1
        records = self.task_center.records(500)
        names = {str(account_id), str(getattr(account, "display_name", "") or ""), str(getattr(account, "douyin_nickname", "") or "")}
        related = []
        for record in records:
            blob = " ".join(str(record.get(key) or "") for key in ("title", "detail", "category"))
            payload = record.get("retry_payload") if isinstance(record.get("retry_payload"), dict) else {}
            if str(payload.get("account_id") or "") == account_id or any(name and name in blob for name in names):
                related.append(record)
        failures = [r for r in related if str(r.get("status")) == "失败" or r.get("failed_count")]
        suggestions: list[str] = []
        last_error = str(getattr(account, "last_error", "") or "")
        if last_error:
            suggestions.append(self._advice_for_reason(last_error))
        if int(status_counts.get("new", 0) or 0) > 0 or int(status_counts.get("count_only", 0) or 0) > 0:
            suggestions.append("存在未处理新作品，可进入新作品箱批量下载或标记已处理。")
        if not suggestions:
            suggestions.append("账号当前没有明显异常；建议按监控间隔低频检测，避免频繁同步全部作品。")
        timeline: list[dict[str, Any]] = []
        for record in related[:120]:
            timestamp = record.get("updated_at") or record.get("created_at") or record.get("time") or 0
            timeline.append({
                "time": timestamp,
                "type": "task",
                "title": record.get("title") or record.get("category") or "任务记录",
                "status": record.get("status") or "",
                "detail": record.get("detail") or record.get("reason") or "",
            })
        for item in items[:120]:
            data = item_to_dict(item)
            timeline.append({
                "time": data.get("detected_at") or data.get("create_time") or data.get("publish_time") or 0,
                "type": "item",
                "title": data.get("title") or data.get("description") or data.get("item_id") or "作品",
                "status": data.get("status") or "",
                "detail": data.get("share_url") or "",
            })
        timeline.sort(key=lambda row: str(row.get("time") or ""), reverse=True)
        detail["insights"] = {
            "status_counts": status_counts,
            "type_counts": type_counts,
            "related_tasks": related[:30],
            "failures": failures[:30],
            "timeline": timeline[:80],
            "suggestions": list(dict.fromkeys(suggestions)),
            "recent_items": [item_to_dict(item) for item in items[:50]],
        }
        return detail

    @staticmethod
    def _advice_for_reason(reason: str) -> str:
        text = str(reason or "")
        if any(key in text for key in ("Cookie", "登录", "session", "验证")):
            return "疑似 Cookie / 登录态异常：请在 Cookie 管理中测试并更新 Cookie。"
        if any(key in text for key in ("风控", "空响应", "risk", "empty", "频率")):
            return "疑似网络/IP 风控：建议暂停批次、降低并发，等待冷却后再检测。"
        if any(key in text for key in ("不存在", "不可访问", "404", "主页")):
            return "主页不可访问或无公开作品：请打开主页确认账号状态。"
        return "请查看运行日志和诊断中心，并根据失败详情重试。"

    def download_queue_tasks(self, *, limit: int = 100) -> dict[str, Any]:
        records = self.task_center.records(limit)
        rows = []
        for record in records:
            category = str(record.get("category") or "")
            title = str(record.get("title") or "")
            if "下载" not in category and "下载" not in title:
                continue
            rows.append(record)
        counts: dict[str, int] = {}
        for row in rows:
            status = str(row.get("status") or "unknown")
            counts[status] = counts.get(status, 0) + 1
        return {"total": len(rows), "counts": counts, "tasks": rows[: max(1, int(limit or 100))]}

    @staticmethod
    def _coerce_epoch(value: Any) -> float:
        if value in (None, ""):
            return 0.0
        if isinstance(value, (int, float)):
            return float(value)
        text = str(value).strip()
        if not text:
            return 0.0
        try:
            return float(text)
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
            try:
                return time.mktime(time.strptime(text[:26].replace("Z", ""), fmt))
            except ValueError:
                continue
        return 0.0

    @staticmethod
    def _coerce_float(value: Any) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    def download_queue_realtime(self, *, limit: int = 100) -> dict[str, Any]:
        summary = self.task_center.queue_summary()
        snapshot = self.task_center.queue_snapshot()
        tasks = self.download_queue_tasks(limit=limit).get("tasks", [])
        running = []
        queued = []
        total_speed = 0.0
        now = time.time()
        for row in tasks:
            status = str(row.get("status") or "")
            completed = self._coerce_float(row.get("bytes_downloaded") or row.get("downloaded_bytes") or row.get("completed_bytes") or row.get("completed") or 0)
            total = self._coerce_float(row.get("total_bytes") or row.get("size") or row.get("total") or 0)
            started = self._coerce_epoch(row.get("started_at") or row.get("created_at"))
            updated = self._coerce_epoch(row.get("updated_at")) or now
            elapsed = max(0.001, updated - started) if started and updated >= started else 0.0
            speed = completed / elapsed if completed and elapsed else 0.0
            eta = max(0.0, (total - completed) / speed) if total and speed else 0.0
            enriched = dict(row)
            enriched.update({"speed_bps": round(speed, 2), "eta_seconds": round(eta, 1), "progress_ratio": round(completed / total, 4) if total else 0})
            total_speed += speed
            if status in {"运行中", "running", "downloading"}:
                running.append(enriched)
            else:
                queued.append(enriched)
        return {"summary": summary, "snapshot": snapshot, "running": running[:20], "queued": queued[:80], "total_speed_bps": round(total_speed, 2)}

    def cancel_task_record(self, task_id: str) -> dict[str, Any]:
        center = getattr(self.services, "task_center", None)
        if center is None or not hasattr(center, "cancel"):
            return {"success": False, "reason": "任务中心不可用"}
        center.cancel(task_id, "用户在 Web 端取消任务记录")
        return {"success": True, "reason": "任务记录已标记取消；已运行的底层下载可能需使用队列取消。"}

    async def retry_task_record(self, task_id: str) -> dict[str, Any]:
        record = next((r for r in self.task_center.records(500) if str(r.get("task_id")) == str(task_id)), None)
        if not record:
            return {"success": False, "reason": "任务不存在"}
        return await self.task_center.retry_record(record)

    def batch_job_failures(self, job_id: str, *, page: int = 1, page_size: int = 50) -> dict[str, Any]:
        detail = self.task_center.batch_job_detail(job_id)
        if not detail:
            return {"success": False, "reason": "批量任务不存在", "items": []}
        failed_ids = [str(item) for item in detail.get("failed_ids", []) if item]
        failure_reasons = detail.get("failure_reasons") if isinstance(detail.get("failure_reasons"), dict) else {}
        groups: dict[str, dict[str, Any]] = {}
        items = []
        for item_id in failed_ids:
            reason = str(failure_reasons.get(item_id) or detail.get("reason") or detail.get("detail") or "未知失败")
            category = self._failure_category(reason)
            bucket = groups.setdefault(category, {"category": category, "count": 0, "sample_reason": reason, "item_ids": []})
            bucket["count"] += 1
            bucket["item_ids"].append(item_id)
            items.append({"item_id": item_id, "category": category, "reason": reason})
        page = max(1, int(page or 1)); page_size = max(1, min(200, int(page_size or 50)))
        start = (page - 1) * page_size
        return {"success": True, "job_id": job_id, "total": len(items), "page": page, "page_size": page_size, "groups": list(groups.values()), "items": items[start:start + page_size]}

    @staticmethod
    def _failure_category(reason: str) -> str:
        text = str(reason or "")
        if any(key in text for key in ("Cookie", "登录", "session", "验证")):
            return "Cookie/登录态"
        if any(key in text for key in ("风控", "空响应", "risk", "empty", "429", "频率")):
            return "风控/限速"
        if any(key in text for key in ("网络", "timeout", "Connect", "DNS", "Proxy")):
            return "网络/代理"
        if any(key in text for key in ("磁盘", "权限", "Permission", "No space")):
            return "存储/权限"
        return "其他失败"

    async def retry_batch_job_category(self, job_id: str, *, category: str = "all") -> dict[str, Any]:
        detail = self.task_center.batch_job_detail(job_id)
        if not detail:
            return {"success": False, "reason": "批量任务不存在"}
        failures = self.batch_job_failures(job_id, page=1, page_size=10000)
        wanted = [item["item_id"] for item in failures.get("items", []) if category in {"all", "", item.get("category")}]
        payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
        account_id = str(payload.get("account_id") or "")
        if not account_id or not wanted:
            return {"success": False, "reason": "没有可重试的失败项"}
        return await self.monitor.download_items_batch(account_id, wanted, title_prefix=f"重试批量任务-{category or '全部'}")

    async def bulk_set_cookies_disabled(self, platform: str, cookie_hashes: list[str], disabled: bool) -> dict[str, Any]:
        updated = 0
        for cookie_hash in cookie_hashes or []:
            result = await self.set_cookie_disabled(platform, str(cookie_hash), disabled)
            if result.get("success"):
                updated += 1
        return {"success": True, "updated": updated, "disabled": disabled}

    def clear_logs(self, name: str = "") -> dict[str, Any]:
        files = self.log_files().get("files", [])
        targets = [row for row in files if not name or row.get("name") == name or row.get("path") == name]
        cleared = 0
        errors = []
        for row in targets:
            path = Path(str(row.get("path") or ""))
            try:
                if path.exists() and path.is_file():
                    path.write_text("", encoding="utf-8")
                    cleared += 1
            except Exception as exc:
                errors.append(f"{path.name}: {exc}")
        return {"success": not errors, "cleared": cleared, "errors": errors}

    async def test_notification(self, channel: str, message: str, *, allow_network: bool = False) -> dict[str, Any]:
        state = self.notification_state()
        config = state.get("global") or {}
        channel = str(channel or "webhook").lower().strip()
        message = str(message or "Douyin Monitor Web 通知测试")
        channel_fields = {
            "webhook": ["webhook_url"],
            "telegram": ["telegram_bot_token", "telegram_chat_id"],
            "bark": ["bark_url", "bark_key"],
            "serverchan": ["serverchan_sendkey"],
            "wecom": ["wecom_webhook_url"],
        }
        missing = [key for key in channel_fields.get(channel, []) if not str(config.get(key) or "").strip()]
        if channel not in channel_fields:
            return {"success": False, "reason": f"暂不支持通知渠道：{channel}"}
        if not allow_network:
            return {"success": not missing, "dry_run": True, "channel": channel, "message": message, "missing": missing, "reason": "Dry-run 完成；传 allow_network=true 才会真实请求通知渠道。"}
        if missing:
            return {"success": False, "channel": channel, "reason": "缺少配置：" + ", ".join(missing)}
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                if channel == "webhook":
                    response = await client.post(str(config.get("webhook_url")), json={"text": message, "source": "douyin-monitor-web"})
                elif channel == "telegram":
                    token = str(config.get("telegram_bot_token")); chat_id = str(config.get("telegram_chat_id"))
                    response = await client.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat_id, "text": message})
                elif channel == "bark":
                    base = str(config.get("bark_url") or "https://api.day.app").rstrip("/"); key = str(config.get("bark_key"))
                    response = await client.post(f"{base}/{key}", json={"title": "Douyin Monitor", "body": message})
                elif channel == "serverchan":
                    key = str(config.get("serverchan_sendkey"))
                    response = await client.post(f"https://sctapi.ftqq.com/{key}.send", data={"title": "Douyin Monitor", "desp": message})
                else:  # wecom
                    response = await client.post(str(config.get("wecom_webhook_url")), json={"msgtype": "text", "text": {"content": message}})
            return {"success": response.status_code < 400, "channel": channel, "status_code": response.status_code, "reason": response.text[:500]}
        except Exception as exc:
            return {"success": False, "channel": channel, "reason": str(exc)}


    def _auth_file_path(self) -> Path:
        path = Path(self.run_path) / "config" / "web_auth.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _read_auth_file(self) -> dict[str, Any]:
        path = self._auth_file_path()
        if not path.exists():
            return {"users": [], "audit": []}
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {"users": [], "audit": []}
        except Exception:
            return {"users": [], "audit": []}

    def _write_auth_file(self, data: dict[str, Any]) -> None:
        self._auth_file_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def access_users(self) -> dict[str, Any]:
        data = self._read_auth_file()
        users = []
        for user in data.get("users", []):
            token = str(user.get("token") or "")
            users.append({k: v for k, v in user.items() if k != "token"} | {"token_preview": (token[:4] + "…" + token[-4:]) if len(token) >= 12 else "已配置"})
        return {"total": len(users), "users": users, "audit": list(data.get("audit", []))[-50:]}

    def create_access_user(self, name: str, role: str = "viewer") -> dict[str, Any]:
        data = self._read_auth_file()
        user_id = secrets.token_hex(6)
        token = secrets.token_urlsafe(32)
        user = {"user_id": user_id, "name": str(name or user_id), "role": str(role or "viewer"), "token": token, "disabled": False, "created_at": int(time.time())}
        data.setdefault("users", []).append(user)
        data.setdefault("audit", []).append({"action": "create_user", "user_id": user_id, "time": int(time.time())})
        self._write_auth_file(data)
        return {"success": True, "user": {k: v for k, v in user.items() if k != "token"}, "token": token}

    def delete_access_user(self, user_id: str) -> dict[str, Any]:
        data = self._read_auth_file()
        before = len(data.get("users", []))
        data["users"] = [u for u in data.get("users", []) if str(u.get("user_id")) != str(user_id)]
        data.setdefault("audit", []).append({"action": "delete_user", "user_id": user_id, "time": int(time.time())})
        self._write_auth_file(data)
        return {"success": len(data["users"]) < before}

    def rotate_access_user(self, user_id: str) -> dict[str, Any]:
        data = self._read_auth_file(); token = secrets.token_urlsafe(32)
        for user in data.get("users", []):
            if str(user.get("user_id")) == str(user_id):
                user["token"] = token; user["rotated_at"] = int(time.time())
                data.setdefault("audit", []).append({"action": "rotate_token", "user_id": user_id, "time": int(time.time())})
                self._write_auth_file(data)
                return {"success": True, "token": token}
        return {"success": False, "reason": "用户不存在"}

    def restore_backup(self, name: str, *, apply: bool = False) -> dict[str, Any]:
        path = self.resolve_backup_file(name)
        if not path:
            return {"success": False, "reason": "备份文件不存在"}
        return self._restore_zip(path, apply=apply)

    async def restore_uploaded_backup(self, file: Any, *, apply: bool = False) -> dict[str, Any]:
        raw = await file.read(50 * 1024 * 1024 + 1)
        if len(raw) > 50 * 1024 * 1024:
            return {"success": False, "reason": "备份文件过大，请控制在 50MB 内"}
        folder = Path(self.run_path) / "backups" / "uploads"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (Path(str(getattr(file, "filename", "backup.zip") or "backup.zip")).name)
        path.write_bytes(raw)
        return self._restore_zip(path, apply=apply)

    def _restore_zip(self, path: Path, *, apply: bool = False) -> dict[str, Any]:
        if not zipfile.is_zipfile(path):
            return {"success": False, "reason": "不是有效 zip 备份"}
        safe_prefixes = ("config/", "data/config/", "accounts", "cookies", "default_settings", "user_settings")
        with zipfile.ZipFile(path, "r") as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            unsafe = [n for n in names if ".." in Path(n).parts or Path(n).is_absolute()]
            restorable = [n for n in names if not unsafe and (n.startswith(safe_prefixes) or "/config/" in n)]
            preview = {"total_files": len(names), "restorable_files": len(restorable), "unsafe_files": len(unsafe), "files": restorable[:200]}
            if not apply:
                return {"success": True, "dry_run": True, "backup": str(path), **preview, "reason": "校验完成；apply=true 才会写入配置目录。"}
            restore_root = Path(self.run_path)
            restore_root.mkdir(parents=True, exist_ok=True)
            restored = 0
            for name in restorable:
                target_name = name
                if "/config/" in target_name:
                    target_name = "config/" + target_name.split("/config/", 1)[1]
                elif target_name.startswith("data/config/"):
                    target_name = "config/" + target_name[len("data/config/"):]
                elif not target_name.startswith("config/"):
                    target_name = "config/" + Path(target_name).name
                target = restore_root / target_name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(zf.read(name))
                restored += 1
        return {"success": True, "restored": restored, "reason": "备份配置已恢复；建议重启容器加载新配置。"}

    def access_rbac_matrix(self) -> dict[str, Any]:
        return {
            "roles": [
                {"role": "viewer", "description": "只读：查看总览、账号、作品、任务、日志、备份列表和媒体预览。", "level": 0},
                {"role": "operator", "description": "操作员：可检测、同步、解析、下载、导入和导出诊断。", "level": 1},
                {"role": "admin", "description": "管理员：可修改设置、管理 Cookie、删除数据、恢复备份、管理访问用户。", "level": 2},
            ],
            "rules": [
                {"scope": "GET /api/*", "required": "viewer"},
                {"scope": "检测 / 同步 / 解析 / 下载 / 导入", "required": "operator"},
                {"scope": "设置 / Cookie 管理 / 访问控制 / 备份恢复 / 删除文件 / 清日志", "required": "admin"},
            ],
        }

    def access_state(self) -> dict[str, Any]:
        import os
        token = os.environ.get("DOUYIN_MONITOR_WEB_TOKEN", "")
        return {"token_configured": bool(token), "token_preview": (token[:4] + "…" + token[-4:]) if len(token) >= 12 else ("已配置" if token else "未配置"), "cors": os.environ.get("DOUYIN_MONITOR_WEB_CORS", "*"), "run_path": self.run_path, "auth_mode": "Bearer Token / X-Auth-Token"}

    @staticmethod
    def _cookie_hash(cookie: str) -> str:
        import hashlib
        return hashlib.sha256(str(cookie or "").encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _mask_cookie(cookie: str) -> str:
        text = str(cookie or "").strip()
        if len(text) <= 24:
            return "已配置" if text else ""
        return text[:10] + "…" + text[-10:]

    def _find_local_media_files(self, item: dict[str, Any]) -> list[dict[str, Any]]:
        item_id = str(item.get("item_id") or "")
        if not item_id:
            return []
        root = self.storage_browser.root_path()
        rows = []
        try:
            for path in root.rglob(f"*{item_id}*"):
                if path.is_file():
                    rows.append({"name": path.name, "path": str(path), "size": self.storage_browser.safe_file_size(path)})
                    if len(rows) >= 20:
                        break
        except Exception:
            pass
        return rows


def default_run_path() -> str:
    return os.environ.get("DOUYIN_MONITOR_RUN_PATH") or os.getcwd()
