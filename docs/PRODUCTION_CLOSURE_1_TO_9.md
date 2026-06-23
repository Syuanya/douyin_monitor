# 1–9 项生产收尾完成说明

本轮补齐上一轮列出的 1–9 项：线上压测入口、外部解析器统一接口、Cookie 健康度可视化、全局限速器可视化、批量下载详情 UI、批量任务暂停/继续/取消恢复链路、分片下载强化、旧数据迁移验证、Windows 打包验证。

## 1. 真实抖音线上压测入口

新增 `scripts/live_douyin_benchmark.py`。默认 dry-run，不访问网络；加 `--allow-network` 后才会真实请求。

示例：

```bash
python scripts/live_douyin_benchmark.py --parse --urls-file urls.txt --concurrency 3 --limit 100 --allow-network
python scripts/live_douyin_benchmark.py --monitor --allow-network
```

输出 JSON 写入 `downloads/benchmarks/`。

## 2. 外部解析器统一接口

`ExternalDouyinParserBackend.parse_url()` 已实现，并接入 `DouyinExternalApiClient.fetch_one_video_by_url()`。外部 API 单作品响应会被归一化为 `ParsedVideoResult.from_api_data()` 可消费的统一 schema。

## 3. Cookie 健康度可视化

新增 `PerformanceObservabilityService.cookie_health_summary()`，设置页显示 Cookie 健康摘要，并支持清理 Cookie 健康记录。诊断页新增 Cookie 健康度检查。

## 4. 全局限速器可视化

`PerformanceObservabilityService.rate_limiter_summary()` 会展示全局退避、等待次数、scope 数量和失败次数。诊断页新增全局限速器检查。

## 5. 批量下载任务详情 UI

任务中心新增批量任务区域，显示运行/暂停/失败批次，并提供详情查看。详情包含失败作品 ID、剩余作品 ID、失败原因和批次进度。

## 6. 批量任务暂停/继续/取消恢复链路

`BatchJobStore` 新增：

- `pause()`
- `resume()`
- `cancel()`
- `snapshot()`
- `detail()`
- `is_paused()`
- `is_cancelled()`

内容监控批量下载 worker 会在每个 item 前检查批次状态。暂停/取消后保留剩余进度，继续时按 remaining item_ids 恢复。

## 7. 分片下载完整校验强化

分片下载新增：

- 分片 SHA256 记录
- 合并文件 SHA256 记录
- `Content-MD5` 校验支持
- 分片运行态快照 `segmented_download_snapshot()`
- Range 不稳定 host 黑名单可观测

## 8. 旧用户数据迁移验证脚本

新增 `scripts/verify_legacy_migration.py`。

示例：

```bash
python scripts/verify_legacy_migration.py
python scripts/verify_legacy_migration.py --source-run-path D:\\old_douyin_monitor
```

## 9. Windows exe 打包运行验证脚本

新增 `scripts/verify_windows_package.py`。

示例：

```bash
python scripts/package_release.py --name douyin_monitor_release.zip
python scripts/verify_windows_package.py --release-zip douyin_monitor_release.zip
python scripts/verify_windows_package.py --run-build
```

非 Windows 环境默认跳过 exe 构建；Windows 环境可通过 `--run-build` 调用 `build_windows_exe.ps1`。
