from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _read_lines(path: str) -> list[str]:
    if not path:
        return []
    file = Path(path)
    if not file.exists():
        return []
    return [line.strip() for line in file.read_text(encoding="utf-8").splitlines() if line.strip() and not line.strip().startswith("#")]


async def _run_parse_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.application.service_container import DouyinMonitorServices

    services = DouyinMonitorServices(str(ROOT))
    parser = services.video_parser
    urls = _read_lines(args.urls_file)
    if not urls:
        return {"kind": "parse", "skipped": True, "reason": "未提供 urls 文件或文件为空"}
    if not args.allow_network:
        extracted = parser.extract_urls("\n".join(urls))
        return {"kind": "parse", "dry_run": True, "input": len(urls), "extracted": len(extracted), "network": False}

    durations: list[float] = []
    success = failed = 0
    sem = asyncio.Semaphore(max(1, args.concurrency))

    async def parse_one(url: str) -> None:
        nonlocal success, failed
        start = time.monotonic()
        async with sem:
            try:
                await parser.parse_url(url)
                success += 1
            except Exception:
                failed += 1
        durations.append(time.monotonic() - start)

    await asyncio.gather(*(parse_one(url) for url in urls[: args.limit]))
    await services.download_http_client_pool.aclose()
    return _timing_summary("parse", len(urls[: args.limit]), success, failed, durations)


async def _run_monitor_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    from app.core.application.service_container import DouyinMonitorServices

    services = DouyinMonitorServices(str(ROOT))
    manager = services.douyin_content_monitor
    accounts = list(getattr(manager, "_accounts", []) or [])
    enabled = [account for account in accounts if getattr(account, "enabled", True)]
    if not args.allow_network:
        return {"kind": "monitor", "dry_run": True, "accounts": len(accounts), "enabled": len(enabled), "network": False}
    start = time.monotonic()
    result = await manager.check_all_enabled()
    await services.download_http_client_pool.aclose()
    return {"kind": "monitor", "elapsed": round(time.monotonic() - start, 3), "result": result}


def _timing_summary(kind: str, total: int, success: int, failed: int, durations: list[float]) -> dict[str, Any]:
    if not durations:
        return {"kind": kind, "total": total, "success": success, "failed": failed}
    return {
        "kind": kind,
        "total": total,
        "success": success,
        "failed": failed,
        "avg_ms": round(statistics.mean(durations) * 1000, 1),
        "p95_ms": round(statistics.quantiles(durations, n=20)[18] * 1000, 1) if len(durations) >= 20 else round(max(durations) * 1000, 1),
        "max_ms": round(max(durations) * 1000, 1),
    }


async def main_async(args: argparse.Namespace) -> int:
    results: list[dict[str, Any]] = []
    if args.parse:
        results.append(await _run_parse_benchmark(args))
    if args.monitor:
        results.append(await _run_monitor_benchmark(args))
    if not results:
        results.append({"skipped": True, "reason": "未选择 --parse 或 --monitor"})
    payload = {"created_at": time.strftime("%Y-%m-%d %H:%M:%S"), "allow_network": bool(args.allow_network), "results": results}
    output = Path(args.output or ROOT / "downloads" / "benchmarks" / f"douyin_benchmark_{int(time.time())}.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Douyin monitor live benchmark. Dry-run by default; use --allow-network for real requests.")
    parser.add_argument("--allow-network", action="store_true", help="允许真实访问抖音/解析接口")
    parser.add_argument("--parse", action="store_true", help="压测批量解析")
    parser.add_argument("--monitor", action="store_true", help="压测内容监控")
    parser.add_argument("--urls-file", default="", help="包含待解析 URL 的文本文件")
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main_async(parse_args(sys.argv[1:]))))
