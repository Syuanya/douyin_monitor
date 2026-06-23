from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator

from .context import WebRuntime, default_run_path
from .serializers import parse_event_to_dict

try:  # FastAPI is an optional web dependency.
    from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
    from fastapi.middleware.cors import CORSMiddleware
    from fastapi.responses import FileResponse, HTMLResponse, StreamingResponse, Response
    from fastapi.staticfiles import StaticFiles
    from pydantic import BaseModel, Field
except Exception as exc:  # pragma: no cover - only hit when running without web deps.
    raise RuntimeError("Web server dependencies are missing. Install: pip install -r requirements-web.txt") from exc


class AddAccountRequest(BaseModel):
    homepage_url: str
    display_name: str = ""
    group_name: str = ""
    start_monitor: bool = False


class BatchImportRequest(BaseModel):
    text: str = ""
    default_group: str = ""
    auto_download_policy: str = "none"
    notify_enabled: bool = True
    start_monitor: bool = False


class AccountSettingsRequest(BaseModel):
    display_name: str | None = None
    group_name: str | None = None
    auto_download_policy: str | None = None
    monitor_interval_minutes: float | None = None
    auto_sync_enabled: bool | None = None
    auto_pause_failures: int | None = None
    keep_recent_count: int | None = None
    notify_mode: str | None = None
    notify_enabled: bool | None = None


class BulkIdsRequest(BaseModel):
    account_ids: list[str] = Field(default_factory=list)


class ParseTextRequest(BaseModel):
    text: str
    concurrency: int | None = None
    download: bool = False


class ParsedMediaDownloadRequest(BaseModel):
    item: dict[str, Any] = Field(default_factory=dict)


class DownloadItemsRequest(BaseModel):
    item_ids: list[str] = Field(default_factory=list)


class ItemPair(BaseModel):
    account_id: str
    item_id: str


class ItemPairsRequest(BaseModel):
    items: list[ItemPair] = Field(default_factory=list)


class SettingsPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class StoragePathRequest(BaseModel):
    path: str = ""


class StoragePathsRequest(BaseModel):
    paths: list[str] = Field(default_factory=list)


class CookiePatchRequest(BaseModel):
    platform: str = "douyin"
    cookie_text: str = ""


class CookieHashRequest(BaseModel):
    platform: str = "douyin"
    cookie_hash: str = ""


class NotificationPatchRequest(BaseModel):
    values: dict[str, Any] = Field(default_factory=dict)


class NotificationTestRequest(BaseModel):
    channel: str = "webhook"
    message: str = "Douyin Monitor Web 通知测试"
    allow_network: bool = False


class CookieBulkRequest(BaseModel):
    platform: str = "douyin"
    cookie_hashes: list[str] = Field(default_factory=list)


class AccessUserRequest(BaseModel):
    name: str = ""
    role: str = "viewer"


class RestoreBackupRequest(BaseModel):
    name: str = ""
    apply: bool = False




_ROLE_ORDER = {"viewer": 0, "operator": 1, "admin": 2}


def _token_hash(token: str) -> str:
    return hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()[:16]


