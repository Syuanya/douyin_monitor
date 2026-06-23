from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import time
from urllib.parse import urlsplit
from collections.abc import Callable
from typing import Any

import httpx


ProgressFormatter = Callable[[int, int, float], str]
ProgressReporter = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]

_SEGMENTED_HOST_BLACKLIST: dict[str, float] = {}
_SEGMENTED_ACTIVE: set[str] = set()


async def download_http_file(
    url: str,
    save_path: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: httpx.Timeout | float = 180.0,
    proxy: str | None = None,
    chunk_size: int = 1024 * 256,
    progress_interval: float = 1.5,
    progress_formatter: ProgressFormatter | None = None,
    progress_reporter: ProgressReporter | None = None,
    progress_callback: ProgressCallback | None = None,
    resume_enabled: bool = True,
    client: httpx.AsyncClient | None = None,
    client_pool: Any | None = None,
    segmented_enabled: bool = False,
    segmented_parts: int = 4,
    segmented_min_size_mb: int = 50,
) -> None:
    """Download to ``save_path`` using a resumable ``.part`` file.

    When ``segmented_enabled`` is true and the server advertises Range support,
    large files are split into several temporary range files and merged into the
    final part file. If segmented mode is not supported, the function falls back
    to the normal resumable stream path.
    """

    if not url:
        raise ValueError("download url is empty")
    host = (urlsplit(url).hostname or "").lower()
    if host and _SEGMENTED_HOST_BLACKLIST.get(host, 0.0) <= time.time():
        _SEGMENTED_HOST_BLACKLIST.pop(host, None)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    part_path = save_path + ".part"
    if not resume_enabled:
        _remove_quietly(part_path)

    request_headers = dict(headers or {})
    close_client = False
    if client is None and client_pool is not None:
        client = await client_pool.get_client(proxy=proxy)
    if client is None:
        client = httpx.AsyncClient(headers=request_headers, timeout=timeout, proxy=proxy, follow_redirects=True)
        close_client = True

    try:
        resume_from = _file_size(part_path) if resume_enabled else 0
        if (
            segmented_enabled
            and resume_from <= 0
            and not (host and _SEGMENTED_HOST_BLACKLIST.get(host, 0.0) > time.time())
            and await _download_segmented_if_supported(
                client,
                url,
                save_path,
                part_path,
                request_headers,
                timeout=timeout,
                chunk_size=chunk_size,
                progress_interval=progress_interval,
                progress_formatter=progress_formatter,
                progress_reporter=progress_reporter,
                progress_callback=progress_callback,
                segmented_parts=segmented_parts,
                segmented_min_size_mb=segmented_min_size_mb,
            )
        ):
            return

        await _download_stream(
            client,
            url,
            save_path,
            part_path,
            request_headers,
            timeout=timeout,
            chunk_size=chunk_size,
            progress_interval=progress_interval,
            progress_formatter=progress_formatter,
            progress_reporter=progress_reporter,
            progress_callback=progress_callback,
            resume_enabled=resume_enabled,
        )
    finally:
        if close_client and hasattr(client, "aclose"):
            await client.aclose()


async def _download_stream(
    client: httpx.AsyncClient,
    url: str,
    save_path: str,
    part_path: str,
    request_headers: dict[str, str],
    *,
    timeout: httpx.Timeout | float,
    chunk_size: int,
    progress_interval: float,
    progress_formatter: ProgressFormatter | None,
    progress_reporter: ProgressReporter | None,
    progress_callback: ProgressCallback | None,
    resume_enabled: bool,
) -> None:
    resume_from = _file_size(part_path) if resume_enabled else 0
    headers = dict(request_headers)
    if resume_from > 0:
        headers["Range"] = f"bytes={resume_from}-"

    downloaded = resume_from
    total = 0
    started = time.monotonic()
    last_report = started
    try:
        async with _stream(client, "GET", url, headers=headers, timeout=timeout) as response:
            if response.status_code == 416 and resume_from > 0:
                _remove_quietly(part_path)
                return await _download_stream(
                    client,
                    url,
                    save_path,
                    part_path,
                    request_headers,
                    timeout=timeout,
                    chunk_size=chunk_size,
                    progress_interval=progress_interval,
                    progress_formatter=progress_formatter,
                    progress_reporter=progress_reporter,
                    progress_callback=progress_callback,
                    resume_enabled=resume_enabled,
                )
            response.raise_for_status()
            if resume_from > 0 and response.status_code == 206:
                mode = "ab"
                total = _content_range_total(response.headers.get("content-range")) or (resume_from + int(response.headers.get("content-length") or 0))
            else:
                mode = "wb"
                downloaded = 0
                total = int(response.headers.get("content-length") or 0)

            with open(part_path, mode) as file:
                async for chunk in response.aiter_bytes(chunk_size):
                    if not chunk:
                        continue
                    file.write(chunk)
                    downloaded += len(chunk)
                    last_report = _report_progress(
                        downloaded,
                        total,
                        started,
                        last_report,
                        progress_interval,
                        progress_formatter,
                        progress_reporter,
                        progress_callback,
                    )
        os.replace(part_path, save_path)
    except asyncio.CancelledError:
        raise


