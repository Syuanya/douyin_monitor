# Performance Optimization Pass

This pass focuses on throughput and batch behavior after the project-level decoupling work.

## Implemented

- Bounded concurrent account checks for the content monitor.
- Streaming batch parsing via `VideoParserService.parse_text_stream()`.
- Reusable media download HTTP client pool.
- Concurrent gallery image downloads.
- Cookie health scoring, cooldown and rotation for parser and monitor cookies.
- Batch download orchestration with task-center progress and retry payloads.
- Transaction-style batch marking for new-work inbox items.
- Optional segmented large-file downloads using HTTP Range requests.

## Safe defaults

```json
{
  "monitor_batch_concurrency": 2,
  "batch_parse_size": 20,
  "batch_download_concurrency": 3,
  "download_chunk_size_kb": 512,
  "gallery_image_concurrency": 4,
  "segmented_download_enabled": false,
  "segmented_download_parts": 4,
  "segmented_download_min_size_mb": 50,
  "douyin_cookie_cooldown_seconds": 600
}
```

Segmented download remains off by default because some CDN endpoints have incomplete or unstable Range support. It can be enabled for large videos when the network and CDN behavior are stable.
