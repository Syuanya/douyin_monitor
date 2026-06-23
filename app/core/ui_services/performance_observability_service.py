from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class CookieHealthRow:
    platform: str
    cookie_hash: str
    status: str
    score: float
    success: float
    failure: float
    empty: float
    cooldown_seconds: float
    disabled_seconds: float
    last_reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "cookie_hash": self.cookie_hash,
            "status": self.status,
            "score": self.score,
            "success": self.success,
            "failure": self.failure,
            "empty": self.empty,
            "cooldown_seconds": self.cooldown_seconds,
            "disabled_seconds": self.disabled_seconds,
            "last_reason": self.last_reason,
        }


class PerformanceObservabilityService:
    """UI-independent observability projection for Cookie, limiter and batch jobs."""

    def __init__(self, app: Any):
        self.app = app

    def cookie_health_rows(self, platform: str = "douyin") -> list[dict[str, Any]]:
        store = getattr(getattr(self.app, "services", None), "cookie_health_store", None)
        if store is None or not hasattr(store, "snapshot"):
            return []
        now = time.time()
        rows: list[CookieHealthRow] = []
        try:
            snapshot = store.snapshot(platform)
        except Exception:
            snapshot = {}
        for cookie_hash, state in snapshot.items():
            try:
                success = float(state.get("success") or 0.0)
                failure = float(state.get("failure") or 0.0)
                empty = float(state.get("empty") or 0.0)
                cooldown_seconds = max(0.0, float(state.get("cooldown_until") or 0.0) - now)
                disabled_seconds = max(0.0, float(state.get("disabled_until") or 0.0) - now)
            except (TypeError, ValueError):
                success = failure = empty = cooldown_seconds = disabled_seconds = 0.0
            score = 1.0 + success * 1.5 - failure * 2.0 - empty * 3.0
            if disabled_seconds > 0:
                status = "disabled"
            elif cooldown_seconds > 0:
                status = "cooldown"
            elif failure >= 3 or empty >= 2:
                status = "degraded"
            else:
                status = "healthy"
            rows.append(
                CookieHealthRow(
                    platform=str(state.get("platform") or platform),
                    cookie_hash=str(cookie_hash),
                    status=status,
                    score=round(score, 2),
                    success=success,
                    failure=failure,
                    empty=empty,
                    cooldown_seconds=round(cooldown_seconds, 1),
                    disabled_seconds=round(disabled_seconds, 1),
                    last_reason=str(state.get("last_reason") or ""),
                )
            )
        rows.sort(key=lambda row: (row.status != "healthy", -row.score, row.cookie_hash))
        return [row.to_dict() for row in rows]

    def cookie_health_summary(self, platform: str = "douyin") -> dict[str, Any]:
        rows = self.cookie_health_rows(platform)
        counts = {"healthy": 0, "degraded": 0, "cooldown": 0, "disabled": 0}
        for row in rows:
            counts[str(row.get("status") or "degraded")] = counts.get(str(row.get("status") or "degraded"), 0) + 1
        return {"total": len(rows), **counts, "rows": rows}

    def clear_cookie_health(self, platform: str = "douyin") -> int:
        store = getattr(getattr(self.app, "services", None), "cookie_health_store", None)
        if store is None or not hasattr(store, "clear"):
            return 0
        return int(store.clear(platform=platform) or 0)

    def rate_limiter_summary(self) -> dict[str, Any]:
        limiter = getattr(getattr(self.app, "services", None), "douyin_request_limiter", None)
        if limiter is None or not hasattr(limiter, "snapshot"):
            return {"available": False}
        try:
            snapshot = limiter.snapshot()
            scopes = dict(getattr(snapshot, "scopes", {}) or {})
            settings = getattr(getattr(self.app, "services", None), "settings_config", None)
            user_config = getattr(settings, "user_config", {}) or {}
            bypass = bool(user_config.get("development_bypass_risk_controls_enabled", False))
            global_enabled = bool(user_config.get("global_request_limiter_enabled", True))
            risk_backoff_enabled = bool(user_config.get("risk_backoff_enabled", True))
            return {
                "available": True,
                "enabled": bool(global_enabled and not bypass),
                "development_bypass": bypass,
                "risk_backoff_enabled": bool(risk_backoff_enabled and not bypass),
                "global_delay": round(float(getattr(snapshot, "global_delay", 0.0) or 0.0), 2),
                "wait_count": int(getattr(snapshot, "wait_count", 0) or 0),
                "failure_count": int(getattr(snapshot, "failure_count", 0) or 0),
                "scope_count": len(scopes),
                "scopes": {key: round(float(value), 3) for key, value in scopes.items()},
            }
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    def batch_job_summary(self) -> dict[str, Any]:
        store = getattr(getattr(self.app, "services", None), "batch_job_store", None)
        if store is None or not hasattr(store, "snapshot"):
            return {"available": False, "jobs": []}
        jobs = store.snapshot(limit=100)
        counts: dict[str, int] = {}
        for job in jobs:
            counts[str(job.get("status") or "unknown")] = counts.get(str(job.get("status") or "unknown"), 0) + 1
        return {"available": True, "total": len(jobs), "counts": counts, "jobs": jobs}

    def segmented_download_summary(self) -> dict[str, Any]:
        try:
            from ..media.resumable_download import segmented_download_snapshot

            return segmented_download_snapshot()
        except Exception as exc:
            return {"available": False, "reason": str(exc)}

    def compact_text(self) -> str:
        cookie = self.cookie_health_summary("douyin")
        limiter = self.rate_limiter_summary()
        batches = self.batch_job_summary()
        segmented = self.segmented_download_summary()
        return (
            f"Cookie：{cookie.get('healthy', 0)} 正常 / {cookie.get('cooldown', 0)} 冷却 / {cookie.get('disabled', 0)} 禁用；"
            f"限速等待 {limiter.get('wait_count', 0)} 次，退避 {limiter.get('global_delay', 0)}s；"
            f"批任务 {batches.get('total', 0)} 个；"
            f"分片黑名单 host {segmented.get('blacklisted_hosts', 0)} 个"
        )
