from __future__ import annotations

from .monitor_common import *


class ContentMonitorBaseMixin:
    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @classmethod
    def sort_items_newest_first(cls, items: list[DouyinContentItem]) -> list[DouyinContentItem]:
        return sorted(items, key=cls._item_sort_key, reverse=True)

    @classmethod
    def _item_sort_key(cls, item: DouyinContentItem) -> tuple[int, float, float, int]:
        publish_ts = cls._parse_time_for_sort(item.publish_time)
        first_seen_ts = cls._parse_time_for_sort(item.first_seen_time)
        item_id_value = cls._parse_int(item.item_id, 0)
        return (
            1 if publish_ts > 0 else 0,
            publish_ts,
            first_seen_ts,
            item_id_value,
        )

    @staticmethod
    def _parse_time_for_sort(value: str) -> float:
        text = str(value or "").strip()
        if not text or text == "-":
            return 0.0
        if text.isdigit():
            try:
                return float(int(text[:10]))
            except Exception:
                return 0.0
        normalized = text.replace("T", " ").replace("/", "-")
        if normalized.endswith("Z"):
            normalized = normalized[:-1]
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
            try:
                return datetime.strptime(normalized[: len(fmt)], fmt).timestamp()
            except ValueError:
                continue
        try:
            return datetime.fromisoformat(normalized).timestamp()
        except Exception:
            return 0.0

    def _account_interval_seconds(self, account: DouyinMonitorAccount) -> float:
        minutes = float(getattr(account, "monitor_interval_minutes", 0.0) or 0.0)
        if minutes <= 0:
            minutes = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        return max(60.0, minutes * 60.0)

    def _account_check_due(self, account: DouyinMonitorAccount, now_ts: float | None = None) -> bool:
        if not account.monitor_enabled:
            return False
        if now_ts is None:
            now_ts = time.time()
        last_ts = self._parse_time_for_sort(account.last_check_time)
        return last_ts <= 0 or now_ts - last_ts >= self._account_interval_seconds(account)

    def _record_monitor_history(self, account: DouyinMonitorAccount, success: bool, detail: str, new_count: int = 0) -> None:
        history = list(getattr(account, "monitor_history", []) or [])
        history.append(
            {
                "time": self._now(),
                "success": bool(success),
                "new": max(0, int(new_count or 0)),
                "detail": sanitize_text(str(detail or ""))[:300],
                "error_count": int(getattr(account, "error_count", 0) or 0),
            }
        )
        account.monitor_history = history[-100:]

    def _apply_account_retention(self, account: DouyinMonitorAccount) -> None:
        self._merge_service.apply_retention(account)

    @staticmethod
    def _is_pending_new_marker(item: DouyinContentItem) -> bool:
        return str(getattr(item, "status", "") or "") in {"new", "count_only"}

    def _refresh_account_new_count(self, account: DouyinMonitorAccount) -> int:
        count = sum(1 for item in getattr(account, "items", []) if self._is_pending_new_marker(item))
        account.last_new_count = count
        return count

    def _auto_pause_if_needed(self, account: DouyinMonitorAccount) -> bool:
        return self._merge_service.auto_pause_if_needed(account)

    def _write_detection_log(self, message: str) -> None:
        try:
            Path(self.log_path).parent.mkdir(parents=True, exist_ok=True)
            line = f"{self._now()} | {sanitize_text(message)}\n"
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(line)
        except Exception as exc:
            logger.debug(f"Douyin monitor log write failed: {exc}")

    def _interval_seconds(self) -> int:
        try:
            minutes = float(self.settings.user_config.get("douyin_content_monitor_interval_minutes", 10) or 10)
        except (TypeError, ValueError):
            minutes = 10
        return max(60, int(minutes * 60))

    def _between_users_delay(self) -> float:
        try:
            value = float(self.settings.user_config.get("douyin_content_check_interval_between_users_seconds", 3) or 3)
        except (TypeError, ValueError):
            value = 3
        return max(0.0, value)

    def _request_timeout(self) -> float:
        try:
            value = float(self.settings.user_config.get("douyin_content_request_timeout_seconds", 15) or 15)
        except (TypeError, ValueError):
            value = 15
        return max(5.0, value)

    def _external_api_base_url(self) -> str:
        return str(self.settings.user_config.get("douyin_external_api_base_url") or "").strip()

    def _parser_backend(self) -> str:
        configured = str(self.settings.user_config.get("douyin_parser_backend") or "").strip().lower()
        if configured in {"internal", "external"}:
            return configured
        return "external" if self._external_api_base_url() else "internal"

    def _parser_max_pages(self) -> int:
        value = self.settings.user_config.get("douyin_parser_max_pages")
        if value in (None, ""):
            value = self.settings.user_config.get("douyin_external_api_max_pages")
        return self._parse_int(value, 20)

    async def _resolve_parser_backend(self) -> str:
        backend = self._parser_backend()
        if backend == "external":
            base_url = self._external_api_base_url()
            if not base_url:
                raise ValueError("已选择外部解析器，但未配置 douyin_external_api_base_url")
            return f"external:{base_url.rstrip('/')}"
        return "internal"

    async def _resolve_external_api_base_url(self) -> str:
        """Backward-compatible wrapper for older call sites/settings names."""
        configured = self._external_api_base_url()
        if configured:
            return configured.rstrip("/")
        return "__internal_video_parser__"

    def _external_api_max_pages(self) -> int:
        return self._parser_max_pages()

    def _headers(self, *, include_cookie: bool = True) -> dict[str, str]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }
        if include_cookie:
            cookie = self._select_douyin_cookie()
            if cookie:
                headers["Cookie"] = cookie
        return headers

    def _headers_for_cookie_request(self, *, include_cookie: bool = True) -> tuple[dict[str, str], str]:
        headers = self._headers(include_cookie=False)
        cookie = self._select_douyin_cookie() if include_cookie else ""
        if cookie:
            headers["Cookie"] = cookie
        return headers, cookie
