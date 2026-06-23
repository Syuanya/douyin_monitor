from __future__ import annotations

from .monitor_common import *


class ContentMonitorProfileSyncMixin:
    async def fetch_parser_user_posts(self, account: DouyinMonitorAccount, max_pages: int | None = None) -> list[DouyinContentItem]:
        sec_uid = self.extract_sec_uid(account.homepage_url)
        fallback_items: list[DouyinContentItem] = []
        if not sec_uid:
            try:
                page_text, final_url = await self.fetch_public_profile(account, include_cookie=False)
                self._safe_update_homepage_from_final_url(account, final_url)
                if self._public_profile_page_matches_account(account, page_text, final_url):
                    fallback_items = self.parse_public_profile_items(page_text)
            except Exception as exc:
                logger.debug(f"Resolve Douyin profile URL before parser sync failed: {exc}")
            sec_uid = self.extract_sec_uid(account.homepage_url)
            if not sec_uid:
                return fallback_items
        backend = build_douyin_parser_backend(
            self._parser_backend(),
            video_parser=getattr(self.services, "video_parser", None),
            external_base_url=self._external_api_base_url(),
        )
        try:
            limiter = getattr(self.services, "douyin_request_limiter", None)
            if limiter is not None:
                try:
                    await limiter.wait("api:user_posts", "account:" + account.account_id)
                except Exception:
                    pass
            items = await backend.fetch_profile_contents(sec_uid, max_pages=max_pages or self._parser_max_pages(), count=20)
        except Exception:
            if fallback_items:
                return self._strip_eager_video_download_urls(fallback_items)
            raise
        normalized_items = self._normalize_parser_items(items)
        if normalized_items:
            return self._strip_eager_video_download_urls(normalized_items)
        return self._strip_eager_video_download_urls(fallback_items)

    async def fetch_external_user_posts(self, account: DouyinMonitorAccount) -> list[DouyinContentItem]:
        """Compatibility alias. The current default backend is the bundled parser."""
        return await self.fetch_parser_user_posts(account)

    async def sync_account_works(self, account_id: str) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "total": 0, "new": 0}
        lock = self._account_scan_lock(account_id)
        if lock.locked():
            return {"success": False, "reason": "该账号已有检测或同步任务正在运行", "total": len(account.items), "new": 0}
        async with lock:
            try:
                await self.hydrate_account_display_name(account.account_id)
            except Exception as exc:
                logger.debug(f"Refresh target identity before sync failed: {exc}")
            parser_error = ""
            try:
                items = await self.fetch_parser_user_posts(account)
            except Exception as exc:
                parser_error = str(exc)
                logger.debug(f"Douyin parser sync failed, trying public profile fallback: {exc}")
                items = []
            public_errors: list[str] = []
            if not items:
                items, public_errors = await self._fetch_public_profile_items_for_sync(account)
            if not items:
                count_result = await self._sync_account_by_profile_count(account, parser_error=parser_error, public_errors=public_errors)
                if count_result:
                    return count_result
                details = self._sync_failure_detail(parser_error, public_errors)
                return {
                    "success": False,
                    "reason": (
                        "未返回作品列表。"
                        + details
                        + "请稍后重试，或更换可用 Cookie / 降低批量频率；如果该主页无公开作品，也会出现此结果。"
                    ),
                    "total": 0,
                    "new": 0,
                }
            new_items = self._merge_detected_items(account, items)
            now = self._now()
            account.last_check_time = now
            account.last_success_time = now
            account.last_error = ""
            account.error_count = 0
            account.aweme_count = max(account.aweme_count, len(items))
            account.last_aweme_count = account.aweme_count
            account.last_new_count = len(new_items)
            account.total_new_count += len(new_items)
            account.status = "已同步作品列表"
            self._apply_account_retention(account)
            self._refresh_account_new_count(account)
            self._record_monitor_history(account, True, account.status, len(new_items))
            await self.persist(force=True)
            self._write_detection_log(
                f"Synced Douyin works via parser: name={account.display_name or account.douyin_nickname}, "
                f"items={len(items)}, new={len(new_items)}, url={account.homepage_url}"
            )
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
            self._schedule_auto_download(account, new_items)
            return {"success": True, "reason": account.status, "total": len(items), "new": len(new_items)}

    async def _fetch_public_profile_items_for_sync(self, account: DouyinMonitorAccount) -> tuple[list[DouyinContentItem], list[str]]:
        errors: list[str] = []
        for include_cookie, label in ((False, "无 Cookie 公开主页"), (True, "Cookie 公开主页")):
            try:
                page_text, final_url = await self.fetch_public_profile(account, include_cookie=include_cookie)
            except Exception as exc:
                message = f"{label}请求失败：{exc}"
                errors.append(message)
                logger.debug(f"Douyin sync public profile fallback failed: {message}")
                continue
            if not self._public_profile_page_matches_account(account, page_text, final_url):
                message = f"{label}返回页与目标账号不匹配"
                errors.append(message)
                logger.debug(
                    "Skip sync public-profile fallback because fetched page does not match target: "
                    f"source={label}, account={account.account_id}, final_url={sanitize_url(final_url)}"
                )
                continue
            self._safe_update_homepage_from_final_url(account, final_url)
            items = self.parse_public_profile_items(page_text)
            if items:
                return items, errors
            errors.append(f"{label}未识别到作品 ID")
        return [], errors

    async def _sync_account_by_profile_count(
        self,
        account: DouyinMonitorAccount,
        *,
        parser_error: str = "",
        public_errors: list[str] | None = None,
    ) -> dict[str, Any] | None:
        try:
            profile_info = await self.fetch_user_profile_info(account)
        except Exception as exc:
            logger.debug(f"Douyin sync profile count fallback failed: {exc}")
            return None
        if not self._profile_info_matches_account(account, profile_info):
            return None
        aweme_count = self._parse_int(profile_info.get("aweme_count"), -1)
        if aweme_count < 0:
            return None
        if profile_info.get("douyin_nickname") and not account.douyin_nickname:
            account.douyin_nickname = profile_info["douyin_nickname"]
            self._auto_fill_display_name(account)
        if profile_info.get("avatar_url"):
            account.avatar_url = profile_info["avatar_url"]

        now = self._now()
        previous_count = account.aweme_count if account.aweme_count >= 0 else account.last_aweme_count
        first_success = previous_count < 0 and not account.items and not account.known_item_ids
        delta = max(0, aweme_count - previous_count) if previous_count >= 0 else 0
        new_items: list[DouyinContentItem] = []
        if delta:
            item = DouyinContentItem(
                item_id=f"count-{aweme_count}-{int(time.time())}",
                title=f"作品数量增加 {delta} 个（当前 {aweme_count} 个，未获取到作品明细）",
                share_url=account.homepage_url,
                publish_time="",
                first_seen_time=now,
                last_seen_time=now,
                status="count_only",
            )
            account.items.insert(0, item)
            account.items = account.items[:200]
            new_items.append(item)

        account.last_check_time = now
        account.last_success_time = now
        account.last_error = ""
        account.error_count = 0
        account.aweme_count = aweme_count
        account.last_aweme_count = aweme_count
        account.last_new_count = len(new_items)
        account.total_new_count += len(new_items)
        account.status = "已同步作品数量基线" if first_success else ("已发现作品数量变化" if new_items else "作品数量无变化")
        self._apply_account_retention(account)
        self._refresh_account_new_count(account)
        self._record_monitor_history(account, True, account.status, len(new_items))
        await self.persist()
        self._write_detection_log(
            f"Synced Douyin profile count fallback: name={account.display_name or account.douyin_nickname}, "
            f"aweme_count={aweme_count}, new={len(new_items)}, parser_error={sanitize_text(parser_error)}, "
            f"public_errors={sanitize_text('; '.join(public_errors or []))}, url={account.homepage_url}"
        )
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        reason = account.status + "；暂未获取作品明细，已保留数量基线，稍后可再次同步明细"
        return {"success": True, "reason": reason, "total": aweme_count, "new": len(new_items)}

    @staticmethod
    def _sync_failure_detail(parser_error: str = "", public_errors: list[str] | None = None) -> str:
        parts: list[str] = []
        if parser_error:
            parts.append(f"解析器失败：{parser_error}")
        for item in public_errors or []:
            if item:
                parts.append(item)
        return ("原因：" + "；".join(parts) + "。") if parts else ""

    def _merge_detected_items(self, account: DouyinMonitorAccount, detected_items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        for item in detected_items:
            item.image_urls = deduplicate_image_urls(item.image_urls)
        return self._merge_service.merge_detected_items(account, detected_items)

    async def fetch_public_profile(self, account: DouyinMonitorAccount, *, include_cookie: bool = True) -> tuple[str, str]:
        proxy = None
        if self.settings.user_config.get("enable_proxy"):
            proxy = self.settings.user_config.get("proxy_address") or None
        headers, cookie = self._headers_for_cookie_request(include_cookie=include_cookie)
        limiter = getattr(self.services, "douyin_request_limiter", None)
        if limiter is not None:
            try:
                scopes = ["api:profile", "account:" + account.account_id]
                if cookie:
                    scopes.append("cookie:" + cookie[-24:])
                await limiter.wait(*scopes)
            except Exception:
                pass
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=self._request_timeout(),
            proxy=proxy,
        ) as client:
            try:
                response = await client.get(account.homepage_url)
                self._record_cookie_response_health(cookie, response=response)
                if limiter is not None:
                    try:
                        limiter.record_success() if response.status_code < 400 and str(response.text or "").strip() else limiter.record_failure("HTTP 200 empty response")
                    except Exception:
                        pass
                response.raise_for_status()
            except Exception as exc:
                self._record_cookie_response_health(cookie, error=exc)
                if limiter is not None:
                    try:
                        limiter.record_failure(str(exc))
                    except Exception:
                        pass
                raise
            return response.text, str(response.url)

    async def fetch_user_profile_info(self, account: DouyinMonitorAccount) -> dict[str, str]:
        sec_uid = self.extract_sec_uid(account.homepage_url)
        if not sec_uid:
            return {}

        proxy = None
        if self.settings.user_config.get("enable_proxy"):
            proxy = self.settings.user_config.get("proxy_address") or None
        url = f"https://www.douyin.com/web/api/v2/user/info/?sec_uid={sec_uid}"
        headers, cookie = self._headers_for_cookie_request(include_cookie=True)
        limiter = getattr(self.services, "douyin_request_limiter", None)
        if limiter is not None:
            try:
                scopes = ["api:user_info", "account:" + account.account_id]
                if cookie:
                    scopes.append("cookie:" + cookie[-24:])
                await limiter.wait(*scopes)
            except Exception:
                pass
        async with httpx.AsyncClient(
            headers=headers,
            follow_redirects=True,
            timeout=self._request_timeout(),
            proxy=proxy,
        ) as client:
            try:
                response = await client.get(url)
                self._record_cookie_response_health(cookie, response=response)
                if limiter is not None:
                    try:
                        limiter.record_success() if response.status_code < 400 and str(response.text or "").strip() else limiter.record_failure("HTTP 200 empty response")
                    except Exception:
                        pass
                response.raise_for_status()
            except Exception as exc:
                self._record_cookie_response_health(cookie, error=exc)
                if limiter is not None:
                    try:
                        limiter.record_failure(str(exc))
                    except Exception:
                        pass
                raise
            data = response.json()

        if int(data.get("status_code") or 0) != 0:
            return {}
        user_info = data.get("user_info") or data.get("user") or {}
        if not isinstance(user_info, dict):
            return {}

        nickname = self._decode_text(user_info.get("nickname") or "")
        avatar_url = self._extract_avatar_url(user_info)
        aweme_count = self._parse_int(user_info.get("aweme_count"), -1)
        return {
            "douyin_nickname": nickname[:80],
            "avatar_url": avatar_url,
            "aweme_count": aweme_count,
            "sec_uid": str(user_info.get("sec_uid") or user_info.get("secUid") or user_info.get("sec_user_id") or ""),
            "uid": str(user_info.get("uid") or ""),
            "unique_id": str(user_info.get("unique_id") or ""),
        }

    async def check_account(self, account_id: str, notify: bool = True) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在"}
        lock = self._account_scan_lock(account_id)
        if lock.locked():
            return {"success": False, "reason": "该账号已有检测或同步任务正在运行", "new_items": []}
        async with lock:
            account.status = "检测中"
            account.last_check_time = self._now()
            account.last_error = ""
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checking", "account_id": account_id})
            try:
                page_text, final_url = await self.fetch_public_profile(account)
                profile_page_matches = self._public_profile_page_matches_account(account, page_text, final_url)
                if profile_page_matches:
                    self._safe_update_homepage_from_final_url(account, final_url)
                identity_result = await self.hydrate_account_display_name(account.account_id)
                douyin_nickname = account.douyin_nickname if identity_result.get("success") else ""
                try:
                    profile_info = await self.fetch_user_profile_info(account)
                except Exception as exc:
                    profile_info = {}
                    logger.debug(f"Douyin user profile info fallback failed: {exc}")
                profile_info_matches = self._profile_info_matches_account(account, profile_info)
                if profile_info_matches and profile_info.get("douyin_nickname") and not douyin_nickname:
                    account.douyin_nickname = profile_info["douyin_nickname"]
                    self._auto_fill_display_name(account)
                if profile_info_matches and profile_info.get("avatar_url"):
                    account.avatar_url = profile_info["avatar_url"]
                profile_aweme_count = self._parse_int(profile_info.get("aweme_count"), -1) if profile_info_matches else -1
                detected_items = []
                if self._fast_check_no_change(account, profile_aweme_count, profile_info_matches):
                    return await self._handle_fast_no_change_check(account, profile_aweme_count)
                if getattr(account, "auto_sync_enabled", True):
                    try:
                        max_pages = self._incremental_parser_pages(account, profile_aweme_count)
                        detected_items = await self.fetch_parser_user_posts(account, max_pages=max_pages)
                    except Exception as exc:
                        logger.debug(f"Douyin parser user posts fallback failed: {exc}")
                if not detected_items:
                    detected_items = self.parse_public_profile_items(page_text) if profile_page_matches else []
                if not detected_items:
                    if profile_aweme_count >= 0:
                        return await self._handle_profile_count_check(account, profile_aweme_count, notify=notify)
                    return await self._handle_no_public_items_check(account)

                now = self._now()
                first_success = not account.known_item_ids and not account.items
                new_items = self._merge_detected_items(account, detected_items)
                account.aweme_count = profile_aweme_count if profile_aweme_count >= 0 else max(account.aweme_count, len(account.known_item_ids))
                account.last_aweme_count = account.aweme_count
                account.last_success_time = now
                account.error_count = 0
                account.last_new_count = len(new_items)
                account.total_new_count += len(new_items)
                account.status = "已发现新作品" if new_items else ("已建立初始基线" if first_success else "无更新")
                self._apply_account_retention(account)
                self._refresh_account_new_count(account)
                self._record_monitor_history(account, True, account.status, len(new_items))
                await self.persist()
                self._write_detection_log(
                    f"Checked Douyin account: name={account.display_name}, items={len(detected_items)}, new={len(new_items)}, url={account.homepage_url}"
                )
                if notify and account.notify_enabled and new_items:
                    await self._notify_new_items(account, new_items)
                self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
                self._schedule_auto_download(account, new_items)
                return {"success": True, "reason": account.status, "new_items": [item.to_dict() for item in new_items]}
            except httpx.HTTPStatusError as exc:
                reason = f"HTTP {exc.response.status_code}：公开主页请求失败"
            except httpx.TimeoutException:
                reason = "网络超时：公开主页请求超时"
            except httpx.RequestError as exc:
                reason = f"网络错误：{exc}"
            except Exception as exc:
                reason = f"检测异常：{exc}"
            account.status = "检测异常"
            account.last_error = sanitize_text(reason)
            account.error_count += 1
            self._auto_pause_if_needed(account)
            self._record_monitor_history(account, False, account.last_error, 0)
            await self.persist()
            self._write_detection_log(f"Check failed: account={account.display_name}, error={reason}, url={account.homepage_url}")
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account_id})
            return {"success": False, "reason": account.last_error, "new_items": []}


    def _fast_monitor_enabled(self) -> bool:
        value = self.settings.user_config.get("monitor_fast_check_enabled", True)
        if isinstance(value, str):
            return value.strip().lower() not in {"0", "false", "no", "off"}
        return bool(value)

    def _fast_check_no_change(self, account: DouyinMonitorAccount, aweme_count: int, profile_matches: bool) -> bool:
        if not self._fast_monitor_enabled() or not profile_matches or aweme_count < 0:
            return False
        previous = account.aweme_count if account.aweme_count >= 0 else account.last_aweme_count
        if previous < 0 or previous != aweme_count:
            return False
        return bool(account.items or account.known_item_ids)

    def _incremental_parser_pages(self, account: DouyinMonitorAccount, aweme_count: int) -> int | None:
        if not self._fast_monitor_enabled() or aweme_count < 0:
            return None
        previous = account.aweme_count if account.aweme_count >= 0 else account.last_aweme_count
        if previous < 0:
            return None
        delta = max(0, aweme_count - previous)
        if delta <= 0:
            return None
        try:
            pages = int(self.settings.user_config.get("douyin_monitor_incremental_pages", 3) or 3)
        except (TypeError, ValueError):
            pages = 3
        # Always fetch enough pages to cover small bursts; fallback paths still
        # handle count-only changes if the parser returns no detail.
        return max(1, min(self._parser_max_pages(), max(pages, (delta + 19) // 20)))

    async def _handle_fast_no_change_check(self, account: DouyinMonitorAccount, aweme_count: int) -> dict[str, Any]:
        now = self._now()
        account.last_check_time = now
        account.last_success_time = now
        account.last_error = ""
        account.error_count = 0
        account.aweme_count = aweme_count
        account.last_aweme_count = aweme_count
        account.last_new_count = 0
        account.status = "无更新（快速检测）"
        self._refresh_account_new_count(account)
        self._record_monitor_history(account, True, account.status, 0)
        await self.persist()
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        return {"success": True, "reason": account.status, "new_items": []}

    async def _handle_profile_count_check(self, account: DouyinMonitorAccount, aweme_count: int, notify: bool = True) -> dict[str, Any]:
        now = self._now()
        previous_count = account.aweme_count if account.aweme_count >= 0 else account.last_aweme_count
        first_success = previous_count < 0 and not account.items and not account.known_item_ids
        delta = max(0, aweme_count - previous_count) if previous_count >= 0 else 0

        account.last_aweme_count = previous_count if previous_count >= 0 else aweme_count
        account.aweme_count = aweme_count
        account.last_success_time = now
        account.error_count = 0
        account.last_error = ""
        account.last_new_count = delta
        account.total_new_count += delta
        account.status = "已发现新作品" if delta else ("已建立初始基线" if first_success else "无更新")

        new_items: list[DouyinContentItem] = []
        if delta:
            item = DouyinContentItem(
                item_id=f"count-{aweme_count}-{int(time.time())}",
                title=f"作品数量增加 {delta} 个（当前 {aweme_count} 个）",
                share_url=account.homepage_url,
                publish_time="",
                first_seen_time=now,
                last_seen_time=now,
                status="count_only",
            )
            account.items.insert(0, item)
            account.items = account.items[:200]
            new_items.append(item)

        self._apply_account_retention(account)
        self._refresh_account_new_count(account)
        self._record_monitor_history(account, True, account.status, delta)
        await self.persist()
        self._write_detection_log(
            f"Checked Douyin account by profile count: name={account.display_name or account.douyin_nickname}, "
            f"aweme_count={aweme_count}, previous={previous_count}, new={delta}, url={account.homepage_url}"
        )
        if notify and account.notify_enabled and new_items:
            await self._notify_new_items(account, new_items)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        return {"success": True, "reason": account.status, "new_items": [item.to_dict() for item in new_items]}

    async def _handle_no_public_items_check(self, account: DouyinMonitorAccount) -> dict[str, Any]:
        account.status = "未识别到公开作品"
        account.last_error = "本次检测未从公开主页识别到作品 ID。可能是账号无公开作品、页面结构变化、登录限制或风控。"
        account.last_new_count = 0
        self._record_monitor_history(account, False, account.last_error, 0)
        await self.persist()
        self._write_detection_log(f"No public items detected: account={account.display_name}, url={account.homepage_url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "checked", "account_id": account.account_id})
        return {"success": False, "reason": account.last_error, "new_items": []}


    async def sync_accounts_batch(self, account_ids: list[str] | None = None, should_cancel=None) -> dict[str, Any]:
        targets = set(str(item) for item in account_ids or [] if str(item or "").strip())
        accounts = [account for account in list(self._accounts) if not targets or account.account_id in targets]
        if not accounts:
            return {"success": True, "total": 0, "success_count": 0, "failed_count": 0, "results": []}
        limit = self._monitor_batch_concurrency()
        sem = asyncio.Semaphore(limit)
        ordered: list[dict[str, Any] | None] = [None] * len(accounts)

        async def worker(index: int, account: DouyinMonitorAccount) -> None:
            if callable(should_cancel) and should_cancel():
                ordered[index] = {"account_id": account.account_id, "success": False, "reason": "用户已取消批量同步", "cancelled": True, "total": 0, "new": 0}
                return
            async with sem:
                if callable(should_cancel) and should_cancel():
                    ordered[index] = {"account_id": account.account_id, "success": False, "reason": "用户已取消批量同步", "cancelled": True, "total": 0, "new": 0}
                    return
                try:
                    result = await self.sync_account_works(account.account_id)
                except Exception as exc:
                    result = {"success": False, "reason": str(exc) or exc.__class__.__name__, "total": 0, "new": 0}
                ordered[index] = {"account_id": account.account_id, **result}

        await asyncio.gather(*(worker(index, account) for index, account in enumerate(accounts)))
        results = [item for item in ordered if isinstance(item, dict)]
        try:
            await self.flush_persist()
        except Exception as exc:
            logger.debug(f"flush monitor sync batch persistence failed: {exc}")
        success_count = len([item for item in results if item.get("success")])
        failed_count = len(results) - success_count
        new_total = 0
        for item in results:
            try:
                new_total += int(item.get("new") or 0)
            except (TypeError, ValueError):
                pass
        return {
            "success": failed_count == 0,
            "total": len(results),
            "success_count": success_count,
            "failed_count": failed_count,
            "new_total": new_total,
            "concurrency": limit,
            "results": results,
        }

    async def check_all_enabled(self, should_cancel=None) -> dict[str, Any]:
        if self._batch_check_lock.locked():
            return {"total": 0, "results": [], "reason": "已有批量检测任务正在运行"}
        async with self._batch_check_lock:
            return await self._check_all_enabled_locked(should_cancel=should_cancel)

    async def _check_all_enabled_locked(self, should_cancel=None) -> dict[str, Any]:
        accounts = [account for account in list(self._accounts) if account.monitor_enabled]
        return await self._run_bounded_monitor_batch(accounts, notify=True, reason_if_empty="没有启用监控的账号", should_cancel=should_cancel)

    async def check_due_enabled(self) -> dict[str, Any]:
        if self._batch_check_lock.locked():
            return {"total": 0, "results": [], "reason": "已有批量检测任务正在运行"}
        async with self._batch_check_lock:
            now_ts = time.time()
            accounts = [account for account in list(self._accounts) if self._account_check_due(account, now_ts)]
            return await self._run_bounded_monitor_batch(accounts, notify=True, reason_if_empty="暂无到期账号")

    async def _run_bounded_monitor_batch(
        self,
        accounts: list[DouyinMonitorAccount],
        *,
        notify: bool = True,
        reason_if_empty: str = "",
        should_cancel=None,
    ) -> dict[str, Any]:
        if not accounts:
            return {"total": 0, "results": [], "reason": reason_if_empty}
        limit = self._monitor_batch_concurrency()
        delay = self._between_users_delay()
        sem = asyncio.Semaphore(limit)
        ordered_results: list[dict[str, Any] | None] = [None] * len(accounts)

        async def worker(index: int, account: DouyinMonitorAccount) -> None:
            if callable(should_cancel) and should_cancel():
                ordered_results[index] = {"account_id": account.account_id, "success": False, "reason": "用户已取消批量检测", "cancelled": True}
                return
            if delay > 0 and index >= limit:
                await asyncio.sleep(delay * (index // max(1, limit)))
            async with sem:
                if callable(should_cancel) and should_cancel():
                    ordered_results[index] = {"account_id": account.account_id, "success": False, "reason": "用户已取消批量检测", "cancelled": True}
                    return
                result = await self.check_account(account.account_id, notify=notify)
                ordered_results[index] = {"account_id": account.account_id, **result}

        await asyncio.gather(*(worker(index, account) for index, account in enumerate(accounts)))
        results = [result for result in ordered_results if isinstance(result, dict)]
        try:
            await self.flush_persist()
        except Exception as exc:
            logger.debug(f"flush monitor batch persistence failed: {exc}")
        return {"total": len(results), "results": results, "concurrency": limit}

    def _monitor_batch_concurrency(self) -> int:
        try:
            value = int(self.settings.user_config.get("monitor_batch_concurrency", self.settings.user_config.get("douyin_content_monitor_batch_concurrency", 2)) or 2)
        except (TypeError, ValueError):
            value = 2
        return max(1, min(8, value))
