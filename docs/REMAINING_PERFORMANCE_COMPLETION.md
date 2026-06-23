# Remaining Performance Completion

This release completes the second-stage performance work after the core decoupling and initial optimization pass.

## Completed areas

### Content monitor

- Bounded batch checks for enabled/due accounts.
- Fast no-change path based on profile aweme count.
- Incremental parser page limits when the public profile reports a small count delta.
- Batch sync API for selected/all accounts.
- Global request limiter integration for profile, user-info and user-post requests.
- Persistent cookie health integration for monitor Cookie rotation.

### Video parser

- Streamed parse events remain available through `parse_text_stream`.
- High-throughput parse/download pipeline is available through `parse_text_download_stream`.
- Stronger URL dedupe by normalized URL and direct Douyin work id.
- Parser Cookie health now uses persisted scores/cooldowns when present.
- Parser requests join the global Douyin request limiter.

### Download system

- Shared HTTP client pool remains the default path for parsed/content downloads.
- Gallery image downloads use bounded internal concurrency.
- Segmented download now supports resumable segment files, per-segment retry, metadata consistency checks and temporary host blacklist fallback.
- Batch content download jobs are persisted and can resume completed/failed/skipped item state after restart.

### Batch operations

- New-work batch mark-as-seen uses one in-memory update, one persist and one UI broadcast.
- Account start/stop and delete operations have batch transaction-style service methods.
- Content batch downloads persist job progress and failed item reasons.

### Settings UI

The settings page exposes performance controls for:

- monitor concurrency
- parse batch size
- batch download concurrency
- gallery image concurrency
- download chunk size
- Cookie cooldown
- monitor incremental pages
- global request limiter
- Cookie health persistence
- parse-download pipeline
- segmented download and segmented thresholds

## Default posture

Defaults are intentionally conservative. Higher values may improve throughput but increase Douyin risk-control probability.

- `monitor_batch_concurrency`: 2
- `batch_parse_size`: 20
- `batch_download_concurrency`: 3
- `gallery_image_concurrency`: 4
- `segmented_download_enabled`: false
- `batch_parse_download_pipeline_enabled`: false

Enable the pipeline and segmented download only after Cookie/IP stability is confirmed.
