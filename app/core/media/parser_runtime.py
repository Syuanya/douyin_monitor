from __future__ import annotations

from .parser_common import *


class ParserRuntimeMixin:
    async def parse_text(self, text: str, concurrency: int | None = None) -> VideoParseBatchResult:
        urls = self.extract_urls(text)
        result = VideoParseBatchResult(input_text=text, urls=urls)
        async for event in self.parse_text_stream(text, concurrency=concurrency):
            if isinstance(event, ParsedVideoResult):
                result.successes.append(event)
            elif isinstance(event, ParseFailure):
                result.failures.append(event)
        return result

    async def parse_text_stream(
        self,
        text: str,
        concurrency: int | None = None,
        batch_size: int | None = None,
    ):
        """Yield parse results as soon as each URL finishes.

        The generator yields ``ParseProgress`` events plus ``ParsedVideoResult``
        or ``ParseFailure`` objects. This lets the UI display results during a
        large batch instead of waiting for the whole gather call to finish.
        """

        urls = self.extract_urls(text)
        total = len(urls)
        if total <= 0:
            yield ParseProgress(total=0, completed=0, status="completed", message="没有识别到可解析链接")
            return
        limit = max(1, int(concurrency or self.parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        chunk_size = max(1, int(batch_size or self._parse_batch_size()))
        completed = 0
        success_count = 0
        failed_count = 0
        yield ParseProgress(total=total, completed=0, status="started", message=f"开始解析 {total} 个链接，并发 {limit}")

        for offset in range(0, total, chunk_size):
            chunk = urls[offset : offset + chunk_size]
            sem = asyncio.Semaphore(limit)

            async def parse_one(url: str) -> ParsedVideoResult | ParseFailure:
                try:
                    async with sem:
                        data = await self.parse_url(url)
                    return ParsedVideoResult.from_api_data(url, data)
                except Exception as exc:
                    reason = str(exc) or exc.__class__.__name__
                    assessment = classify_parser_failure(reason)
                    return ParseFailure(
                        source_url=url,
                        reason=reason,
                        category=assessment.category,
                        retryable=assessment.retryable,
                        user_action_required=assessment.user_action_required,
                        next_step=assessment.detail,
                    )

            tasks = [asyncio.create_task(parse_one(url)) for url in chunk]
            for task in asyncio.as_completed(tasks):
                item = await task
                completed += 1
                if isinstance(item, ParsedVideoResult):
                    success_count += 1
                else:
                    failed_count += 1
                yield item
                yield ParseProgress(
                    source_url=getattr(item, "source_url", ""),
                    total=total,
                    completed=completed,
                    success_count=success_count,
                    failed_count=failed_count,
                    status="running" if completed < total else "completed",
                    message=f"解析进度：{completed}/{total}，成功 {success_count}，失败 {failed_count}",
                )


    async def parse_text_download_stream(
        self,
        text: str,
        downloader: Any,
        *,
        concurrency: int | None = None,
        batch_size: int | None = None,
        download_concurrency: int | None = None,
    ):
        """Stream parse events and enqueue downloads as each item succeeds.

        This implements the high-throughput pipeline mode:
        parse one item -> immediately enqueue download -> continue parsing.
        It yields ParsedVideoResult/ParseFailure/ParseProgress plus
        ParseDownloadEvent objects for download state.
        """

        download_limit = max(1, int(download_concurrency or getattr(self, "batch_download_concurrency", 3) or 3))
        download_sem = asyncio.Semaphore(download_limit)
        download_tasks: set[asyncio.Task] = set()

        async def run_download(item: ParsedVideoResult) -> ParseDownloadEvent:
            async with download_sem:
                try:
                    result = await downloader.download(item)
                    return ParseDownloadEvent(
                        source_url=item.source_url,
                        item_id=item.item_id,
                        status="completed" if result.get("success") else "failed",
                        success=bool(result.get("success")),
                        reason=str(result.get("reason") or ""),
                        path=str(result.get("path") or ""),
                        result=dict(result or {}),
                    )
                except Exception as exc:
                    return ParseDownloadEvent(
                        source_url=item.source_url,
                        item_id=item.item_id,
                        status="failed",
                        success=False,
                        reason=str(exc) or exc.__class__.__name__,
                    )

        async for event in self.parse_text_stream(text, concurrency=concurrency, batch_size=batch_size):
            yield event
            if isinstance(event, ParsedVideoResult):
                yield ParseDownloadEvent(event.source_url, event.item_id, status="queued", reason="已加入下载队列")
                task = asyncio.create_task(run_download(event))
                download_tasks.add(task)
                completed_now = [task for task in list(download_tasks) if task.done()]
                for done_task in completed_now:
                    download_tasks.discard(done_task)
                    yield done_task.result()
        while download_tasks:
            done, _pending = await asyncio.wait(download_tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                download_tasks.discard(task)
                yield task.result()

    def _parse_batch_size(self) -> int:
        try:
            return max(1, min(200, int(getattr(self, "parse_batch_size", 20) or 20)))
        except (TypeError, ValueError):
            return 20

    async def parse_url(self, url: str) -> dict[str, Any]:
        key_url = normalize_work_url(url) or str(url or "").strip()
        cached = self._parse_cache.get(key_url)
        if cached is not None and time.time() - cached[0] <= self.parse_cache_ttl_seconds:
            data = dict(cached[1])
            if data.get("__negative_cache__"):
                raise RuntimeError(str(data.get("reason") or "cached parse failure"))
            return data
        loop = asyncio.get_running_loop()
        task_key = (id(loop), key_url)
        existing = self._inflight_parses.get(task_key)
        if existing is not None and not existing.done():
            return dict(await existing)

        task = loop.create_task(self._parse_url_once(url))
        self._inflight_parses[task_key] = task
        try:
            data = dict(await task)
            self._parse_cache[key_url] = (time.time(), dict(data))
            self._trim_parse_cache()
            return data
        except Exception as exc:
            reason = str(exc) or exc.__class__.__name__
            ttl = self._negative_cache_ttl(reason)
            if ttl > 0:
                self._parse_cache[key_url] = (time.time() - self.parse_cache_ttl_seconds + ttl, {"__negative_cache__": True, "reason": reason})
                self._trim_parse_cache()
            raise
        finally:
            if self._inflight_parses.get(task_key) is task:
                self._inflight_parses.pop(task_key, None)

    def _negative_cache_ttl(self, reason: str) -> float:
        lowered = str(reason or "").lower()
        if "not found" in lowered or "不存在" in lowered:
            return min(3600.0, self.parse_cache_ttl_seconds)
        if "empty" in lowered or "空响应" in lowered or "响应内容为空" in lowered:
            return min(900.0, self.parse_cache_ttl_seconds)
        if "cookie" in lowered or "登录" in lowered or "login" in lowered:
            return min(300.0, self.parse_cache_ttl_seconds)
        return 0.0

    def _trim_parse_cache(self) -> None:
        if len(self._parse_cache) <= 300:
            return
        for key, _value in sorted(self._parse_cache.items(), key=lambda item: item[1][0])[:75]:
            self._parse_cache.pop(key, None)

    async def _parse_url_once(self, url: str) -> dict[str, Any]:
        parser = self._parser or self._get_default_parser()
        cookie = ""
        platform = "douyin" if "douyin" in str(url or "").lower() else "tiktok" if "tiktok" in str(url or "").lower() else ""
        async with self._parse_semaphore():
            kwargs = {"url": url, "minimal": True}
            try:
                if platform and "cookie" in inspect.signature(parser).parameters:
                    cookie = self.next_cookie(platform) or ""
                    if cookie:
                        kwargs["cookie"] = cookie
            except (TypeError, ValueError):
                pass
            limiter = getattr(self, "request_limiter", None)
            if limiter is not None:
                scopes = ["api:parse"]
                if cookie:
                    scopes.append("cookie:" + cookie[-24:])
                try:
                    await limiter.wait(*scopes)
                except Exception:
                    pass
            try:
                value = parser(**kwargs)
                if inspect.isawaitable(value):
                    value = await value
            except Exception as exc:
                if cookie and platform and hasattr(self, "record_cookie_failure"):
                    self.record_cookie_failure(platform, cookie, str(exc))
                limiter = getattr(self, "request_limiter", None)
                if limiter is not None:
                    try:
                        limiter.record_failure(str(exc))
                    except Exception:
                        pass
                raise
        if not isinstance(value, dict):
            if cookie and platform and hasattr(self, "record_cookie_failure"):
                self.record_cookie_failure(platform, cookie, "invalid parser response")
            limiter = getattr(self, "request_limiter", None)
            if limiter is not None:
                try:
                    limiter.record_failure("invalid parser response")
                except Exception:
                    pass
            raise ValueError("Parser returned an invalid response.")
        if cookie and platform and hasattr(self, "record_cookie_success"):
            self.record_cookie_success(platform, cookie)
        limiter = getattr(self, "request_limiter", None)
        if limiter is not None:
            try:
                limiter.record_success()
            except Exception:
                pass
        return value

    def _parse_semaphore(self) -> asyncio.Semaphore:
        limit = max(1, int(self.parse_concurrency or self.DEFAULT_PARSE_CONCURRENCY))
        loop_id = id(asyncio.get_running_loop())
        sem = self._parse_locks.get(loop_id)
        if sem is None or getattr(sem, "_douyin_parser_limit", None) != limit:
            sem = asyncio.Semaphore(limit)
            setattr(sem, "_douyin_parser_limit", limit)
            self._parse_locks[loop_id] = sem
        return sem

    def _get_default_parser(self) -> ParserCallable:
        if self._hybrid_crawler is None:
            from crawlers.hybrid.hybrid_crawler import HybridCrawler

            self._hybrid_crawler = HybridCrawler()
        return self._hybrid_crawler.hybrid_parsing_single_video
