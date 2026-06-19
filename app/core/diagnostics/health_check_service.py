from __future__ import annotations

import importlib
import os
import platform
import shutil
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ..media.cookie_utils import cookie_looks_usable, sanitize_cookie_header
from ..parser import build_douyin_parser_backend, parser_backend_registry


@dataclass(slots=True)
class HealthCheckResult:
    name: str
    status: str
    detail: str
    next_step: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


class HealthCheckService:
    def __init__(self, services: Any):
        self.services = services

    async def run_core_checks(self) -> list[HealthCheckResult]:
        checks = [
            self.check_python_runtime,
            self.check_dependencies,
            self.check_config,
            self.check_sqlite,
            self.check_cookie,
            self.check_parser_backend,
            self.check_parser_registry,
            self.check_storage_permission,
            self.check_disk_space,
            self.check_task_queue,
        ]
        results: list[HealthCheckResult] = []
        for check in checks:
            try:
                results.append(await check())
            except Exception as exc:
                results.append(HealthCheckResult("未知检测", "异常", str(exc), "请导出诊断包后查看日志。"))
        return results

    async def check_python_runtime(self) -> HealthCheckResult:
        version = sys.version_info
        detail = f"Python {version.major}.{version.minor}.{version.micro}；{platform.platform()}"
        if version < (3, 10):
            return HealthCheckResult("运行环境", "异常", detail, "建议使用 Python 3.10 或更高版本。")
        if version >= (3, 12):
            return HealthCheckResult("运行环境", "可用", detail, "如遇依赖兼容问题，优先使用 Python 3.11。")
        return HealthCheckResult("运行环境", "正常", detail)

    async def check_dependencies(self) -> HealthCheckResult:
        required = ["flet", "httpx", "yaml", "loguru"]
        missing = []
        for name in required:
            try:
                importlib.import_module(name)
            except Exception:
                missing.append(name)
        if missing:
            return HealthCheckResult("依赖", "异常", f"缺少依赖：{', '.join(missing)}", "重新安装 requirements.txt 后再启动。")
        return HealthCheckResult("依赖", "正常", "核心依赖可导入。")

    async def check_config(self) -> HealthCheckResult:
        settings = getattr(self.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        backend = str(user_config.get("douyin_parser_backend") or "internal")
        parallel = user_config.get("max_parallel_downloads")
        return HealthCheckResult("配置", "正常", f"解析器 backend={backend}；下载并发={parallel}。")

    async def check_sqlite(self) -> HealthCheckResult:
        store = getattr(self.services, "sqlite_store", None)
        if store is None:
            return HealthCheckResult("SQLite", "异常", "SQLite 存储未初始化。", "重启应用；若仍失败请检查写入权限。")
        try:
            store.ensure_schema()
            schema_version = store.get_metadata("schema_version", "")
            accounts = store.monitor_account_count()
            tasks = store.task_record_count()
            downloads = store.download_record_count()
            recoverable = store.download_record_count(["pending", "running", "recoverable", "failed", "cancelled"])
            return HealthCheckResult("SQLite", "正常", f"schema={schema_version}；账号={accounts}；任务={tasks}；下载记录={downloads}；可恢复={recoverable}；路径={store.path}")
        except Exception as exc:
            return HealthCheckResult("SQLite", "异常", f"数据库检查失败：{exc}", "备份 config/ 与 data/ 后重启或运行迁移脚本。")

    async def check_cookie(self) -> HealthCheckResult:
        settings = getattr(self.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) if settings is not None else {}
        douyin_cookie = sanitize_cookie_header(str(cookies.get("douyin_cookie") or ""))
        tiktok_cookie = sanitize_cookie_header(str(cookies.get("tiktok_cookie") or ""))
        douyin_ok = cookie_looks_usable(douyin_cookie)
        tiktok_ok = cookie_looks_usable(tiktok_cookie)
        if douyin_ok and tiktok_ok:
            return HealthCheckResult("Cookie", "正常", "抖音和 TikTok Cookie 格式看起来有效。")
        if douyin_ok:
            return HealthCheckResult("Cookie", "可用", "抖音 Cookie 格式看起来有效；TikTok Cookie 未配置或格式较短。")
        return HealthCheckResult("Cookie", "需配置", "未配置有效抖音 Cookie。", "打开设置页填写 Cookie 后点击有效性测试。")

    async def check_parser_backend(self) -> HealthCheckResult:
        settings = getattr(self.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        kind = str(user_config.get("douyin_parser_backend") or "internal")
        external_base_url = str(user_config.get("douyin_external_api_base_url") or "")
        backend = build_douyin_parser_backend(kind, video_parser=getattr(self.services, "video_parser", None), external_base_url=external_base_url)
        health = await backend.health_check()
        caps = backend.capabilities()
        cap_text = (
            f"parse_url={caps.parse_url}, profile={caps.profile_contents}, "
            f"video={caps.video}, gallery={caps.gallery}, tiktok={caps.tiktok}"
        )
        return HealthCheckResult("解析器后端", "正常" if health.ok else "异常", f"{health.detail or f'{backend.platform}:{backend.name}'}；能力：{cap_text}")

    async def check_parser_registry(self) -> HealthCheckResult:
        descriptors = parser_backend_registry.descriptors(platform="douyin")
        if not descriptors:
            return HealthCheckResult("解析器注册中心", "异常", "没有注册 Douyin 解析器后端。", "检查 app/core/parser/douyin_backends.py 是否正常导入。")
        labels = []
        for descriptor in descriptors:
            caps = descriptor.capabilities
            labels.append(f"{descriptor.key}[parse={caps.parse_url},profile={caps.profile_contents}]")
        return HealthCheckResult("解析器注册中心", "正常", "；".join(labels))

    async def check_storage_permission(self) -> HealthCheckResult:
        path = self.storage_dir()
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(prefix=".health_", suffix=".tmp", dir=path, delete=False) as temp:
                temp.write(b"ok")
                temp_path = temp.name
            os.remove(temp_path)
            return HealthCheckResult("保存目录权限", "正常", f"可写入：{path}")
        except Exception as exc:
            return HealthCheckResult("保存目录权限", "异常", f"不可写入：{path}；{exc}", "在设置页选择有写入权限的下载目录。")

    async def check_disk_space(self) -> HealthCheckResult:
        path = self.storage_dir()
        try:
            Path(path).mkdir(parents=True, exist_ok=True)
            usage = shutil.disk_usage(path)
        except Exception as exc:
            return HealthCheckResult("磁盘空间", "异常", f"无法读取保存目录空间：{path}；{exc}", "在设置页选择可访问的保存目录。")
        free_gb = usage.free / 1024 / 1024 / 1024
        total_gb = usage.total / 1024 / 1024 / 1024
        detail = f"保存目录：{path}；剩余 {free_gb:.1f} GB / 总计 {total_gb:.1f} GB。"
        if free_gb < 1:
            return HealthCheckResult("磁盘空间", "异常", detail, "空间不足会导致下载失败，请清理磁盘或更换保存目录。")
        if free_gb < 5:
            return HealthCheckResult("磁盘空间", "可用", detail, "剩余空间偏低，批量下载前建议清理或更换目录。")
        return HealthCheckResult("磁盘空间", "正常", detail)

    async def check_task_queue(self) -> HealthCheckResult:
        queue = getattr(self.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return HealthCheckResult("下载队列", "异常", "下载队列未初始化。")
        return HealthCheckResult("下载队列", "正常", f"队列状态：{queue.snapshot()}")

    def storage_dir(self) -> str:
        settings = getattr(self.services, "settings_config", None)
        configured = ""
        if settings is not None:
            configured = str(getattr(settings, "user_config", {}).get("douyin_content_download_path") or "")
        return configured or os.path.join(self.services.run_path, "downloads")