async def _download_segmented_if_supported(
    client: httpx.AsyncClient,
    url: str,
    save_path: str,
    part_path: str,
    request_headers: dict[str, str],
    *,
    timeout: httpx.Timeout | float,
    chunk_size: int,
    progress_interval: float,
    progress_formatter: ProgressFormatter | None,
    progress_reporter: ProgressReporter | None,
    progress_callback: ProgressCallback | None,
    segmented_parts: int,
    segmented_min_size_mb: int,
) -> bool:
    try:
        head = await client.head(url, headers=request_headers, timeout=timeout)
        if head.status_code >= 400 or head.headers.get("content-length") in (None, ""):
            return False
        total = int(head.headers.get("content-length") or 0)
    except Exception:
        return False

    min_size = max(1, int(segmented_min_size_mb or 50)) * 1024 * 1024
    if total < min_size:
        return False
    accept_ranges = str(head.headers.get("accept-ranges") or "").lower()
    if "bytes" not in accept_ranges:
        return False
    etag = str(head.headers.get("etag") or "")
    last_modified = str(head.headers.get("last-modified") or "")
    content_md5 = str(head.headers.get("content-md5") or "")
    host = (urlsplit(url).hostname or "").lower()

    parts = max(2, min(16, int(segmented_parts or 4)))
    parts = min(parts, max(1, total // max(1, min_size // 2)) or 1)
    if parts < 2:
        return False

    ranges: list[tuple[int, int]] = []
    block = total // parts
    start = 0
    for index in range(parts):
        end = total - 1 if index == parts - 1 else start + block - 1
        ranges.append((start, end))
        start = end + 1

    started = time.monotonic()
    last_report = started
    progress: dict[int, int] = {index: 0 for index in range(parts)}
    progress_lock = asyncio.Lock()
    segment_paths = [f"{part_path}.seg{index:03d}" for index in range(parts)]
    meta_path = f"{part_path}.segmeta.json"
    meta = {"url": url, "total": total, "etag": etag, "last_modified": last_modified, "content_md5": content_md5, "parts": parts}
    existing_meta: dict[str, Any] = {}
    if os.path.isfile(meta_path):
        try:
            with open(meta_path, "r", encoding="utf-8") as file:
                existing_meta = json.load(file)
        except Exception:
            existing_meta = {}
    if existing_meta and any(existing_meta.get(key) != value for key, value in meta.items() if value):
        for segment_path in segment_paths:
            _remove_quietly(segment_path)
        _remove_quietly(meta_path)
    try:
        with open(meta_path, "w", encoding="utf-8") as file:
            json.dump(meta, file, ensure_ascii=False, indent=2)
    except Exception:
        pass

    async def report(index: int, value: int) -> None:
        nonlocal last_report
        async with progress_lock:
            progress[index] = value
            downloaded = sum(progress.values())
            last_report = _report_progress(
                downloaded,
                total,
                started,
                last_report,
                progress_interval,
                progress_formatter,
                progress_reporter,
                progress_callback,
            )

    async def download_segment(index: int, range_start: int, range_end: int) -> None:
        expected = range_end - range_start + 1
        segment_path = segment_paths[index]
        existing = _file_size(segment_path)
        if existing > expected:
            _remove_quietly(segment_path)
            existing = 0
        if existing == expected:
            await report(index, expected)
            return
        await report(index, existing)
        attempts = 3
        last_error: Exception | None = None
        for attempt in range(attempts):
            current = _file_size(segment_path)
            if current > expected:
                _remove_quietly(segment_path)
                current = 0
            if current == expected:
                await report(index, expected)
                return
            headers = dict(request_headers)
            headers["Range"] = f"bytes={range_start + current}-{range_end}"
            mode = "ab" if current else "wb"
            try:
                async with _stream(client, "GET", url, headers=headers, timeout=timeout) as response:
                    if response.status_code != 206:
                        raise RuntimeError(f"server did not return partial content: HTTP {response.status_code}")
                    response.raise_for_status()
                    downloaded = current
                    with open(segment_path, mode) as file:
                        async for chunk in response.aiter_bytes(chunk_size):
                            if not chunk:
                                continue
                            file.write(chunk)
                            downloaded += len(chunk)
                            await report(index, min(downloaded, expected))
                if _file_size(segment_path) == expected:
                    return
                raise RuntimeError("segmented download wrote an incomplete segment")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                last_error = exc
                await asyncio.sleep(min(2.0, 0.4 * (attempt + 1)))
        if last_error is not None:
            raise last_error
        raise RuntimeError("segmented download wrote an incomplete segment")

    try:
        _SEGMENTED_ACTIVE.add(part_path)
        await asyncio.gather(*(download_segment(index, start, end) for index, (start, end) in enumerate(ranges)))
        segment_hashes = [_sha256_file(segment_path) for segment_path in segment_paths]
        with open(part_path, "wb") as target:
            for segment_path in segment_paths:
                with open(segment_path, "rb") as source:
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        target.write(chunk)
        if _file_size(part_path) != total:
            raise RuntimeError("segmented download merge size mismatch")
        final_sha256 = _sha256_file(part_path)
        if content_md5 and not _content_md5_matches(part_path, content_md5):
            raise RuntimeError("segmented download content-md5 mismatch")
        try:
            meta.update({"segment_sha256": segment_hashes, "final_sha256": final_sha256, "verified_at": time.time()})
            with open(meta_path, "w", encoding="utf-8") as file:
                json.dump(meta, file, ensure_ascii=False, indent=2)
        except Exception:
            pass
        os.replace(part_path, save_path)
        for segment_path in segment_paths:
            _remove_quietly(segment_path)
        _remove_quietly(meta_path)
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        # Keep .seg files and metadata for a later retry; blacklist hosts that
        # claimed Range support but failed partial requests during this run.
        if host:
            _SEGMENTED_HOST_BLACKLIST[host] = time.time() + 1800.0
        _remove_quietly(part_path)
        return False
    finally:
        _SEGMENTED_ACTIVE.discard(part_path)



def segmented_download_snapshot() -> dict[str, Any]:
    now = time.time()
    expired = [host for host, until in _SEGMENTED_HOST_BLACKLIST.items() if until <= now]
    for host in expired:
        _SEGMENTED_HOST_BLACKLIST.pop(host, None)
    return {
        "available": True,
        "blacklisted_hosts": len(_SEGMENTED_HOST_BLACKLIST),
        "active_segments": len(_SEGMENTED_ACTIVE),
        "hosts": sorted(_SEGMENTED_HOST_BLACKLIST),
    }


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _content_md5_matches(path: str, value: str) -> bool:
    text = str(value or "").strip().strip('"')
    if not text:
        return True
    digest = hashlib.md5()  # nosec B324: validating server-provided Content-MD5 only.
    with open(path, "rb") as file:
        while True:
            chunk = file.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    raw = digest.digest()
    candidates = {digest.hexdigest(), base64.b64encode(raw).decode("ascii")}
    return text in candidates

def _stream(client: httpx.AsyncClient, method: str, url: str, *, headers: dict[str, str], timeout: httpx.Timeout | float):
    try:
        return client.stream(method, url, headers=headers, timeout=timeout)
    except TypeError:
        # Test doubles and older wrappers may accept only method/url and read
        # headers from the client constructor/class.
        try:
            type(client).last_headers = dict(headers)
        except Exception:
            pass
        return client.stream(method, url)


def _report_progress(
    downloaded: int,
    total: int,
    started: float,
    last_report: float,
    progress_interval: float,
    progress_formatter: ProgressFormatter | None,
    progress_reporter: ProgressReporter | None,
    progress_callback: ProgressCallback | None,
) -> float:
    now = time.monotonic()
    if progress_callback:
        progress_callback(downloaded, total)
    if progress_reporter and progress_formatter and now - last_report >= progress_interval:
        progress_reporter(progress_formatter(downloaded, total, started))
        return now
    return last_report


def _file_size(path: str) -> int:
    try:
        return os.path.getsize(path) if os.path.isfile(path) else 0
    except OSError:
        return 0


def _content_range_total(value: Any) -> int:
    text = str(value or "")
    if "/" not in text:
        return 0
    try:
        return int(text.rsplit("/", 1)[1])
    except (TypeError, ValueError):
        return 0


def _remove_quietly(path: str) -> None:
    try:
        if os.path.exists(path):
            os.remove(path)
    except OSError:
        pass
