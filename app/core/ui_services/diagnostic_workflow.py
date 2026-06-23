from __future__ import annotations

import importlib
import os
import shutil
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx

from ..media.cookie_utils import cookie_looks_usable, sanitize_cookie_header


@dataclass(slots=True)
class HealthCheckResult:
    name: str
    status: str
    detail: str
    next_step: str = ""


class DiagnosticWorkflow:
    """Runs health checks without depending on Flet controls."""

    def __init__(self, app: Any):
        self.app = app

    async def check_python_runtime(self) -> HealthCheckResult:
        version = sys.version_info
        detail = f"Python {version.major}.{version.minor}.{version.micro}，可执行文件：{sys.executable}"
        if version < (3, 10):
            return HealthCheckResult("运行环境", "异常", detail, "建议使用 Python 3.10 或 3.11 运行。")
        if version >= (3, 12):
            return HealthCheckResult("运行环境", "可用", detail, "如遇依赖兼容问题，优先使用 Python 3.11。")
        return HealthCheckResult("运行环境", "正常", detail)

    async def check_dependencies(self) -> HealthCheckResult:
        required = ["flet", "httpx", "yaml", "crawlers.utils.utils"]
        missing = []
        for name in required:
            try:
                importlib.import_module(name)
            except Exception:
                missing.append(name)
        if missing:
            return HealthCheckResult("依赖", "异常", f"缺少依赖：{', '.join(missing)}", "重新安装依赖后再启动。")
        return HealthCheckResult("依赖", "正常", "核心依赖可导入。")

    async def check_sqlite(self) -> HealthCheckResult:
        service = getattr(self.app.services, "health_check_service", None)
        if service is None:
            return HealthCheckResult("SQLite", "异常", "健康检查服务未初始化。", "重启应用；若仍失败请导出诊断包。")
        result = await service.check_sqlite()
        return HealthCheckResult(result.name, result.status, result.detail, result.next_step)

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

    async def check_cookie(self) -> HealthCheckResult:
        settings = getattr(self.app.services, "settings_config", None)
        cookies = getattr(settings, "cookies_config", {}) or {}
        raw_douyin_cookie = str(cookies.get("douyin_cookie") or "").strip()
        raw_tiktok_cookie = str(cookies.get("tiktok_cookie") or "").strip()
        douyin_cookie = sanitize_cookie_header(raw_douyin_cookie)
        tiktok_cookie = sanitize_cookie_header(raw_tiktok_cookie)
        douyin_ok = cookie_looks_usable(douyin_cookie)
        tiktok_ok = cookie_looks_usable(tiktok_cookie)
        cleaned = raw_douyin_cookie != douyin_cookie or raw_tiktok_cookie != tiktok_cookie
        if douyin_ok and tiktok_ok:
            detail = "抖音和 TikTok Cookie 已配置，格式看起来有效。"
            if cleaned:
                detail += " 已忽略无效 Cookie 片段。"
            return HealthCheckResult("Cookie", "正常", detail)
        if douyin_ok:
            detail = "抖音 Cookie 格式看起来有效，TikTok Cookie 为空或格式较短。"
            if cleaned:
                detail += " 已忽略无效 Cookie 片段。"
            return HealthCheckResult("Cookie", "可用", detail, "如需解析 TikTok，请在设置页补充 TikTok Cookie。")
        if raw_douyin_cookie:
            return HealthCheckResult("Cookie", "异常", "抖音 Cookie 已填写，但清洗后格式仍过短或缺少键值对。", "请重新复制完整 Cookie，并在设置页点击 Cookie 测试。")
        return HealthCheckResult("Cookie", "需配置", "未配置抖音 Cookie。", "打开设置页填写 Cookie 后点击有效性测试。")

    async def check_network(self) -> HealthCheckResult:
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0), proxy=self.proxy_url()) as client:
                response = await client.get("https://www.baidu.com")
            if response.status_code < 500:
                return HealthCheckResult("网络", "正常", f"基础网络可访问：HTTP {response.status_code}。")
            return HealthCheckResult("网络", "异常", f"基础网络返回 HTTP {response.status_code}。", "检查本机网络或代理设置。")
        except Exception as exc:
            return HealthCheckResult("网络", "异常", f"基础网络访问失败：{exc}", "检查代理、防火墙或网络连接。")

    async def check_proxy(self) -> HealthCheckResult:
        proxy = self.proxy_url()
        if not proxy:
            return HealthCheckResult("代理", "未启用", "当前未启用代理。")
        try:
            start = time.monotonic()
            async with httpx.AsyncClient(timeout=httpx.Timeout(6.0), proxy=proxy) as client:
                response = await client.get("https://www.baidu.com")
            elapsed = (time.monotonic() - start) * 1000
            return HealthCheckResult("代理", "正常" if response.status_code < 500 else "异常", f"代理访问 HTTP {response.status_code}，耗时 {elapsed:.0f} ms。")
        except Exception as exc:
            return HealthCheckResult("代理", "异常", f"代理连通失败：{exc}", "检查代理地址、端口和本机代理程序。")

    async def check_douyin_access(self) -> HealthCheckResult:
        try:
            headers = {"User-Agent": "Mozilla/5.0"}
            settings = getattr(self.app.services, "settings_config", None)
            cookie = sanitize_cookie_header(str((getattr(settings, "cookies_config", {}) or {}).get("douyin_cookie") or ""))
            if cookie:
                headers["Cookie"] = cookie
            async with httpx.AsyncClient(timeout=httpx.Timeout(6.0), follow_redirects=True, proxy=self.proxy_url()) as client:
                response = await client.get("https://www.douyin.com", headers=headers)
            if response.status_code < 400:
                return HealthCheckResult("抖音访问", "正常", f"抖音首页可访问：HTTP {response.status_code}。")
            return HealthCheckResult("抖音访问", "异常", f"抖音首页返回 HTTP {response.status_code}。", "检查代理地区、Cookie 或稍后重试。")
        except Exception as exc:
            return HealthCheckResult("抖音访问", "异常", f"抖音访问失败：{exc}", "检查网络/代理，必要时更新 Cookie。")

    async def check_parser(self) -> HealthCheckResult:
        parser = getattr(self.app.services, "video_parser", None)
        if parser is None:
            return HealthCheckResult("解析器", "异常", "解析器服务未初始化。", "重启应用，若仍失败请导出诊断包。")
        missing = [name for name in ("extract_urls", "parse_url", "update_cookie") if not hasattr(parser, name)]
        if missing:
            return HealthCheckResult("解析器", "异常", f"解析器缺少接口：{', '.join(missing)}。", "检查 Douyin_TikTok_Download_API 依赖整合是否完整。")
        try:
            urls = list(parser.extract_urls("测试链接 https://v.douyin.com/test123/"))
        except Exception as exc:
            return HealthCheckResult("解析器", "异常", f"解析器链接提取失败：{exc}", "请检查解析器服务初始化日志。")
        if not urls:
            return HealthCheckResult("解析器", "异常", "解析器未能从文本中提取分享链接。", "请检查解析器版本或重新安装依赖。")
        return HealthCheckResult("解析器", "正常", "内置解析器接口完整，链接提取正常。")

    async def check_parser_backend(self) -> HealthCheckResult:
        service = getattr(self.app.services, "health_check_service", None)
        if service is None:
            return HealthCheckResult("解析器后端", "异常", "健康检查服务未初始化。")
        result = await service.check_parser_backend()
        return HealthCheckResult(result.name, result.status, result.detail, result.next_step)

    async def check_parser_registry(self) -> HealthCheckResult:
        service = getattr(self.app.services, "health_check_service", None)
        if service is None:
            return HealthCheckResult("解析器注册中心", "异常", "健康检查服务未初始化。")
        result = await service.check_parser_registry()
        return HealthCheckResult(result.name, result.status, result.detail, result.next_step)

    async def check_parser_latency(self) -> HealthCheckResult:
        parser = getattr(self.app.services, "video_parser", None)
        if parser is None or not hasattr(parser, "extract_urls"):
            return HealthCheckResult("解析器延迟", "异常", "解析器服务未初始化。")
        start = time.monotonic()
        try:
            list(parser.extract_urls("https://v.douyin.com/test123/"))
            elapsed = (time.monotonic() - start) * 1000
            return HealthCheckResult("解析器延迟", "正常", f"本地链接提取耗时 {elapsed:.0f} ms。")
        except Exception as exc:
            return HealthCheckResult("解析器延迟", "异常", f"链接提取耗时检测失败：{exc}")

    async def check_download_strategy(self) -> HealthCheckResult:
        settings = getattr(self.app.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        preset = str(user_config.get("download_strategy_preset") or "standard")
        parallel = self.safe_int_config(user_config, "max_parallel_downloads", 2, minimum=1, maximum=16)
        retry = self.safe_int_config(user_config, "media_download_retry_count", 1, minimum=0, maximum=5)
        parse_concurrency = self.safe_int_config(user_config, "video_parse_concurrency", 4, minimum=1, maximum=16)
        detail = f"策略 {preset}；下载并发 {parallel}；解析并发 {parse_concurrency}；失败重试 {retry}。"
        if parallel > 8 or parse_concurrency > 12:
            return HealthCheckResult("下载策略", "可用", detail, "并发偏高，长时间运行或弱网环境建议切换到标准/保守模式。")
        if retry > 3:
            return HealthCheckResult("下载策略", "可用", detail, "重试次数偏高，可能延长失败任务占用队列的时间。")
        return HealthCheckResult("下载策略", "正常", detail)

    @staticmethod
    def safe_int_config(config: dict, key: str, default: int, minimum: int, maximum: int) -> int:
        try:
            value = int(config.get(key, default) or default)
        except (TypeError, ValueError):
            value = default
        return max(minimum, min(maximum, value))

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

    async def check_temp_residue(self) -> HealthCheckResult:
        root = Path(self.storage_dir())
        count = 0
        try:
            for path in root.rglob("*"):
                if path.is_file() and (path.suffix in {".tmp", ".download", ".part"} or path.name.endswith((".tmp", ".download", ".part"))):
                    count += 1
        except Exception as exc:
            return HealthCheckResult("临时文件", "异常", f"扫描失败：{exc}")
        if count:
            return HealthCheckResult("临时文件", "可用", f"发现 {count} 个临时下载残留。", "可在存储页点击清理按钮释放空间。")
        return HealthCheckResult("临时文件", "正常", "未发现临时下载残留。")

    async def check_task_queue(self) -> HealthCheckResult:
        queue = getattr(self.app.services, "media_task_queue", None)
        if queue is None or not hasattr(queue, "snapshot"):
            return HealthCheckResult("下载队列", "异常", "下载队列未初始化。")
        snapshot = queue.snapshot()
        return HealthCheckResult("下载队列", "正常", f"队列状态：{snapshot}")


    async def check_cookie_health_observability(self) -> HealthCheckResult:
        try:
            from .performance_observability_service import PerformanceObservabilityService

            summary = PerformanceObservabilityService(self.app).cookie_health_summary("douyin")
            detail = (
                f"Cookie 健康记录 {summary.get('total', 0)} 条；"
                f"正常 {summary.get('healthy', 0)}，降级 {summary.get('degraded', 0)}，"
                f"冷却 {summary.get('cooldown', 0)}，禁用 {summary.get('disabled', 0)}。"
            )
            if int(summary.get('disabled', 0) or 0) > 0 or int(summary.get('cooldown', 0) or 0) > 0:
                return HealthCheckResult("Cookie 健康度", "可用", detail, "异常 Cookie 会自动冷却；可在设置页清理健康记录。")
            return HealthCheckResult("Cookie 健康度", "正常", detail)
        except Exception as exc:
            return HealthCheckResult("Cookie 健康度", "异常", f"读取 Cookie 健康状态失败：{exc}")

    async def check_rate_limiter_observability(self) -> HealthCheckResult:
        try:
            from .performance_observability_service import PerformanceObservabilityService

            summary = PerformanceObservabilityService(self.app).rate_limiter_summary()
            if not summary.get("available"):
                return HealthCheckResult("全局限速器", "异常", str(summary.get("reason") or "限速器不可用"))
            detail = f"等待 {summary.get('wait_count', 0)} 次；风控退避 {summary.get('global_delay', 0)} 秒；scope {summary.get('scope_count', 0)} 个。"
            if float(summary.get('global_delay', 0) or 0) > 0:
                return HealthCheckResult("全局限速器", "可用", detail, "当前处于风控退避，解析/监控会主动降速。")
            return HealthCheckResult("全局限速器", "正常", detail)
        except Exception as exc:
            return HealthCheckResult("全局限速器", "异常", f"读取限速器状态失败：{exc}")

    async def check_batch_jobs(self) -> HealthCheckResult:
        try:
            from .performance_observability_service import PerformanceObservabilityService

            summary = PerformanceObservabilityService(self.app).batch_job_summary()
            if not summary.get("available"):
                return HealthCheckResult("批量任务", "异常", "批量任务存储不可用。")
            counts = summary.get("counts", {}) if isinstance(summary.get("counts"), dict) else {}
            detail = f"批量任务 {summary.get('total', 0)} 个；状态：{counts}"
            if counts.get("failed") or counts.get("paused"):
                return HealthCheckResult("批量任务", "可用", detail, "任务中心可查看批次详情、恢复或取消未完成批次。")
            return HealthCheckResult("批量任务", "正常", detail)
        except Exception as exc:
            return HealthCheckResult("批量任务", "异常", f"读取批量任务失败：{exc}")

    async def check_segmented_download(self) -> HealthCheckResult:
        try:
            from .performance_observability_service import PerformanceObservabilityService

            summary = PerformanceObservabilityService(self.app).segmented_download_summary()
            detail = f"Range 黑名单 host {summary.get('blacklisted_hosts', 0)} 个；当前分片任务 {summary.get('active_segments', 0)} 个。"
            if int(summary.get('blacklisted_hosts', 0) or 0) > 0:
                return HealthCheckResult("分片下载", "可用", detail, "部分 CDN Range 不稳定，已自动回退普通下载。")
            return HealthCheckResult("分片下载", "正常", detail)
        except Exception as exc:
            return HealthCheckResult("分片下载", "异常", f"读取分片状态失败：{exc}")

    def storage_dir(self) -> str:
        settings = getattr(self.app.services, "settings_config", None)
        configured = ""
        if settings is not None:
            configured = str(getattr(settings, "user_config", {}).get("douyin_content_download_path") or "")
        return configured or os.path.join(self.app.services.run_path, "downloads")

    def proxy_url(self) -> str | None:
        settings = getattr(self.app.services, "settings_config", None)
        user_config = getattr(settings, "user_config", {}) if settings is not None else {}
        if not user_config.get("enable_proxy"):
            return None
        proxy = str(user_config.get("proxy_address") or "").strip()
        return proxy or None