def _load_auth_data(run_path: str | None) -> dict[str, Any]:
    if not run_path:
        return {"users": [], "audit": []}
    path = Path(run_path) / "config" / "web_auth.json"
    if not path.exists():
        return {"users": [], "audit": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {"users": [], "audit": []}
    except Exception:
        return {"users": [], "audit": []}


def _write_auth_data(run_path: str | None, data: dict[str, Any]) -> None:
    if not run_path:
        return
    path = Path(run_path) / "config" / "web_auth.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    audit = data.get("audit") if isinstance(data.get("audit"), list) else []
    data["audit"] = audit[-500:]
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _append_audit(run_path: str | None, row: dict[str, Any]) -> None:
    try:
        data = _load_auth_data(run_path)
        audit = data.setdefault("audit", [])
        audit.append({"time": int(time.time()), **row})
        _write_auth_data(run_path, data)
    except Exception:
        pass


def _required_role(method: str, path: str) -> str:
    method = str(method or "GET").upper()
    path = str(path or "")
    if method == "GET":
        if path.startswith("/api/backups/download"):
            return "operator"
        return "viewer"
    admin_prefixes = (
        "/api/access",
        "/api/settings",
        "/api/backups/restore",
        "/api/backups/upload-restore",
        "/api/logs/clear",
        "/api/storage/delete",
        "/api/storage/bulk-delete",
        "/api/storage/cleanup-temp",
        "/api/cookies/delete",
        "/api/cookies/disable",
        "/api/cookies/enable",
        "/api/cookies/bulk",
        "/api/notifications",
    )
    if method == "DELETE" or any(path.startswith(prefix) for prefix in admin_prefixes):
        return "admin"
    return "operator"


def _role_allows(role: str, required: str) -> bool:
    return _ROLE_ORDER.get(str(role or "viewer"), 0) >= _ROLE_ORDER.get(str(required or "viewer"), 0)


def _require_token(expected_token: str, run_path: str | None = None):
    async def dependency(request: Request, authorization: str | None = Header(default=None), x_auth_token: str | None = Header(default=None)) -> dict[str, Any]:
        token = str(x_auth_token or request.query_params.get("x_auth_token") or request.query_params.get("token") or "")
        if authorization and authorization.lower().startswith("bearer "):
            token = authorization[7:].strip()
        identities: dict[str, dict[str, Any]] = {}
        if expected_token:
            identities[expected_token] = {"role": "admin", "name": "root", "user_id": "root"}
        auth_data = _load_auth_data(run_path)
        for user in auth_data.get("users", []):
            value = str(user.get("token") or "").strip()
            if value and not user.get("disabled"):
                identities[value] = {
                    "role": str(user.get("role") or "viewer"),
                    "name": str(user.get("name") or user.get("user_id") or "user"),
                    "user_id": str(user.get("user_id") or ""),
                }
        if not identities:
            request.state.web_user = {"role": "admin", "name": "dev", "user_id": "dev"}
            return request.state.web_user
        identity = identities.get(token)
        if identity is None:
            _append_audit(run_path, {"action": "auth_failed", "method": request.method, "path": request.url.path, "token_hash": _token_hash(token), "client": request.client.host if request.client else ""})
            raise HTTPException(status_code=401, detail="Unauthorized")
        required = _required_role(request.method, request.url.path)
        if not _role_allows(identity.get("role", "viewer"), required):
            _append_audit(run_path, {"action": "rbac_denied", "method": request.method, "path": request.url.path, "role": identity.get("role"), "required": required, "user_id": identity.get("user_id"), "client": request.client.host if request.client else ""})
            raise HTTPException(status_code=403, detail=f"Forbidden: requires {required}")
        if request.method.upper() != "GET":
            _append_audit(run_path, {"action": "api_write", "method": request.method, "path": request.url.path, "role": identity.get("role"), "user_id": identity.get("user_id"), "client": request.client.host if request.client else ""})
        request.state.web_user = identity
        return identity

    return dependency


def create_app(run_path: str | None = None) -> FastAPI:
    web_token = os.environ.get("DOUYIN_MONITOR_WEB_TOKEN", "").strip()
    resolved_run_path = run_path or default_run_path()
    static_dir = Path(__file__).with_name("static")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.runtime = WebRuntime(resolved_run_path)
        yield
        await app.state.runtime.close()

    app = FastAPI(
        title="Douyin Monitor Web",
        version="1.0.0",
        description="Linux headless web endpoint for Douyin content monitoring and video parsing.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in os.environ.get("DOUYIN_MONITOR_WEB_CORS", "").split(",") if origin.strip()] or ["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response: Response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "geolocation=(), microphone=(), camera=()")
        return response

    auth = Depends(_require_token(web_token, resolved_run_path))

    def runtime(request: Request) -> WebRuntime:
        return request.app.state.runtime

    @app.get("/", response_class=HTMLResponse)
    async def index() -> FileResponse:
        return FileResponse(static_dir / "index.html")

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "service": "douyin-monitor-web"}

    @app.get("/api/events", dependencies=[auth])
    async def events(interval: float = 2.0, rt: WebRuntime = Depends(runtime)) -> StreamingResponse:
        interval = max(1.0, min(10.0, float(interval or 2.0)))
        async def stream():
            while True:
                payload = {
                    "event": "snapshot",
                    "time": int(time.time()),
                    "dashboard": rt.dashboard.stats(),
                    "jobs": await rt.jobs.snapshot(20),
                    "download_queue": rt.download_queue_realtime(),
                    "rate_limiter": rt.observability.rate_limiter_summary(),
                }
                yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                await asyncio.sleep(interval)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/status", dependencies=[auth])
    async def status(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return {
            "run_path": rt.run_path,
            "dashboard": rt.dashboard.stats(),
            "observability": {
                "cookie_health": rt.observability.cookie_health_summary("douyin"),
                "rate_limiter": rt.observability.rate_limiter_summary(),
                "batch_jobs": rt.observability.batch_job_summary(),
                "segmented_download": rt.observability.segmented_download_summary(),
            },
        }

    @app.get("/api/accounts", dependencies=[auth])
    async def list_accounts(include_items: bool = False, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        accounts = rt.accounts(include_items=include_items)
        return {"total": len(accounts), "accounts": accounts}

    @app.post("/api/accounts", dependencies=[auth])
    async def add_account(payload: AddAccountRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        account = await rt.monitor.add_account(payload.homepage_url, payload.display_name)
        if payload.group_name:
            await rt.monitor.update_account_settings(account.account_id, group_name=payload.group_name)
        if payload.start_monitor:
            await rt.monitor.start_monitor(account.account_id)
        return {"success": True, "account": rt.account_detail(account.account_id)}

    @app.get("/api/accounts/{account_id}", dependencies=[auth])
    async def account_detail(account_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        account = rt.account_detail(account_id)
        if not account:
            raise HTTPException(status_code=404, detail="Account not found")
        return account

    @app.get("/api/accounts/{account_id}/insights", dependencies=[auth])
    async def account_insights(account_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        detail = rt.account_insights(account_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Account not found")
        return detail

    @app.patch("/api/accounts/{account_id}", dependencies=[auth])
    async def update_account(account_id: str, payload: AccountSettingsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        ok = await rt.monitor.update_account_settings(account_id, **payload.model_dump(exclude_none=True))
        if not ok:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"success": True, "account": rt.account_detail(account_id)}

    @app.delete("/api/accounts/{account_id}", dependencies=[auth])
    async def delete_account(account_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        ok = await rt.monitor.delete_account(account_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Account not found")
        return {"success": True}

    @app.post("/api/accounts/bulk/monitor", dependencies=[auth])
    async def bulk_monitor(payload: BulkIdsRequest, enabled: bool = True, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.set_monitor_enabled_batch(payload.account_ids, enabled=enabled)

    @app.post("/api/accounts/bulk/delete", dependencies=[auth])
    async def bulk_delete(payload: BulkIdsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.delete_accounts_batch(payload.account_ids)

    @app.post("/api/import/preview", dependencies=[auth])
    async def import_preview(payload: BatchImportRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.batch_import_preview(payload.text, default_group=payload.default_group, source="web")

    @app.post("/api/import/commit", dependencies=[auth])
    async def import_commit(payload: BatchImportRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.commit_batch_import(
            payload.text,
            default_group=payload.default_group,
            auto_download_policy=payload.auto_download_policy,
            notify_enabled=payload.notify_enabled,
            start_monitor=payload.start_monitor,
            source="web",
        )

    @app.post("/api/import/file/preview", dependencies=[auth])
    async def import_file_preview(file: UploadFile = File(...), default_group: str = "", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        text = await _read_upload_text(file)
        return rt.batch_import_preview(text, default_group=default_group, source=file.filename or "upload")

    @app.post("/api/import/file/commit", dependencies=[auth])
    async def import_file_commit(
        file: UploadFile = File(...),
        default_group: str = "",
        auto_download_policy: str = "none",
        notify_enabled: bool = True,
        start_monitor: bool = False,
        rt: WebRuntime = Depends(runtime),
    ) -> dict[str, Any]:
        text = await _read_upload_text(file)
        return await rt.commit_batch_import(
            text,
            default_group=default_group,
            auto_download_policy=auto_download_policy,
            notify_enabled=notify_enabled,
            start_monitor=start_monitor,
            source=file.filename or "upload",
        )

    @app.post("/api/monitor/check-all", dependencies=[auth])
    async def check_all(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        job = await rt.jobs.start("检测全部监控账号", lambda: rt.monitor.check_all_enabled())
        return {"success": True, "job": job.to_dict()}

    @app.post("/api/monitor/check-selected", dependencies=[auth])
    async def check_selected(payload: BulkIdsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        title = f"检测选中账号（{len(payload.account_ids)}）" if payload.account_ids else "检测全部监控账号"
        job = await rt.jobs.start(title, lambda: rt.check_accounts_batch(payload.account_ids))
        return {"success": True, "job": job.to_dict()}

    @app.post("/api/monitor/sync-all", dependencies=[auth])
    async def sync_all(payload: BulkIdsRequest | None = None, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        ids = payload.account_ids if payload else None
        job = await rt.jobs.start("同步账号作品", lambda: rt.monitor.sync_accounts_batch(ids))
        return {"success": True, "job": job.to_dict()}

    @app.post("/api/accounts/{account_id}/check", dependencies=[auth])
    async def check_account(account_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.check_account(account_id)

    @app.post("/api/accounts/{account_id}/sync", dependencies=[auth])
    async def sync_account(account_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.sync_account_works(account_id)

    @app.get("/api/accounts/{account_id}/items", dependencies=[auth])
    async def account_items(account_id: str, status: str = "", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        items = rt.items(account_id, status=status)
        return {"total": len(items), "items": items}

    @app.post("/api/accounts/{account_id}/items/{item_id}/download", dependencies=[auth])
    async def download_item(account_id: str, item_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.download_item(account_id, item_id)

    @app.post("/api/accounts/{account_id}/items/download", dependencies=[auth])
    async def download_items(account_id: str, payload: DownloadItemsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.monitor.download_items_batch(account_id, payload.item_ids)

    @app.get("/api/inbox/new-items", dependencies=[auth])
    async def new_items(q: str = "", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        items = rt.new_items(query=q)
        return {"total": len(items), "items": items}

    @app.post("/api/items/mark-seen", dependencies=[auth])
    async def mark_items_seen(payload: ItemPairsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.mark_items_seen([item.model_dump() for item in payload.items])

    @app.post("/api/items/download", dependencies=[auth])
    async def download_items_global(payload: ItemPairsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        job = await rt.jobs.start("Web批量下载作品", lambda: rt.download_items([item.model_dump() for item in payload.items]))
        return {"success": True, "job": job.to_dict()}

    @app.post("/api/parse", dependencies=[auth])
    async def parse_text(payload: ParseTextRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        if payload.download:
            events = []
            async for event in rt.parser.parse_text_download_stream(payload.text, rt.services.parsed_media_downloader.download, concurrency=payload.concurrency):
                events.append(parse_event_to_dict(event))
            return {"success": True, "events": events}
        result = await rt.parser.parse_text(payload.text, concurrency=payload.concurrency)
        return {
            "success": True,
            "total": result.total_count,
            "success_count": result.success_count,
            "failed_count": result.failed_count,
            "successes": [parse_event_to_dict(item) for item in result.successes],
            "failures": [parse_event_to_dict(item) for item in result.failures],
        }

    @app.post("/api/parse/download", dependencies=[auth])
    async def download_parsed_media(payload: ParsedMediaDownloadRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        from ..core.media.parser_models import ParsedVideoResult

        data = payload.item if isinstance(payload.item, dict) else {}
        image_urls = data.get("image_urls") if isinstance(data.get("image_urls"), list) else []
        watermark_image_urls = data.get("watermark_image_urls") if isinstance(data.get("watermark_image_urls"), list) else []
        item = ParsedVideoResult(
            source_url=str(data.get("source_url") or ""),
            media_type=str(data.get("media_type") or ("image" if image_urls else "video")),
            platform=str(data.get("platform") or "douyin"),
            item_id=str(data.get("item_id") or ""),
            description=str(data.get("description") or data.get("title") or ""),
            author_nickname=str(data.get("author_nickname") or ""),
            author_id=str(data.get("author_id") or ""),
            no_watermark_url=str(data.get("no_watermark_url") or ""),
            watermark_url=str(data.get("watermark_url") or ""),
            image_urls=[str(x) for x in image_urls if x],
            watermark_image_urls=[str(x) for x in watermark_image_urls if x],
            raw_data=data.get("raw_data") if isinstance(data.get("raw_data"), dict) else {},
        )
        if not item.primary_media_url:
            raise HTTPException(status_code=400, detail="解析结果中没有可下载的媒体直链")
        result = await rt.services.parsed_media_downloader.download(item)
        return {"success": bool(result.get("success")), "result": result}


    @app.post("/api/parse/stream", dependencies=[auth])
    async def parse_stream(payload: ParseTextRequest, rt: WebRuntime = Depends(runtime)) -> StreamingResponse:
        async def events():
            if payload.download:
                iterator = rt.parser.parse_text_download_stream(payload.text, rt.services.parsed_media_downloader.download, concurrency=payload.concurrency)
            else:
                iterator = rt.parser.parse_text_stream(payload.text, concurrency=payload.concurrency)
            async for event in iterator:
                yield "data: " + json.dumps(parse_event_to_dict(event), ensure_ascii=False) + "\n\n"
            yield "data: " + json.dumps({"event": "done"}, ensure_ascii=False) + "\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.get("/api/tasks", dependencies=[auth])
    async def tasks(limit: int = 80, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        records = rt.services.task_center.snapshot(limit)
        return {"total": len(records), "records": records, "web_jobs": await rt.jobs.snapshot(limit)}

    @app.get("/api/download-history", dependencies=[auth])
    async def download_history(status: str = "all", limit: int = 100, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.download_history_records(status=status, limit=limit)

    @app.get("/api/jobs", dependencies=[auth])
    async def jobs(limit: int = 80, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        items = await rt.jobs.snapshot(limit)
        return {"total": len(items), "jobs": items}

    @app.get("/api/jobs/{job_id}", dependencies=[auth])
    async def job_detail(job_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        job = await rt.jobs.detail(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        return job

    @app.post("/api/jobs/{job_id}/cancel", dependencies=[auth])
    async def cancel_job(job_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return {"success": await rt.jobs.cancel(job_id)}

    @app.get("/api/settings", dependencies=[auth])
    async def settings(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        settings_config = rt.services.settings_config
        return {"user_config": dict(settings_config.user_config), "cookies_config": dict(settings_config.cookies_config)}

    @app.patch("/api/settings", dependencies=[auth])
    async def patch_settings(payload: SettingsPatchRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        settings_config = rt.services.settings_config
        values = dict(payload.values or {})
        for key, value in values.items():
            settings_config.user_config[key] = value
        await rt.services.config_manager.save_user_config(settings_config.user_config)
        settings_config.adopt_user_config(settings_config.user_config)
        return {"success": True, "user_config": dict(settings_config.user_config)}


    @app.get("/api/diagnostics", dependencies=[auth])
    async def diagnostics(include_network: bool = False, include_douyin: bool = False, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.diagnostic_results(include_network=include_network, include_douyin=include_douyin)

    @app.post("/api/diagnostics/export", dependencies=[auth])
    async def export_diagnostics(rt: WebRuntime = Depends(runtime)) -> FileResponse:
        path = Path(rt.export_diagnostics_bundle())
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.get("/api/cookies", dependencies=[auth])
    async def cookies(platform: str = "douyin", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.cookie_management(platform)

    @app.patch("/api/cookies", dependencies=[auth])
    async def patch_cookies(payload: CookiePatchRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.update_cookie_config(payload.platform, payload.cookie_text)

    @app.post("/api/cookies/clear-health", dependencies=[auth])
    async def clear_cookie_health(platform: str = "douyin", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        store = getattr(rt.services, "cookie_health_store", None)
        cleared = store.clear(platform) if store is not None and hasattr(store, "clear") else 0
        return {"success": True, "cleared": cleared}

    @app.post("/api/cookies/disable", dependencies=[auth])
    async def disable_cookie(payload: CookieHashRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.set_cookie_disabled(payload.platform, payload.cookie_hash, True)

    @app.post("/api/cookies/enable", dependencies=[auth])
    async def enable_cookie(payload: CookieHashRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.set_cookie_disabled(payload.platform, payload.cookie_hash, False)

    @app.post("/api/cookies/delete", dependencies=[auth])
    async def delete_cookie(payload: CookieHashRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.delete_cookie(payload.platform, payload.cookie_hash)

    @app.post("/api/cookies/bulk-disable", dependencies=[auth])
    async def bulk_disable_cookies(payload: CookieBulkRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.bulk_set_cookies_disabled(payload.platform, payload.cookie_hashes, True)

    @app.post("/api/cookies/bulk-enable", dependencies=[auth])
    async def bulk_enable_cookies(payload: CookieBulkRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.bulk_set_cookies_disabled(payload.platform, payload.cookie_hashes, False)

    @app.post("/api/cookies/test", dependencies=[auth])
    async def test_cookie(payload: CookieHashRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.test_cookie(payload.platform, payload.cookie_hash)

    @app.get("/api/download-queue", dependencies=[auth])
    async def download_queue(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.download_queue_realtime()

    @app.post("/api/download-queue/{action}", dependencies=[auth])
    async def download_queue_action(action: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        queue = getattr(rt.services, "media_task_queue", None)
        if queue is None:
            return {"success": False, "reason": "下载队列不可用"}
        if action == "pause" and hasattr(queue, "pause"):
            queue.pause(); return {"success": True, "reason": "下载队列已暂停"}
        if action == "resume" and hasattr(queue, "resume"):
            queue.resume(); return {"success": True, "reason": "下载队列已继续"}
        if action == "cancel" and hasattr(queue, "cancel_all"):
            queue.cancel_all(); return {"success": True, "reason": "已取消当前下载队列"}
        raise HTTPException(status_code=400, detail="Unsupported queue action")

    @app.get("/api/download-queue/tasks", dependencies=[auth])
    async def download_queue_tasks(limit: int = 100, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.download_queue_tasks(limit=limit)

    @app.post("/api/tasks/{task_id}/cancel", dependencies=[auth])
    async def task_cancel(task_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.cancel_task_record(task_id)

    @app.post("/api/tasks/{task_id}/retry", dependencies=[auth])
    async def task_retry(task_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.retry_task_record(task_id)

    @app.get("/api/batch-jobs", dependencies=[auth])
    async def batch_jobs(limit: int = 100, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.task_center.batch_jobs_summary() | {"jobs": rt.task_center.batch_jobs(limit)}

    @app.get("/api/batch-jobs/{job_id}", dependencies=[auth])
    async def batch_job_detail(job_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        detail = rt.task_center.batch_job_detail(job_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Batch job not found")
        return detail

    @app.post("/api/batch-jobs/{job_id}/{action}", dependencies=[auth])
    async def batch_job_action(job_id: str, action: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        if action == "pause":
            return await rt.task_center.pause_batch_job(job_id)
        if action == "resume":
            return await rt.task_center.resume_batch_job(job_id)
        if action == "cancel":
            return await rt.task_center.cancel_batch_job(job_id)
        raise HTTPException(status_code=400, detail="Unsupported batch job action")

    @app.post("/api/batch-jobs/{job_id}/retry-failed", dependencies=[auth])
    async def batch_job_retry_failed(job_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        detail = rt.task_center.batch_job_detail(job_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Batch job not found")
        payload = detail.get("payload") if isinstance(detail.get("payload"), dict) else {}
        account_id = str(payload.get("account_id") or "")
        failed_ids = [str(item) for item in detail.get("failed_ids", []) if item]
        if not account_id or not failed_ids:
            return {"success": False, "reason": "当前批次没有可重试的失败作品"}
        return await rt.monitor.download_items_batch(account_id, failed_ids, title_prefix="重试失败批量任务")

    @app.get("/api/batch-jobs/{job_id}/failures", dependencies=[auth])
    async def batch_job_failures(job_id: str, page: int = 1, page_size: int = 50, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.batch_job_failures(job_id, page=page, page_size=page_size)

    @app.post("/api/batch-jobs/{job_id}/retry-category", dependencies=[auth])
    async def batch_job_retry_category(job_id: str, category: str = "all", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.retry_batch_job_category(job_id, category=category)

    @app.get("/api/media-library", dependencies=[auth])
    async def media_library(account_id: str = "", q: str = "", status: str = "all", media_type: str = "all", limit: int = 300, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.media_library(account_id=account_id, query=q, status=status, media_type=media_type, limit=limit)

    @app.get("/api/media/{account_id}/{item_id}", dependencies=[auth])
    async def media_detail(account_id: str, item_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        detail = rt.media_item_detail(account_id, item_id)
        if not detail:
            raise HTTPException(status_code=404, detail="Media item not found")
        return detail

    @app.get("/api/media/{account_id}/{item_id}/file/{index}", dependencies=[auth])
    async def media_file(account_id: str, item_id: str, index: int, rt: WebRuntime = Depends(runtime)) -> FileResponse:
        path = rt.resolve_media_file(account_id, item_id, index)
        if not path:
            raise HTTPException(status_code=404, detail="Media file not found")
        return FileResponse(path, filename=path.name)

    @app.get("/api/media/{account_id}/{item_id}/archive", dependencies=[auth])
    async def media_archive(account_id: str, item_id: str, rt: WebRuntime = Depends(runtime)) -> FileResponse:
        path = rt.create_media_archive(account_id, item_id)
        if not path:
            raise HTTPException(status_code=404, detail="没有可打包的本地媒体文件")
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.post("/api/media/{account_id}/{item_id}/mark-seen", dependencies=[auth])
    async def media_mark_seen(account_id: str, item_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.mark_items_seen([{"account_id": account_id, "item_id": item_id}])

    @app.get("/api/storage", dependencies=[auth])
    async def storage(path: str = "", q: str = "", media_filter: str = "all", sort_mode: str = "name_asc", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.storage_snapshot(path=path, query=q, media_filter=media_filter, sort_mode=sort_mode)


    @app.get("/api/storage/file", dependencies=[auth])
    async def storage_file(path: str, rt: WebRuntime = Depends(runtime)) -> FileResponse:
        resolved = rt.resolve_storage_file(path)
        if not resolved:
            raise HTTPException(status_code=404, detail="Storage media file not found")
        return FileResponse(resolved, filename=resolved.name)

    @app.get("/api/storage/stats", dependencies=[auth])
    async def storage_stats(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.storage_stats()

    @app.post("/api/storage/delete", dependencies=[auth])
    async def storage_delete(payload: StoragePathRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.delete_storage_path(payload.path)

    @app.post("/api/storage/cleanup-temp", dependencies=[auth])
    async def storage_cleanup_temp(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.cleanup_temp_files()

    @app.get("/api/storage/scan-empty", dependencies=[auth])
    async def storage_scan_empty(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.storage_scan_empty()

    @app.get("/api/storage/scan-duplicates", dependencies=[auth])
    async def storage_scan_duplicates(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.storage_scan_duplicates()

    @app.post("/api/storage/bulk-delete", dependencies=[auth])
    async def storage_bulk_delete(payload: StoragePathsRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.delete_storage_paths(payload.paths)

    @app.get("/api/logs", dependencies=[auth])
    async def logs(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.log_files()

    @app.get("/api/logs/tail", dependencies=[auth])
    async def log_tail(name: str, lines: int = 200, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.read_log_tail(name, lines=lines)

    @app.get("/api/logs/stream", dependencies=[auth])
    async def log_stream(name: str, interval: float = 2.0, lines: int = 80, rt: WebRuntime = Depends(runtime)) -> StreamingResponse:
        interval = max(1.0, min(10.0, float(interval or 2.0)))
        async def stream():
            last_content = None
            while True:
                payload = rt.read_log_tail(name, lines=lines)
                content = payload.get("content", "")
                if content != last_content:
                    yield "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"
                    last_content = content
                await asyncio.sleep(interval)
        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/logs/search", dependencies=[auth])
    async def log_search(q: str = "", level: str = "", lines: int = 500, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.search_logs(q, level, lines=lines)

    @app.get("/api/logs/download", dependencies=[auth])
    async def log_download(name: str, rt: WebRuntime = Depends(runtime)) -> FileResponse:
        path = rt.resolve_log_file(name)
        if not path:
            raise HTTPException(status_code=404, detail="Log file not found")
        return FileResponse(path, filename=path.name, media_type="text/plain")

    @app.post("/api/logs/clear", dependencies=[auth])
    async def log_clear(name: str = "", rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.clear_logs(name)

    @app.get("/api/network-risk", dependencies=[auth])
    async def network_risk(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.network_risk_summary()

    @app.get("/api/notifications", dependencies=[auth])
    async def notifications(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.notification_state()

    @app.patch("/api/notifications", dependencies=[auth])
    async def patch_notifications(payload: NotificationPatchRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.update_notification_state(payload.values)

    @app.post("/api/notifications/test", dependencies=[auth])
    async def test_notifications(payload: NotificationTestRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.test_notification(payload.channel, payload.message, allow_network=payload.allow_network)

    @app.get("/api/updates", dependencies=[auth])
    async def updates(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.update_state()

    @app.post("/api/updates/check", dependencies=[auth])
    async def check_updates(allow_network: bool = False, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.check_updates(allow_network=allow_network)

    @app.get("/api/access", dependencies=[auth])
    async def access(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.access_state()

    @app.get("/api/access/users", dependencies=[auth])
    async def access_users(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.access_users()

    @app.get("/api/access/rbac", dependencies=[auth])
    async def access_rbac(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.access_rbac_matrix()

    @app.post("/api/access/users", dependencies=[auth])
    async def access_user_create(payload: AccessUserRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.create_access_user(payload.name, payload.role)

    @app.delete("/api/access/users/{user_id}", dependencies=[auth])
    async def access_user_delete(user_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.delete_access_user(user_id)

    @app.post("/api/access/users/{user_id}/rotate", dependencies=[auth])
    async def access_user_rotate(user_id: str, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.rotate_access_user(user_id)

    @app.get("/api/backups", dependencies=[auth])
    async def list_backups(rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.list_backups()

    @app.post("/api/backups", dependencies=[auth])
    async def create_backup(full: bool = True, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.create_backup(full=full)

    @app.get("/api/backups/download", dependencies=[auth])
    async def backup_download(name: str, rt: WebRuntime = Depends(runtime)) -> FileResponse:
        path = rt.resolve_backup_file(name)
        if not path:
            raise HTTPException(status_code=404, detail="Backup file not found")
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @app.post("/api/backups/restore", dependencies=[auth])
    async def backup_restore(payload: RestoreBackupRequest, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return rt.restore_backup(payload.name, apply=payload.apply)

    @app.post("/api/backups/upload-restore", dependencies=[auth])
    async def backup_upload_restore(file: UploadFile = File(...), apply: bool = False, rt: WebRuntime = Depends(runtime)) -> dict[str, Any]:
        return await rt.restore_uploaded_backup(file, apply=apply)

    app.mount("/static", StaticFiles(directory=static_dir), name="static")
    return app


async def _read_upload_text(file: UploadFile, *, max_bytes: int = 2 * 1024 * 1024) -> str:
    name = str(file.filename or "")
    suffix = Path(name).suffix.lower()
    if suffix not in {".txt", ".csv"}:
        raise HTTPException(status_code=400, detail="当前支持 TXT / CSV 文件导入")
    raw = await file.read(max_bytes + 1)
    if len(raw) > max_bytes:
        raise HTTPException(status_code=400, detail="导入文件过大，请控制在 2MB 内")
    for encoding in ("utf-8-sig", "utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def main() -> None:
    import uvicorn

    host = os.environ.get("DOUYIN_MONITOR_WEB_HOST", "0.0.0.0")
    port = int(os.environ.get("DOUYIN_MONITOR_WEB_PORT", "8080"))
    uvicorn.run("app.web.server:create_app", host=host, port=port, factory=True, reload=False)


if __name__ == "__main__":
    main()
