from __future__ import annotations

import importlib
import sys
import time
from dataclasses import dataclass
from typing import Any

from ..parser import build_douyin_parser_backend, parser_backend_registry
from ...utils.logger import logger


@dataclass(slots=True)
class HealthCheckResult:
    name: str
    status: str
    detail: str
    next_step: str = ""


class HealthCheckService:
    """Headless health checks used by the desktop UI and unit tests."""

    def __init__(self, services: Any):
        self.services = services

    async def check_sqlite(self) -> HealthCheckResult:
        store = getattr(self.services, "sqlite_store", None)
        if store is None:
            return HealthCheckResult("SQLite", "异常", "SQLiteStore 未初始化。", "重启应用；若仍失败请导出诊断包。")
        try:
            start = time.monotonic()
            store.ensure_schema()
            version = store.get_metadata("schema_version", "unknown") if hasattr(store, "get_metadata") else "unknown"
            elapsed_ms = (time.monotonic() - start) * 1000
            return HealthCheckResult("SQLite", "正常", f"数据库可读写，schema_version={version}，耗时 {elapsed_ms:.0f} ms。")
        except Exception as exc:
            logger.debug(f"SQLite health check failed: {exc}")
            return HealthCheckResult("SQLite", "异常", f"数据库初始化或读写失败：{exc}", "检查 data 目录权限，必要时备份后重建数据库。")

    async def check_parser_backend(self) -> HealthCheckResult:
        settings = getattr(self.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        backend_kind = str(user_config.get("douyin_parser_backend") or "internal").strip().lower()
        external_base_url = str(user_config.get("douyin_external_api_base_url") or "")
        video_parser = getattr(self.services, "video_parser", None)
        try:
            backend = build_douyin_parser_backend(
                backend_kind,
                video_parser=video_parser,
                external_base_url=external_base_url,
            )
            health = await backend.health_check()
            caps = health.capabilities or backend.capabilities()
            status = "正常" if health.ok else "异常"
            capability_labels = []
            if caps.parse_url or caps.single_url:
                capability_labels.append("单链接")
            if caps.profile_contents:
                capability_labels.append("主页作品")
            if caps.gallery:
                capability_labels.append("图集")
            if caps.video:
                capability_labels.append("视频")
            detail = f"后端 {backend.name}；{health.detail}；能力：{', '.join(capability_labels) or '未声明'}。"
            next_step = "检查解析器初始化、Cookie、代理或外部 API 地址。" if not health.ok else ""
            return HealthCheckResult("解析器后端", status, detail, next_step)
        except Exception as exc:
            logger.debug(f"parser backend health check failed: {exc}")
            return HealthCheckResult("解析器后端", "异常", f"后端初始化失败：{exc}", "检查解析器配置和依赖。")

    async def check_parser_registry(self) -> HealthCheckResult:
        try:
            descriptors = parser_backend_registry.descriptors(platform="douyin")
            keys = [item.key for item in descriptors]
            required = {"douyin_internal", "douyin_external", "douyin_fallback"}
            missing = sorted(required.difference(keys))
            if missing:
                return HealthCheckResult("解析器注册中心", "异常", f"缺少注册项：{', '.join(missing)}。", "检查 app.core.parser.douyin_backends 导入和注册逻辑。")
            if not descriptors:
                return HealthCheckResult("解析器注册中心", "异常", "没有注册任何抖音解析器。")
            details = []
            video_parser = getattr(self.services, "video_parser", None)
            external_base_url = str(
                getattr(getattr(self.services, "settings_config", None), "user_config", {}).get("douyin_external_api_base_url")
                or ""
            )
            for health in await parser_backend_registry.health_check_all(
                platform="douyin",
                video_parser=video_parser,
                external_base_url=external_base_url,
            ):
                state = "ok" if health.ok else "bad"
                details.append(f"{health.backend}:{state}")
            status = "正常" if any(item.endswith(":ok") for item in details) else "可用"
            return HealthCheckResult("解析器注册中心", status, f"已注册：{', '.join(keys)}；健康：{', '.join(details)}。")
        except Exception as exc:
            logger.debug(f"parser registry health check failed: {exc}")
            return HealthCheckResult("解析器注册中心", "异常", f"注册中心检测失败：{exc}", "检查解析器注册模块是否完整。")

    async def check_runtime_dependencies(self) -> HealthCheckResult:
        required = ["flet", "flet_video", "httpx", "yaml", "loguru", "PIL", "qrcode", "pydantic", "gmssl", "browser_cookie3", "tenacity", "rich"]
        missing: list[str] = []
        for module in required:
            try:
                importlib.import_module(module)
            except Exception as exc:
                missing.append(f"{module}({exc})")
        version = sys.version_info
        notes: list[str] = []
        if version < (3, 10):
            notes.append("Python 版本过低，要求 >=3.10")
        elif version >= (3, 13):
            notes.append("Python 3.13 尚非桌面运行验证版本，建议 3.10-3.12")
        if missing or notes:
            detail = "；".join(notes + (["缺少依赖：" + ", ".join(missing)] if missing else []))
            return HealthCheckResult("运行依赖", "异常" if missing or version < (3, 10) else "可用", detail, "按 requirements.txt 重新安装依赖。")
        return HealthCheckResult("运行依赖", "正常", f"Python {version.major}.{version.minor}.{version.micro}，核心依赖可导入。")
