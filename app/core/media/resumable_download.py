from __future__ import annotations

import asyncio
import os
import time
from collections.abc import Callable
from typing import Any

import httpx


ProgressFormatter = Callable[[int, int, float], str]
ProgressReporter = Callable[[str], None]
ProgressCallback = Callable[[int, int], None]


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
) -> None:
    """Download to ``save_path`` using a resumable ``.part`` file.

    If a previous partial file exists, the request is retried with a Range
    header. Servers that do not support Range simply restart the download. The
    final move uses ``os.replace`` so callers never observe a half-written final
    file.
    """

    if not url:
        raise ValueError("download url is empty")
    os.makedirs(os.path.dirname(save_path), exist_ok=True)
    part_path = save_path + ".part"
    if not resume_enabled:
        _remove_quietly(part_path)
    resume_from = _file_size(part_path) if resume_enabled else 0
    request_headers = dict(headers or {})
    if resume_from > 0:
        request_headers["Range"] = f"bytes={resume_from}-"

    downloaded = resume_from
    total = 0
    started = time.monotonic()
    last_report = started
    try:
        async with httpx.AsyncClient(headers=request_headers, timeout=timeout, proxy=proxy, follow_redirects=True) as client:
            async with client.stream("GET", url) as response:
                if response.status_code == 416 and resume_from > 0:
                    # Local partial file is incompatible with server state.
                    _remove_quietly(part_path)
                    return await download_http_file(
                        url,
                        save_path,
                        headers=headers,
                        timeout=timeout,
                        proxy=proxy,
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
                        now = time.monotonic()
                        if progress_callback:
                            progress_callback(downloaded, total)
                        if progress_reporter and progress_formatter and now - last_report >= progress_interval:
                            progress_reporter(progress_formatter(downloaded, total, started))
                            last_report = now
        os.replace(part_path, save_path)
    except asyncio.CancelledError:
        # Keep .part for a future resume.
        raise


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
