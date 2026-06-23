from __future__ import annotations

from .monitor_common import *


class ContentMonitorAccountMixin:
    def _load_accounts(self) -> None:
        loaded_accounts = self._account_repository.load_accounts(DouyinMonitorAccount.from_dict)
        self._accounts = self._dedupe_accounts(loaded_accounts)
        if len(self._accounts) != len(loaded_accounts):
            self._save_accounts_sync()
        logger.info(f"Douyin content monitor: loaded {len(self._accounts)} accounts")

    @staticmethod
    def _dedupe_accounts(accounts: list[DouyinMonitorAccount]) -> list[DouyinMonitorAccount]:
        deduped: list[DouyinMonitorAccount] = []
        by_url: dict[str, DouyinMonitorAccount] = {}
        for account in accounts:
            key = account.homepage_url.strip().rstrip("/")
            if not key:
                key = account.account_id
            existing = by_url.get(key)
            if existing is None:
                by_url[key] = account
                deduped.append(account)
                continue

            if not existing.display_name and account.display_name:
                existing.display_name = account.display_name
            if not existing.douyin_nickname and account.douyin_nickname:
                existing.douyin_nickname = account.douyin_nickname
            if not existing.avatar_url and account.avatar_url:
                existing.avatar_url = account.avatar_url
            existing.monitor_enabled = existing.monitor_enabled or account.monitor_enabled
            existing.notify_enabled = existing.notify_enabled or account.notify_enabled
            existing.total_new_count = max(existing.total_new_count, account.total_new_count)
            existing.last_new_count = max(existing.last_new_count, account.last_new_count)
            existing.aweme_count = max(existing.aweme_count, account.aweme_count)
            existing.last_aweme_count = max(existing.last_aweme_count, account.last_aweme_count)
            for item_id in account.known_item_ids:
                if item_id not in existing.known_item_ids:
                    existing.known_item_ids.append(item_id)
            existing_items = {item.item_id for item in existing.items}
            for item in account.items:
                if item.item_id not in existing_items:
                    existing.items.append(item)
                    existing_items.add(item.item_id)
        return deduped

    def _save_accounts_sync(self, accounts: list[dict[str, Any]] | None = None) -> None:
        if accounts is None:
            accounts = [account.to_dict() for account in self._accounts]
        self._account_repository.save_accounts(accounts)

    async def persist(self, force: bool = False) -> None:
        now = time.monotonic()
        if force or now - self._last_persist_at >= self._persist_debounce_seconds:
            if self._persist_task and not self._persist_task.done():
                self._persist_task.cancel()
            await self._persist_now()
            return
        self._schedule_persist()

    def _schedule_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            return
        try:
            self._persist_task = asyncio.create_task(self._delayed_persist())
        except RuntimeError:
            self._save_accounts_sync()

    async def _delayed_persist(self) -> None:
        await asyncio.sleep(self._persist_debounce_seconds)
        await self._persist_now()

    async def _persist_now(self) -> None:
        accounts = [account.to_dict() for account in self._accounts]
        async with self._persist_lock:
            await asyncio.to_thread(self._save_accounts_sync, accounts)
            self._last_persist_at = time.monotonic()

    async def flush_persist(self) -> None:
        if self._persist_task and not self._persist_task.done():
            self._persist_task.cancel()
        await self._persist_now()

    @staticmethod
    def normalize_homepage_url(raw_url: str) -> str:
        text = str(raw_url or "").strip()
        if not text:
            raise ValueError("请输入抖音主页链接")
        if not re.match(r"^https?://", text, re.IGNORECASE):
            text = "https://" + text
        parts = urlsplit(text)
        host = (parts.netloc or "").lower()
        if not host:
            raise ValueError("主页链接无效")
        if not DOUYIN_HOST_RE.search(host):
            raise ValueError("只支持公开抖音主页链接")
        # Keep path, remove query/fragment to reduce expired tracking params.
        return urlunsplit((parts.scheme or "https", parts.netloc, parts.path.rstrip("/") or "/", "", ""))

    def find_account(self, account_id: str) -> DouyinMonitorAccount | None:
        for account in self._accounts:
            if account.account_id == account_id:
                return account
        return None

    def _account_scan_lock(self, account_id: str) -> asyncio.Lock:
        key = str(account_id or "")
        lock = self._account_scan_locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._account_scan_locks[key] = lock
        return lock

    async def add_account(self, homepage_url: str, display_name: str = "") -> DouyinMonitorAccount:
        url = self.normalize_homepage_url(homepage_url)
        sec_uid = self.extract_sec_uid(url)
        provided_display_name = str(display_name or "").strip()
        async with self._lock:
            for account in self._accounts:
                account_sec_uid = self.extract_sec_uid(account.homepage_url)
                if account.homepage_url == url or (sec_uid and account_sec_uid == sec_uid):
                    if provided_display_name:
                        account.display_name = provided_display_name
                    elif not account.display_name or account.display_name == "抖音用户":
                        account.display_name = account.douyin_nickname or account.display_name or "抖音用户"
                    if account.homepage_url != url and sec_uid:
                        account.homepage_url = url
                    await self.persist(force=True)
                    return account
            account = DouyinMonitorAccount(
                account_id=uuid.uuid4().hex,
                homepage_url=url,
                display_name=provided_display_name or "抖音用户",
                notify_enabled=bool(self.settings.user_config.get("douyin_content_notify_enabled", True)),
                status="未监控",
            )
            self._accounts.append(account)
            await self.persist(force=True)
        self._write_detection_log(f"Added Douyin monitor account: {url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "added", "account_id": account.account_id})
        return account

    async def hydrate_account_display_name(self, account_id: str, *, force: bool = False) -> dict[str, Any]:
        account = self.find_account(account_id)
        if not account:
            return {"success": False, "reason": "账号不存在", "display_name": ""}
        display_name = str(account.display_name or "").strip()
        current_nickname = str(account.douyin_nickname or "").strip()
        looks_manual_name = bool(display_name and display_name != "抖音用户" and display_name != current_nickname)
        if not force and looks_manual_name:
            return {"success": True, "reason": "已使用手动备注", "display_name": account.display_name}

        nickname = ""
        avatar_url = ""
        try:
            page_text, final_url = await self.fetch_public_profile(account, include_cookie=False)
            self._safe_update_homepage_from_final_url(account, final_url)
            if self._public_profile_page_matches_account(account, page_text, final_url):
                nickname = self._extract_douyin_nickname(page_text)
            else:
                logger.debug(
                    "Skip Douyin nickname hydration because public profile page does not match target: "
                    f"account={account.account_id}, final_url={sanitize_url(final_url)}"
                )
        except Exception as exc:
            logger.debug(f"Hydrate Douyin display name by public profile failed: {exc}")

        if nickname:
            try:
                profile_info = await self.fetch_user_profile_info(account)
                if self._profile_info_matches_account(account, profile_info):
                    avatar_url = str(profile_info.get("avatar_url") or "").strip()
            except Exception as exc:
                logger.debug(f"Hydrate Douyin avatar by user info failed: {exc}")

        if nickname:
            account.douyin_nickname = nickname[:80]
            if force or not display_name or display_name == "抖音用户" or display_name == current_nickname:
                account.display_name = account.douyin_nickname
        if avatar_url:
            account.avatar_url = avatar_url
        if nickname or avatar_url:
            await self.persist(force=True)
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "account_profile", "account_id": account_id})
            return {"success": True, "reason": "已自动填充抖音昵称", "display_name": account.display_name}
        if force and (not display_name or display_name == "抖音用户" or display_name == current_nickname):
            changed = False
            if current_nickname:
                account.douyin_nickname = ""
                changed = True
            if account.display_name != "抖音用户":
                account.display_name = "抖音用户"
                changed = True
            if changed:
                await self.persist(force=True)
                self.services.broadcast_pubsub("douyin_monitor_update", {"event": "account_profile", "account_id": account_id})
            return {"success": False, "reason": "暂未获取到目标主页昵称，已避免使用 Cookie 账号昵称", "display_name": account.display_name}
        return {"success": False, "reason": "暂未获取到抖音昵称", "display_name": account.display_name}

    def _profile_info_matches_account(self, account: DouyinMonitorAccount, profile_info: dict[str, Any]) -> bool:
        """Return true only when API profile data clearly belongs to this monitored account.

        Some Douyin user-info endpoints may return the logged-in Cookie owner
        under risk-control or parameter issues.  Auto-naming must never use that
        ambiguous data for a newly added monitor target.
        """

        if not isinstance(profile_info, dict) or not profile_info:
            return False
        target_sec_uid = self.extract_sec_uid(account.homepage_url)
        if not target_sec_uid:
            return False
        for key in ("sec_uid", "secUid", "sec_user_id", "secUserId"):
            value = str(profile_info.get(key) or "").strip()
            if value and value == target_sec_uid:
                return True
        return False

    def _safe_update_homepage_from_final_url(self, account: DouyinMonitorAccount, final_url: str) -> bool:
        """Update homepage only when a redirect still points to this target user.

        Cookie-authenticated Douyin requests can occasionally land on the logged-in
        user or another interstitial page.  A monitor target must never be
        re-pointed to that page, otherwise later auto-naming can inherit the
        Cookie owner's identity.
        """

        if not final_url:
            return False
        try:
            normalized = self.normalize_homepage_url(final_url)
        except Exception:
            return False
        current_sec_uid = self.extract_sec_uid(account.homepage_url)
        final_sec_uid = self.extract_sec_uid(normalized)
        if current_sec_uid:
            if final_sec_uid and final_sec_uid == current_sec_uid:
                account.homepage_url = normalized
                return True
            return False
        if final_sec_uid:
            account.homepage_url = normalized
            return True
        return False

    def _public_profile_page_matches_account(self, account: DouyinMonitorAccount, page_text: str, final_url: str = "") -> bool:
        """Return true only when fetched profile HTML can be tied to the target."""

        target_sec_uid = self.extract_sec_uid(account.homepage_url)
        if not target_sec_uid:
            return True
        final_sec_uid = self.extract_sec_uid(final_url)
        if final_sec_uid:
            return final_sec_uid == target_sec_uid
        return target_sec_uid in str(page_text or "")

    @staticmethod
    def _auto_fill_display_name(account: DouyinMonitorAccount) -> None:
        if account.douyin_nickname and (not account.display_name or account.display_name == "抖音用户"):
            account.display_name = account.douyin_nickname

    async def delete_account(self, account_id: str) -> bool:
        async with self._lock:
            account = self.find_account(account_id)
            if not account:
                return False
            self._accounts.remove(account)
            self._account_scan_locks.pop(account_id, None)
            await self.persist(force=True)
        self._write_detection_log(f"Deleted Douyin monitor account: {account.homepage_url}")
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "deleted", "account_id": account_id})
        return True


    async def delete_accounts_batch(self, account_ids: list[str]) -> dict[str, Any]:
        requested = [str(item) for item in account_ids if str(item or "").strip()]
        deleted: list[str] = []
        async with self._lock:
            id_set = set(requested)
            kept = []
            for account in self._accounts:
                if account.account_id in id_set:
                    deleted.append(account.account_id)
                    self._account_scan_locks.pop(account.account_id, None)
                else:
                    kept.append(account)
            if deleted:
                self._accounts = kept
                await self.persist(force=True)
        if deleted:
            self._write_detection_log(f"Batch deleted Douyin monitor accounts: count={len(deleted)}")
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "batch_deleted", "account_ids": deleted})
        return {"success": True, "requested": len(requested), "deleted": len(deleted), "account_ids": deleted}

    async def set_monitor_enabled_batch(self, account_ids: list[str] | None, enabled: bool) -> dict[str, Any]:
        target_ids = set(str(item) for item in account_ids or [] if str(item or "").strip())
        changed: list[str] = []
        async with self._lock:
            for account in self._accounts:
                if target_ids and account.account_id not in target_ids:
                    continue
                if account.monitor_enabled == bool(enabled):
                    continue
                account.monitor_enabled = bool(enabled)
                account.status = "等待检测" if enabled else "已停止监控"
                changed.append(account.account_id)
            if changed:
                await self.persist(force=True)
        if changed:
            self.services.broadcast_pubsub(
                "douyin_monitor_update",
                {"event": "batch_monitor_status", "enabled": bool(enabled), "account_ids": changed},
            )
        return {"success": True, "total": len(changed), "account_ids": changed}

    async def restore_accounts(self, account_data: list[dict[str, Any]]) -> int:
        restored = 0
        async with self._lock:
            existing_ids = {account.account_id for account in self._accounts}
            existing_urls = {account.homepage_url for account in self._accounts}
            for data in account_data:
                account = DouyinMonitorAccount.from_dict(data)
                if account.account_id in existing_ids or account.homepage_url in existing_urls:
                    continue
                self._accounts.append(account)
                existing_ids.add(account.account_id)
                existing_urls.add(account.homepage_url)
                restored += 1
            if restored:
                await self.persist(force=True)
        if restored:
            self.services.broadcast_pubsub("douyin_monitor_update", {"event": "restored", "count": restored})
        return restored

    async def update_account_settings(
        self,
        account_id: str,
        *,
        display_name: str | None = None,
        group_name: str | None = None,
        auto_download_policy: str | None = None,
        monitor_interval_minutes: float | None = None,
        auto_sync_enabled: bool | None = None,
        auto_pause_failures: int | None = None,
        keep_recent_count: int | None = None,
        notify_mode: str | None = None,
        notify_enabled: bool | None = None,
    ) -> bool:
        account = self.find_account(account_id)
        if not account:
            return False
        if display_name is not None:
            account.display_name = str(display_name or "").strip() or account.display_name
        if group_name is not None:
            account.group_name = str(group_name or "").strip()
        if auto_download_policy is not None:
            policy = str(auto_download_policy or "none").strip()
            account.auto_download_policy = policy if policy in {"none", "video", "gallery", "all"} else "none"
        if monitor_interval_minutes is not None:
            try:
                account.monitor_interval_minutes = max(0.0, float(monitor_interval_minutes or 0))
            except (TypeError, ValueError):
                account.monitor_interval_minutes = 0.0
        if auto_sync_enabled is not None:
            account.auto_sync_enabled = bool(auto_sync_enabled)
        if auto_pause_failures is not None:
            try:
                account.auto_pause_failures = max(0, int(auto_pause_failures or 0))
            except (TypeError, ValueError):
                account.auto_pause_failures = 0
        if keep_recent_count is not None:
            try:
                account.keep_recent_count = max(0, int(keep_recent_count or 0))
            except (TypeError, ValueError):
                account.keep_recent_count = 0
        if notify_mode is not None:
            mode = str(notify_mode or "desktop")
            account.notify_mode = mode if mode in {"desktop", "task", "silent"} else "desktop"
        if notify_enabled is not None:
            account.notify_enabled = bool(notify_enabled)
        await self.persist(force=True)
        self.services.broadcast_pubsub("douyin_monitor_update", {"event": "account_settings", "account_id": account_id})
        return True

    async def start_all(self) -> dict[str, Any]:
        return await self.set_monitor_enabled_batch(None, True)

    async def stop_all(self) -> dict[str, Any]:
        return await self.set_monitor_enabled_batch(None, False)

    def snapshot(self) -> dict[str, Any]:
        return {
            "account_count": len(self._accounts),
            "enabled_count": len([a for a in self._accounts if a.monitor_enabled]),
            "last_check_time": max([a.last_check_time for a in self._accounts if a.last_check_time] or [""]),
            "log_path": sanitize_text(self.log_path),
        }
