from __future__ import annotations

from .monitor_common import *


class ContentMonitorDownloadMixin:
    def _content_download_dir(self, account: DouyinMonitorAccount) -> str:
        base = str(self.settings.user_config.get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.run_path, "downloads", "douyin_content")
        safe_name = self._account_download_folder_name(account)
        return os.path.join(base, safe_name)

    def _filename_template(self) -> str:
        return str(self.settings.user_config.get("douyin_content_filename_template") or DEFAULT_FILENAME_TEMPLATE)

    def _media_filename(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        return format_media_filename(
            self._filename_template(),
            {
                "platform": "douyin",
                "author": account.douyin_nickname or account.display_name or account.account_id,
                "item_id": item.item_id,
                "title": item.title or item.item_id,
            },
            fallback=item.item_id or "douyin",
        )

    def _video_save_path(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        return os.path.join(self._content_download_dir(account), f"{self._media_filename(account, item)}.mp4")

    def _existing_downloaded_video_path(self, account: DouyinMonitorAccount, item: DouyinContentItem) -> str:
        save_path = self._video_save_path(account, item)
        if os.path.exists(save_path) and os.path.getsize(save_path) > 0:
            return save_path

        roots = self._video_search_roots(account)
        media_name = self._media_filename(account, item)
        patterns = [
            f"{glob.escape(media_name)}.mp4",
            f"{glob.escape(item.item_id)}*.mp4",
            f"*{glob.escape(item.item_id)}*.mp4",
        ]
        matches: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            if not root.exists() or not root.is_dir():
                continue
            for pattern in patterns:
                try:
                    candidates = root.rglob(pattern)
                    for path in candidates:
                        key = str(path.resolve())
                        if key in seen:
                            continue
                        seen.add(key)
                        if path.is_file() and path.suffix.lower() == ".mp4" and path.stat().st_size > 0:
                            matches.append(path)
                except OSError as exc:
                    logger.debug(f"Search downloaded video failed in {root}: {exc}")
        if not matches:
            return ""
        return str(max(matches, key=lambda path: path.stat().st_mtime))

    def _video_search_roots(self, account: DouyinMonitorAccount) -> list[Path]:
        roots: list[Path] = [Path(self._content_download_dir(account))]
        base = str(self.settings.user_config.get("douyin_content_download_path") or "").strip()
        if not base:
            base = os.path.join(self.run_path, "downloads", "douyin_content")
        base_path = Path(base)
        roots.extend([base_path / "parsed", base_path])
        unique: list[Path] = []
        seen: set[str] = set()
        for root in roots:
            key = str(root)
            if key and key not in seen:
                seen.add(key)
                unique.append(root)
        return unique

    def local_item_path_info(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在"}
        if self._is_gallery_item(item):
            folder = os.path.join(self._content_download_dir(account), self._media_filename(account, item))
            if os.path.isdir(folder):
                files = [str(path) for path in sorted(Path(folder).glob("*")) if path.is_file()]
                if files:
                    return {"success": True, "kind": "folder", "path": folder, "files": files}
            return {"success": False, "reason": "未找到已下载图集文件夹"}
        path = self._existing_downloaded_video_path(account, item)
        if path:
            return {"success": True, "kind": "file", "path": path, "folder": os.path.dirname(path)}
        return {"success": False, "reason": "未找到已下载视频文件"}

    def _account_download_folder_name(self, account: DouyinMonitorAccount) -> str:
        generic_names = {"", "抖音用户", "douyin user", "douyin"}
        display_name = str(account.display_name or "").strip()
        nickname = str(account.douyin_nickname or "").strip()
        name = nickname or ("" if display_name.lower() in generic_names else display_name) or account.account_id
        safe_name = re.sub(r'[\\/:*?"<>|\r\n]+', "_", name).strip(" .") or account.account_id
        sec_uid = self.extract_sec_uid(account.homepage_url)
        suffix = (sec_uid[-8:] if sec_uid else account.account_id[:8]).strip()
        if suffix and suffix not in safe_name:
            safe_name = f"{safe_name}_{suffix}"
        return safe_name[:120]

    async def _notify_new_items(self, account: DouyinMonitorAccount, new_items: list[DouyinContentItem]) -> None:
        if str(getattr(account, "notify_mode", "desktop") or "desktop") != "desktop":
            return
        top_item = new_items[0]
        title = f"抖音用户更新：{account.display_name or account.douyin_nickname or '抖音用户'}"
        message = f"发现 {len(new_items)} 个新作品：{top_item.title or top_item.item_id}"
        self.services.broadcast_snack(message, duration=5000, show_close_icon=True)
        self._write_detection_log(f"New Douyin content notification: {title} / {message}")
        # Desktop notification only when a UI session is hidden/minimized.
        for bridge in self.services.snapshot_bridges():
            try:
                app = bridge
                from ...messages.desktop_notify import send_notification, should_push_notification

                if should_push_notification(app):
                    send_notification(title, message, timeout=10)
            except Exception as exc:
                logger.debug(f"Douyin desktop notification skipped: {exc}")

    def _schedule_auto_download(self, account: DouyinMonitorAccount, new_items: list[DouyinContentItem]) -> None:
        policy = str(getattr(account, "auto_download_policy", "none") or "none")
        if policy == "none" or not new_items:
            return
        item_ids = [item.item_id for item in new_items if self._auto_download_matches(policy, item)]
        if not item_ids:
            return

        async def run_auto_download() -> None:
            success = 0
            failed = 0
            task_center = getattr(self.services, "task_center", None)
            task_id = (
                task_center.start(
                    f"自动下载：{account.display_name or account.douyin_nickname or account.account_id}",
                    "自动下载",
                    total=len(item_ids),
                    retry_action="content_download_items",
                    retry_payload={"account_id": account.account_id, "item_ids": item_ids},
                )
                if task_center
                else None
            )
            for index, item_id in enumerate(item_ids, start=1):
                result = await self.download_item(account.account_id, item_id, priority="background")
                if result.get("success"):
                    success += 1
                else:
                    failed += 1
                if task_center and task_id:
                    task_center.progress(
                        task_id,
                        completed=index,
                        success_count=success,
                        failed_count=failed,
                        detail=f"自动下载进度：{index}/{len(item_ids)}，成功 {success}，失败 {failed}",
                    )
            if task_center and task_id:
                task_center.finish(task_id, success=failed == 0, detail=f"自动下载完成：成功 {success}，失败 {failed}")
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "auto_download", "account_id": account.account_id})

        try:
            asyncio.create_task(run_auto_download())
        except RuntimeError:
            logger.debug("Auto download skipped: no running event loop")

    def _auto_download_matches(self, policy: str, item: DouyinContentItem) -> bool:
        if policy == "all":
            return item.status != "count_only"
        if policy == "gallery":
            return self._is_gallery_item(item)
        if policy == "video":
            return item.status != "count_only" and not self._is_gallery_item(item)
        return False

    async def download_item(self, account_id: str, item_id: str, priority: str = "foreground") -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if item.status == "count_only":
            return {"success": False, "reason": "这是作品数量变化提示，尚未拿到具体作品明细；请先重新同步该账号作品。"}
        if self._is_gallery_item(item):
            return await self._download_gallery_with_parsed_downloader(account, item, priority=priority)

        existing_path = self._existing_downloaded_video_path(account, item)
        if existing_path:
            item.status = "downloaded"
            self._refresh_account_new_count(account)
            await self.persist()
            return {"success": True, "reason": "文件已存在", "path": existing_path}

        should_refresh_video_url = bool(item.download_url) and self._is_expiring_douyin_video_url(item.download_url)
        if (not item.download_url and not item.image_urls) or should_refresh_video_url:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()
            elif should_refresh_video_url:
                item.download_url = ""
                item.status = "download_failed"
                self._refresh_account_new_count(account)
                await self.persist()
                return {"success": False, "reason": "解析器未返回可下载视频，作品可能已下架、不可见或被接口过滤"}
        if not item.download_url:
            return {"success": False, "reason": "未获取到下载地址，请检查解析器配置"}

        save_path = self._video_save_path(account, item)
        task_label = item.title or item.item_id

        async def run_download():
            await self._download_file(item.download_url, save_path)
            return save_path

        try:
            path = await self.services.media_task_queue.run(
                "douyin_download",
                task_label,
                run_download,
                priority=priority,
                dedupe_key=save_path,
            )
        except Exception as exc:
            refreshed = await self._resolve_item_download_item(item)
            if refreshed and refreshed.download_url:
                self._apply_resolved_download_item(item, refreshed)
                await self.persist()

                async def retry_download():
                    await self._download_file(item.download_url, save_path)
                    return save_path

                try:
                    path = await self.services.media_task_queue.run(
                        "douyin_download",
                        task_label,
                        retry_download,
                        priority=priority,
                        dedupe_key=save_path,
                    )
                except Exception as retry_exc:
                    item.status = "download_failed"
                    self._refresh_account_new_count(account)
                    await self.persist()
                    return {"success": False, "reason": f"下载失败：{retry_exc}"}
            else:
                item.status = "download_failed"
                self._refresh_account_new_count(account)
                await self.persist()
                return {"success": False, "reason": f"下载失败：{exc}"}
        item.status = "downloaded"
        self._refresh_account_new_count(account)
        await self.persist()
        return {"success": True, "reason": "下载完成", "path": path}

    async def resolve_item_preview(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if self._is_gallery_item(item):
            return {"success": False, "reason": "图文作品不支持视频浏览，请打开作品或下载图片"}

        existing_path = self._existing_downloaded_video_path(account, item)
        if existing_path:
            item.status = "downloaded"
            await self.persist()
            return {
                "success": True,
                "reason": "使用已下载文件预览",
                "url": existing_path,
                "share_url": item.share_url,
                "title": item.title or item.item_id,
                "is_file_path": True,
            }

        should_refresh_video_url = bool(item.download_url) and self._is_expiring_douyin_video_url(item.download_url)
        if not item.download_url or should_refresh_video_url:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()
            elif should_refresh_video_url:
                item.download_url = ""
                await self.persist()

        if self._is_gallery_item(item):
            return {"success": False, "reason": "图文作品不支持视频浏览，请打开作品或下载图片"}
        if not item.download_url:
            return {"success": False, "reason": "未获取到视频浏览地址，请检查解析器配置"}
        try:
            cache = await self.services.parsed_media_downloader.cache_video_preview(
                item.download_url,
                f"{account.account_id}_{item.item_id}",
                title=item.title or item.item_id or "视频预览",
                priority="foreground",
            )
            if cache.get("success") and cache.get("path"):
                return {
                    "success": True,
                    "reason": "使用本地预览缓存",
                    "url": str(cache["path"]),
                    "share_url": item.share_url,
                    "title": item.title or item.item_id,
                    "is_file_path": True,
                    "copy_source_url": item.download_url,
                }
        except Exception as exc:
            logger.debug(f"Cache content video preview failed: {exc}")
        return {
            "success": True,
            "reason": "已获取视频浏览地址",
            "url": item.download_url,
            "share_url": item.share_url,
            "title": item.title or item.item_id,
            "is_file_path": False,
        }

    async def resolve_item_image_preview(self, account_id: str, item_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        item = next((candidate for candidate in account.items if candidate.item_id == item_id), None)
        if not item:
            return {"success": False, "reason": "作品不存在，请先同步作品列表"}
        if not self._is_gallery_item(item):
            return {"success": False, "reason": "当前作品不是图文作品"}

        item.image_urls = deduplicate_image_urls(item.image_urls)
        if not item.image_urls:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()

        if not item.image_urls:
            return {"success": False, "reason": "未获取到图片地址，请打开作品或重新同步"}
        return {
            "success": True,
            "reason": "已获取图片预览地址",
            "urls": deduplicate_image_urls(item.image_urls),
            "share_url": item.share_url,
            "title": item.title or item.item_id,
            "item_id": item.item_id,
        }

    @staticmethod
    def _apply_resolved_download_item(item: DouyinContentItem, resolved: DouyinContentItem) -> None:
        item.download_url = resolved.download_url or item.download_url
        item.cover_url = resolved.cover_url or item.cover_url
        item.media_type = resolved.media_type or item.media_type
        item.image_urls = deduplicate_image_urls(resolved.image_urls or item.image_urls)

    @staticmethod
    def _is_gallery_item(item: DouyinContentItem) -> bool:
        return bool(item.image_urls) or str(item.media_type or "").lower() in {"image", "images", "gallery", "note"}

    @staticmethod
    def _is_expiring_douyin_video_url(url: str) -> bool:
        hostname = (urlsplit(str(url or "")).hostname or "").lower()
        return hostname.endswith("douyinvod.com")

    async def _download_gallery_with_parsed_downloader(self, account: DouyinMonitorAccount, item: DouyinContentItem, priority: str = "foreground") -> dict[str, Any]:
        item.image_urls = deduplicate_image_urls(item.image_urls)
        if not item.image_urls:
            resolved = await self._resolve_item_download_item(item)
            if resolved:
                self._apply_resolved_download_item(item, resolved)
                await self.persist()

        if not item.image_urls:
            item.status = "download_failed"
            self._refresh_account_new_count(account)
            await self.persist()
            return {"success": False, "reason": "未获取到图集图片地址，请检查解析器配置"}

        item.image_urls = deduplicate_image_urls(item.image_urls)
        parsed_item = self._to_parsed_media_result(account, item, priority=priority)
        try:
            result = await self.services.parsed_media_downloader.download(parsed_item)
        except Exception as exc:
            refreshed = await self._resolve_item_download_item(item)
            if refreshed and refreshed.image_urls:
                self._apply_resolved_download_item(item, refreshed)
                await self.persist()
                parsed_item = self._to_parsed_media_result(account, item, priority=priority)
                try:
                    result = await self.services.parsed_media_downloader.download(parsed_item)
                except Exception as retry_exc:
                    item.status = "download_failed"
                    self._refresh_account_new_count(account)
                    await self.persist()
                    return {"success": False, "reason": f"图集下载失败：{retry_exc}"}
            else:
                item.status = "download_failed"
                self._refresh_account_new_count(account)
                await self.persist()
                return {"success": False, "reason": f"图集下载失败：{exc}"}

        item.status = "downloaded" if result.get("success") else "download_failed"
        self._refresh_account_new_count(account)
        await self.persist()
        return result

    def _to_parsed_media_result(self, account: DouyinMonitorAccount, item: DouyinContentItem, priority: str = "foreground") -> ParsedVideoResult:
        return ParsedVideoResult(
            source_url=item.share_url,
            media_type="image",
            platform="douyin",
            item_id=item.item_id,
            description=item.title or item.item_id,
            author_nickname=account.display_name or account.douyin_nickname,
            no_watermark_url="",
            watermark_url="",
            image_urls=deduplicate_image_urls(item.image_urls),
            watermark_image_urls=[],
            raw_data={
                "download_base_dir": self._content_download_dir(account),
                "download_filename": self._media_filename(account, item),
                "download_priority": priority,
            },
        )

    async def download_all_items(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "total": 0, "success_count": 0, "failed_count": 0}
        if not account.items:
            sync_result = await self.sync_account_works(account_id)
            if not sync_result.get("success"):
                return {"success": False, "reason": sync_result.get("reason"), "total": 0, "success_count": 0, "failed_count": 0}
        item_ids = [item.item_id for item in list(account.items) if item.status != "count_only"]
        return await self.download_items_batch(account_id, item_ids, title_prefix="全部作品下载")

    async def download_items_batch(self, account_id: str, item_ids: list[str], title_prefix: str = "批量下载") -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "total": 0, "success_count": 0, "failed_count": 0}
        unique_ids = [item_id for item_id in dict.fromkeys(str(value) for value in item_ids if value)]
        total = len(unique_ids)
        if total <= 0:
            return {"success": True, "reason": "没有可下载作品", "total": 0, "success_count": 0, "failed_count": 0}

        name = account.display_name or account.douyin_nickname or account.account_id
        batch_key = f"content-download:{account_id}:{','.join(unique_ids)}"
        batch_store = getattr(self.services, "batch_job_store", None)
        batch_job = None
        already_completed: set[str] = set()
        if batch_store is not None:
            try:
                batch_job = batch_store.start_or_resume(
                    batch_key,
                    f"{title_prefix}：{name}",
                    total,
                    {"account_id": account_id, "item_ids": unique_ids},
                )
                already_completed = set(batch_job.completed_ids or [])
            except Exception as exc:
                logger.debug(f"create/resume batch download job failed: {exc}")
                batch_job = None
        task_center = getattr(self.services, "task_center", None)
        task_id = ""
        if task_center is not None:
            task_id = task_center.start(
                f"{title_prefix}：{name}",
                "内容监控下载",
                detail=f"准备批量下载 {total} 个作品" + ("（恢复未完成批次）" if already_completed else ""),
                total=total,
                retry_action="content_download_items",
                retry_payload={"account_id": account_id, "item_ids": unique_ids},
            )

        limit = self._batch_download_concurrency()
        queue: asyncio.Queue[str] = asyncio.Queue()
        results: list[dict[str, Any]] = []
        failed_item_ids: list[str] = []
        for item_id in unique_ids:
            if item_id in already_completed:
                results.append({"success": True, "reason": "已在上次批量任务完成", "skipped": True})
                continue
            queue.put_nowait(item_id)
        state_lock = asyncio.Lock()

        async def worker() -> None:
            while True:
                if batch_store is not None and batch_job is not None:
                    current_job = batch_store.get(batch_job.job_id)
                    if current_job is not None and current_job.status in {"paused", "cancelled"}:
                        return
                try:
                    item_id = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                try:
                    if batch_store is not None and batch_job is not None:
                        current_job = batch_store.get(batch_job.job_id)
                        if current_job is not None and current_job.status in {"paused", "cancelled"}:
                            queue.put_nowait(item_id)
                            return
                    try:
                        result = await self.download_item(account_id, item_id, priority="background")
                    except asyncio.CancelledError:
                        raise
                    except Exception as exc:
                        result = {"success": False, "reason": str(exc) or exc.__class__.__name__}
                    async with state_lock:
                        results.append(result)
                        if result.get("success"):
                            if batch_store is not None and batch_job is not None:
                                batch_store.mark_item(batch_job.job_id, item_id, "completed")
                        else:
                            failed_item_ids.append(item_id)
                            if batch_store is not None and batch_job is not None:
                                batch_store.mark_item(batch_job.job_id, item_id, "failed", str(result.get("reason") or "下载失败"))
                        done = len(results)
                        success_count = len([item for item in results if item.get("success")])
                        failed_count = done - success_count
                        if task_center is not None and task_id:
                            task_center.progress(
                                task_id,
                                completed=done,
                                success_count=success_count,
                                failed_count=failed_count,
                                detail=f"批量下载进度：{done}/{total}，成功 {success_count}，失败 {failed_count}",
                                retry_payload={"account_id": account_id, "item_ids": failed_item_ids or unique_ids, "failed_item_ids": failed_item_ids},
                            )
                finally:
                    queue.task_done()

        workers = [asyncio.create_task(worker()) for _ in range(min(limit, total))]
        try:
            await asyncio.gather(*workers)
        except asyncio.CancelledError:
            for task in workers:
                task.cancel()
            if batch_store is not None and batch_job is not None:
                batch_store.pause(batch_job.job_id)
            if task_center is not None and task_id and hasattr(task_center, "cancel"):
                task_center.cancel(task_id, "批量下载已取消，进度已保存")
            raise

        success_count = len([item for item in results if item.get("success")])
        failed_count = len(results) - success_count
        await self.persist(force=True)
        stopped_status = ""
        if batch_store is not None and batch_job is not None:
            current_job = batch_store.get(batch_job.job_id)
            stopped_status = str(getattr(current_job, "status", "") or "") if current_job is not None else ""
            if stopped_status in {"paused", "cancelled"}:
                pass
            else:
                batch_store.finish(batch_job.job_id, success=(failed_count == 0))
        if task_center is not None and task_id:
            if hasattr(task_center, "update_retry_payload"):
                task_center.update_retry_payload(task_id, {"account_id": account_id, "item_ids": failed_item_ids or unique_ids, "failed_item_ids": failed_item_ids})
            if stopped_status == "paused" and hasattr(task_center, "cancel"):
                task_center.cancel(task_id, f"批量下载已暂停：成功 {success_count}，失败 {failed_count}，剩余进度已保存")
            elif stopped_status == "cancelled" and hasattr(task_center, "cancel"):
                task_center.cancel(task_id, f"批量下载已取消：成功 {success_count}，失败 {failed_count}")
            else:
                task_center.finish(task_id, success=(failed_count == 0), detail=f"批量下载完成：成功 {success_count}，失败 {failed_count}")
        return {
            "success": failed_count == 0 and stopped_status not in {"paused", "cancelled"},
            "reason": (f"批量下载已{ '暂停' if stopped_status == 'paused' else '取消' }：成功 {success_count}，失败 {failed_count}" if stopped_status in {"paused", "cancelled"} else f"下载完成：成功 {success_count}，失败 {failed_count}"),
            "total": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "task_id": task_id,
            "batch_job_id": getattr(batch_job, "job_id", "") if batch_job is not None else "",
            "failed_item_ids": failed_item_ids,
        }

    async def mark_items_seen_batch(self, account_item_pairs: list[tuple[str, str]]) -> dict[str, Any]:
        changed = 0
        touched: set[str] = set()
        async with self._lock:
            for account_id, item_id in account_item_pairs:
                account = self.find_account(account_id)
                if not account:
                    continue
                item = next((candidate for candidate in getattr(account, "items", []) if candidate.item_id == item_id), None)
                if item is None:
                    continue
                if str(getattr(item, "status", "")) == "count_only":
                    account.items = [candidate for candidate in getattr(account, "items", []) if candidate.item_id != item_id]
                    changed += 1
                    touched.add(account.account_id)
                elif str(getattr(item, "status", "")) == "new":
                    item.status = "active"
                    changed += 1
                    touched.add(account.account_id)
            for account in self._accounts:
                if account.account_id in touched:
                    self._refresh_account_new_count(account)
            if changed:
                await self.persist(force=True)
        if changed:
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "batch_mark_seen", "changed": changed})
        return {"success": True, "changed": changed, "accounts": sorted(touched)}

    async def _resolve_item_download_item(self, item: DouyinContentItem) -> DouyinContentItem | None:
        try:
            source_url = item.share_url or f"https://www.douyin.com/video/{item.item_id}"
            backend = build_douyin_parser_backend(
                self._parser_backend(),
                video_parser=getattr(self.services, "video_parser", None),
                external_base_url=self._external_api_base_url(),
            )
            data = await backend.parse_url(source_url)
            parsed = self.services.video_parser_result_from_api_data(source_url, data)
            return self._content_item_from_parsed_result(item, parsed)
        except Exception as exc:
            logger.debug(f"Resolve Douyin download url failed with internal parser: item={item.item_id}, error={exc}")
            return None

    @staticmethod
    def _content_item_from_parsed_result(item: DouyinContentItem, parsed: Any) -> DouyinContentItem:
        return DouyinContentItem(
            item_id=parsed.item_id or item.item_id,
            title=parsed.description or item.title,
            share_url=parsed.source_url or item.share_url,
            download_url=parsed.no_watermark_url or parsed.watermark_url or item.download_url,
            cover_url=item.cover_url,
            media_type=parsed.media_type or item.media_type,
            image_urls=deduplicate_image_urls(parsed.image_urls or item.image_urls),
            publish_time=item.publish_time,
            first_seen_time=item.first_seen_time,
            last_seen_time=item.last_seen_time,
            status=item.status,
        )

    async def _download_file(self, url: str, save_path: str) -> None:
        headers = {
            "User-Agent": self._headers().get("User-Agent", ""),
            "Referer": "https://www.douyin.com/",
        }
        proxy = self.settings.user_config.get("proxy_address") or None if self.settings.user_config.get("enable_proxy") else None
        recovery = getattr(self.services, "download_recovery_service", None)
        download_id = recovery.start(url=url, save_path=save_path, kind="content_monitor", label=os.path.basename(save_path)) if recovery else ""
        try:
            await download_http_file(
                url,
                save_path,
                headers=headers,
                proxy=proxy,
                timeout=DOWNLOAD_TIMEOUT,
                client_pool=getattr(self.services, "download_http_client_pool", None),
                chunk_size=self._download_chunk_size(),
                progress_interval=self._download_progress_interval(),
                progress_formatter=self._download_progress_text,
                progress_reporter=report_media_task_progress,
                progress_callback=(lambda downloaded, total: recovery.mark_progress(download_id, downloaded, total)) if recovery and download_id else None,
                resume_enabled=self._download_resume_enabled(),
                segmented_enabled=self._segmented_download_enabled(),
                segmented_parts=self._segmented_download_parts(),
                segmented_min_size_mb=self._segmented_download_min_size_mb(),
            )
            if recovery and download_id:
                recovery.mark_completed(download_id)
        except asyncio.CancelledError:
            if recovery and download_id:
                recovery.mark_cancelled(download_id)
            raise
        except Exception as exc:
            if recovery and download_id:
                recovery.mark_failed(download_id, str(exc))
            raise

    @classmethod
    def _download_progress_text(cls, downloaded: int, total: int, started: float) -> str:
        elapsed = max(0.1, time.monotonic() - started)
        speed = downloaded / elapsed
        if total > 0:
            percent = min(100.0, downloaded * 100.0 / total)
            return f"下载中：{percent:.1f}%  {cls._format_bytes(downloaded)}/{cls._format_bytes(total)}  {cls._format_bytes(speed)}/s"
        return f"下载中：{cls._format_bytes(downloaded)}  {cls._format_bytes(speed)}/s"


    def _download_chunk_size(self) -> int:
        try:
            kb = int(self.settings.user_config.get("download_chunk_size_kb", 512) or 512)
        except (TypeError, ValueError):
            kb = 512
        return max(64, min(8192, kb)) * 1024

    def _batch_download_concurrency(self) -> int:
        try:
            value = int(self.settings.user_config.get("batch_download_concurrency", self.settings.user_config.get("max_parallel_downloads", 3)) or 3)
        except (TypeError, ValueError):
            value = 3
        return max(1, min(12, value))

    def _segmented_download_enabled(self) -> bool:
        value = self.settings.user_config.get("segmented_download_enabled", False)
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)

    def _segmented_download_parts(self) -> int:
        try:
            value = int(self.settings.user_config.get("segmented_download_parts", 4) or 4)
        except (TypeError, ValueError):
            value = 4
        return max(2, min(16, value))

    def _segmented_download_min_size_mb(self) -> int:
        try:
            value = int(self.settings.user_config.get("segmented_download_min_size_mb", 50) or 50)
        except (TypeError, ValueError):
            value = 50
        return max(1, value)

    def _download_progress_interval(self) -> float:
        try:
            value = self.settings.user_config.get("media_download_progress_interval_seconds", 1.5)
            return max(0.5, min(10.0, float(value or 1.5)))
        except (TypeError, ValueError):
            return 1.5

    def _download_resume_enabled(self) -> bool:
        value = self.settings.user_config.get("download_resume_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    @staticmethod
    def _format_bytes(value: float) -> str:
        size = float(max(0.0, value))
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
            size /= 1024
        return f"{size:.1f}GB"
