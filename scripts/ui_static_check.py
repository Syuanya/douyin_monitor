from __future__ import annotations

import ast
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


REQUIRED_PAGES = {
    "HomeDashboardPage": "app/ui/views/home_dashboard_view.py",
    "DouyinContentMonitorPage": "app/ui/views/douyin_content_view.py",
    "VideoParsePage": "app/ui/views/video_parse_view.py",
    "TaskCenterPage": "app/ui/views/task_center_view.py",
    "DownloadHistoryPage": "app/ui/views/download_history_view.py",
    "IssueCenterPage": "app/ui/views/issue_center_view.py",
    "SettingsPage": "app/ui/views/settings_view.py",
    "StoragePage": "app/ui/views/storage_view.py",
    "DiagnosticHealthPage": "app/ui/views/diagnostic_health_view.py",
}


def class_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {node.name for node in ast.walk(tree) if isinstance(node, ast.ClassDef)}


def main() -> int:
    errors: list[str] = []
    for class_name, relative in REQUIRED_PAGES.items():
        path = ROOT / relative
        if not path.exists():
            errors.append(f"missing page file: {relative}")
            continue
        if class_name not in class_names(path):
            errors.append(f"missing class {class_name} in {relative}")

    app_file = ROOT / "app/standalone/douyin_monitor_app.py"
    app_text = app_file.read_text(encoding="utf-8")
    for marker in ("home_dashboard", "issue_center_page", "download_history_page", "switch_page"):
        if marker not in app_text:
            errors.append(f"navigation marker missing: {marker}")
    if "dict.fromkeys(targets)" in app_text:
        errors.append("overlay hard clear uses hash-based dedupe; Flet controls may be unhashable")

    base_page_text = (ROOT / "app/ui/base_page.py").read_text(encoding="utf-8")
    for marker in ("copy_to_clipboard", "open_path_or_url", "show_dialog", "close_dialog", "is_active_page", "safe_content_update"):
        if marker not in base_page_text:
            errors.append(f"base UI helper missing: {marker}")
    if "**kwargs" not in base_page_text or "kwargs.get(\"error\")" not in base_page_text:
        errors.append("base open_path_or_url should tolerate legacy error= alias")
    settings_view_text = (ROOT / "app/ui/views/settings_view.py").read_text(encoding="utf-8")
    if "open_path_or_url(\n            path," in settings_view_text and "error=self._.get(\"storage_open_failed\"" in settings_view_text:
        errors.append("settings open storage button uses invalid open_path_or_url error= argument")
    if "storage_dir_picker" in settings_view_text or "_ensure_storage_dir_picker" in settings_view_text:
        errors.append("settings storage directory picker must not use Flet FilePicker state; it can cause silent or double dialogs")
    if "get_directory_path" in settings_view_text:
        errors.append("settings storage directory picker must not use Flet get_directory_path")
    for marker in ("_choose_storage_dir_windows_sync", "powershell.exe", "FolderBrowserDialog"):
        if marker not in settings_view_text:
            errors.append(f"settings Windows native storage picker marker missing: {marker}")
    if "if sys.platform.startswith(\"win\"):\n            return self._choose_storage_dir_windows_sync()" not in settings_view_text:
        errors.append("settings storage picker should use exactly one native picker per click on Windows")
    for marker in (
        "self.selected_download_path",
        "on_change=self.update_download_path_state",
        "def update_download_path_state",
        'download_path = (self.download_path_field.value if self.download_path_field else "") or self.selected_download_path or ""',
        "apply_storage_dir",
        "_persist_download_path",
        "await self._persist_download_path(selected)",
        "saved_user_config = self.app.services.config_manager.load_user_config()",
        "saved_download_path != download_path",
    ):
        if marker not in settings_view_text:
            errors.append(f"settings download path save verification marker missing: {marker}")
    if "download_path = self.selected_download_path or" in settings_view_text:
        errors.append("settings save must not prefer stale selected_download_path over the visible text field")
    if "on_click=lambda e: self.run_async(self.open_storage_dir())" in settings_view_text:
        errors.append("settings storage button should choose a folder, not open the current folder")
    if "on_click=lambda e: self.run_async(self.choose_storage_dir())" not in settings_view_text:
        errors.append("settings storage picker should be triggered through run_async")
    ensure_config_block = settings_view_text.split("def _ensure_config_import_picker", 1)[1].split("def pick_config_package", 1)[0]
    if "self.storage_dir_picker = None" in ensure_config_block:
        errors.append("config import picker must not clear the storage directory picker")
    if "logger.debug(f\"create config import picker failed: {exc}\")\n        self.config_import_picker = None" in ensure_config_block:
        errors.append("config import picker should clear itself only inside the exception block")
    logger_text = (ROOT / "app/utils/logger.py").read_text(encoding="utf-8")
    for marker in ("sanitize_log_text", "_sanitize_record", "DOUYIN_MONITOR_CONSOLE_LEVEL", "DOUYIN_MONITOR_LOG_MESSAGE_LIMIT", "logger.remove()"):
        if marker not in logger_text:
            errors.append(f"log output optimization marker missing: {marker}")

    crawler_utils_text = (ROOT / "crawlers/utils/utils.py").read_text(encoding="utf-8")
    if "\nimport importlib_resources" in crawler_utils_text:
        errors.append("crawler utils should prefer stdlib importlib.resources before importlib_resources fallback")
    douyin_crawler_config = (ROOT / "crawlers/douyin/web/config.yaml").read_text(encoding="utf-8")
    if "Cookie: ''" not in douyin_crawler_config:
        errors.append("douyin crawler config should not contain a persisted Cookie")
    for marker in ("msToken:", "ttwid:", "proxies:"):
        if marker not in douyin_crawler_config:
            errors.append(f"douyin crawler config missing non-sensitive default block: {marker}")
    douyin_web_utils_text = (ROOT / "crawlers/douyin/web/utils.py").read_text(encoding="utf-8")
    douyin_web_crawler_text = (ROOT / "crawlers/douyin/web/web_crawler.py").read_text(encoding="utf-8")
    if 'config.get("TokenManager").get("douyin")' in douyin_web_utils_text:
        errors.append("douyin web utils should not chain config.get without None fallback")
    if 'config["TokenManager"]["douyin"]' in douyin_web_crawler_text:
        errors.append("douyin web crawler should not subscript optional config nodes")

    home_dashboard_text = (ROOT / "app/ui/views/home_dashboard_view.py").read_text(encoding="utf-8")
    for marker in ("today_downloads", "failure_rate", "disk_free", "queue_running_labels", "_disk_usage_text"):
        if marker not in home_dashboard_text:
            errors.append(f"home dashboard runtime marker missing: {marker}")

    content_view_text = (ROOT / "app/ui/views/douyin_content_view.py").read_text(encoding="utf-8")
    content_monitor_text = (ROOT / "app/core/content_monitor/douyin_content_monitor.py").read_text(encoding="utf-8")
    if "def _is_active_page" not in content_view_text or "if not self._is_active_page():" not in content_view_text:
        errors.append("douyin content render guard missing: background downloads may redraw another page")
    if "self.content_area.update()" in content_view_text:
        errors.append("douyin content view should use safe_content_update to avoid background redraws")
    if "VideoPlayer(self.app).preview_video" not in content_view_text:
        errors.append("douyin content video preview should use the legacy modal VideoPlayer")
    if "export_monitor_accounts_csv" not in content_view_text or "douyin_monitor_accounts_" not in content_view_text:
        errors.append("douyin content account-level monitor export missing")
    if 'copy_source_url=result.get("copy_source_url") or source_url' not in content_view_text:
        errors.append("douyin content preview should preserve original direct URL when cached locally")
    if "create_content_video_preview" in content_view_text or "content_video_preview" in content_view_text:
        errors.append("douyin content inline video preview should be disabled; storage owns inline switching")
    if "webbrowser.open" in content_view_text:
        errors.append("douyin content view should use PageBase.open_path_or_url instead of direct webbrowser.open")
    for marker in (
        "pending_account_scroll_anchor_id",
        "account_scroll_anchor_hold_until",
        "restore_pending_account_scroll_position",
        "_account_anchor_offset",
        "scroll_to(offset=offset",
    ):
        if marker not in content_view_text:
            errors.append(f"douyin content return scroll marker missing: {marker}")
    for marker in ("_video_search_roots", "root.rglob(pattern)"):
        if marker not in content_monitor_text:
            errors.append(f"douyin content local video lookup marker missing: {marker}")
    if "sanitize_cookie_header" not in content_monitor_text:
        errors.append("content monitor should sanitize Cookie before sending requests")
    if "检测异常：未识别到公开作品" in content_monitor_text:
        errors.append("content monitor should not mark parser-empty public pages as detection exceptions")
    if "_handle_no_public_items_check" not in content_monitor_text:
        errors.append("content monitor no-public-items fallback missing")

    video_parse_text = (ROOT / "app/ui/views/video_parse_view.py").read_text(encoding="utf-8")
    video_parser_service_text = (ROOT / "app/core/media/video_parser_service.py").read_text(encoding="utf-8")
    if "VideoPlayer(self.app).preview_video" not in video_parse_text:
        errors.append("video parse preview should use the legacy modal VideoPlayer")
    if "webbrowser.open" in video_parse_text or "set_clipboard" in video_parse_text:
        errors.append("video parse view should use PageBase open/copy helpers")
    if "def _is_active_page" not in video_parse_text or "if not self._is_active_page():" not in video_parse_text:
        errors.append("video parse render guard missing: background parsing may redraw another page")
    if "self.content_area.update()" in video_parse_text:
        errors.append("video parse view should use safe_content_update to avoid background redraws")
    if "controls.append(self.result_area)" not in video_parse_text or "controls.extend(self.result_controls)" in video_parse_text:
        errors.append("video parse results should be mounted as one stable result_area to preserve scrolling")
    if "sanitize_cookie_header(cookie)" not in video_parser_service_text:
        errors.append("video parser service should sanitize Cookie before writing crawler config")
    if "if not isinstance(page, dict):" not in video_parser_service_text:
        errors.append("video parser service should guard non-dict user post responses")
    if "cache_video_preview" not in video_parse_text:
        errors.append("video parse preview should cache remote direct videos before local playback")

    video_player_text = (ROOT / "app/ui/components/business/video_player.py").read_text(encoding="utf-8")
    if "dict.fromkeys(targets)" in video_player_text:
        errors.append("video preview hard close uses hash-based dedupe; Flet controls may be unhashable")
    if "preview_video_playlist" in video_player_text or "switch_playlist_video" in video_player_text:
        errors.append("legacy VideoPlayer must not contain storage playlist switching")
    if "previous_callback" in video_player_text or "next_callback" in video_player_text:
        errors.append("legacy VideoPlayer must not contain previous/next callback switching")
    if "_close_dialog_hard" in video_player_text or "_detach_video_from_dialog" in video_player_text:
        errors.append("legacy VideoPlayer should not contain hard-close overlay rewrite")
    if "ok = await self._open_url(room_url or \"\")" not in video_player_text:
        errors.append("Douyin playback button should open the original work page")
    if "ok = await self._open_url(playback_source)" not in video_player_text:
        errors.append("browser playback button should keep opening the video direct URL")
    if "browser_target = playback_source if is_file_path else" in video_player_text:
        errors.append("browser playback must not silently redirect remote videos to Douyin page")
    parsed_downloader_text = (ROOT / "app/core/media/parsed_media_downloader.py").read_text(encoding="utf-8")
    for marker in ("cache_video_preview", "_preview_cache_path", '"cache", "video_previews"'):
        if marker not in parsed_downloader_text:
            errors.append(f"parsed media preview cache marker missing: {marker}")
    storage_view_text = (ROOT / "app/ui/views/storage_view.py").read_text(encoding="utf-8")
    if "webbrowser.open" in storage_view_text:
        errors.append("storage view should use PageBase.open_path_or_url instead of direct webbrowser.open")
    if "ft.alignment.center" in storage_view_text:
        errors.append("storage view uses incompatible ft.alignment.center; use ft.alignment.Alignment.CENTER")
    if (
        "_video_preview_window" not in storage_view_text
        or "_show_storage_video_preview" not in storage_view_text
        or "_remove_storage_video_preview" not in storage_view_text
        or "switch_storage_video" not in storage_view_text
        or "close_storage_video_preview" not in storage_view_text
    ):
        errors.append("storage floating video preview missing: close/switch should use storage-owned overlay")
    if "controls.append(video_preview)" in storage_view_text:
        errors.append("storage video preview should not be inserted into the file list")
    if "video_preview_dialog" in storage_view_text:
        errors.append("storage video preview should not keep AlertDialog state; use a plain overlay control")
    preview_window_block = storage_view_text.split("def _video_preview_window", 1)[1].split("def _show_storage_video_preview", 1)[0]
    if "AlertDialog" in preview_window_block:
        errors.append("storage video preview window must be a plain overlay, not AlertDialog")
    if "on_dismiss=lambda e: self.run_async(self.close_storage_video_preview())" in storage_view_text:
        errors.append("storage floating video preview should not close from AlertDialog.on_dismiss during overlay rebuild")
    if "_rebuilding_video_preview" not in storage_view_text:
        errors.append("storage floating video preview rebuild guard missing")
    if (
        "preview_video_playlist" in storage_view_text
        or "previous_callback=previous_video" in storage_view_text
        or "VideoPlayer(self.app).preview_video" in storage_view_text
    ):
        errors.append("storage video preview must not use modal VideoPlayer recursion")
    for marker in (
        "media_select_mode",
        "selected_media_paths",
        "toggle_media_select_mode",
        "select_all_visible_media",
        "delete_selected_media",
    ):
        if marker not in storage_view_text:
            errors.append(f"storage batch management marker missing: {marker}")
    for marker in (
        "_collect_images",
        "_collect_visible_images",
        "_preview_images_for",
        "recursive=True",
        "_image_sort_key",
        "_gallery_id_from_image",
        "_filter_gallery_images",
        "dedupe=False",
        '".avif"',
    ):
        if marker not in storage_view_text:
            errors.append(f"storage image gallery marker missing: {marker}")
    image_preview_text = (ROOT / "app/ui/components/business/image_preview_dialog.py").read_text(encoding="utf-8")
    if "dedupe: bool = True" not in image_preview_text:
        errors.append("image preview dialog should allow storage to disable URL identity dedupe")

    if not (ROOT / "crawlers/utils/httpx_compat.py").exists():
        errors.append("httpx compatibility helper missing")
    for relative in (
        "crawlers/base_crawler.py",
        "crawlers/douyin/web/utils.py",
        "crawlers/tiktok/web/utils.py",
    ):
        text = (ROOT / relative).read_text(encoding="utf-8")
        if "httpx.Client(transport=transport, proxies=" in text or "httpx.AsyncClient(\n                transport=transport, proxies=" in text or "httpx.AsyncClient(\n                    transport=transport, proxies=" in text:
            errors.append(f"{relative} still passes deprecated proxies= directly to httpx")
    base_crawler_text = (ROOT / "crawlers/base_crawler.py").read_text(encoding="utf-8")
    if "_safe_url_for_log" not in base_crawler_text or "_empty_response_message" not in base_crawler_text:
        errors.append("base crawler should redact long signed URLs in retry logs")
    if "response.url)" in base_crawler_text and "_safe_url_for_log(str(getattr(response, \"url\", \"\")))" not in base_crawler_text:
        errors.append("base crawler may still log raw response.url")
    douyin_utils_text = (ROOT / "crawlers/douyin/web/utils.py").read_text(encoding="utf-8")
    if 'logger.error("请求Douyin msToken API' in douyin_utils_text:
        errors.append("douyin msToken fallback should not be logged as ERROR")
    if 'logger.warning("请求Douyin msToken API失败' in douyin_utils_text:
        errors.append("douyin msToken fallback should not be logged as WARNING")
    if 'logger.info("将使用本地生成的虚假msToken' in douyin_utils_text:
        errors.append("douyin msToken fallback continuation message should be DEBUG only")
    if "logger.debug(self._empty_response_message(attempt + 1, response))" not in base_crawler_text:
        errors.append("base crawler should log intermediate empty-response retries at DEBUG")
    if "logger.debug(e.display_error())" not in base_crawler_text or "raise\n\n    async def post_fetch_data" not in base_crawler_text:
        errors.append("base crawler should re-raise APIError instead of returning None and logging NoneType errors")

    task_center_text = (ROOT / "app/core/runtime/task_center.py").read_text(encoding="utf-8")
    task_view_text = (ROOT / "app/ui/views/task_center_view.py").read_text(encoding="utf-8")
    queue_text = (ROOT / "app/core/runtime/media_task_queue.py").read_text(encoding="utf-8")
    for marker in ("TASK_STATUS_RUNNING", "TASK_STATUS_COMPLETED", "TASK_STATUS_FAILED", "TASK_STATUS_CANCELLED", "TASK_STATUS_WAITING"):
        if marker not in task_center_text or marker not in task_view_text:
            errors.append(f"task status constant not wired: {marker}")
    for marker in ("_queue_summary_card", "running_labels", "waiting_labels"):
        if marker not in task_view_text and marker not in queue_text:
            errors.append(f"queue visibility marker missing: {marker}")
    for marker in ('"retryable"', '"today"', '"downloading"', "_record_time"):
        if marker not in task_view_text:
            errors.append(f"task quick filter marker missing: {marker}")
    if "self.records_area = ft.Column(controls=[], spacing=8, expand=True)" in task_view_text:
        errors.append("task center records area must not use expand=True inside a scrollable content area")
    if "ft.VerticalDivider(width=12)" in task_view_text:
        errors.append("task center toolbar must not use VerticalDivider in wrapped rows; it can stretch the page into a grey block")
    for marker in ("_filter_group", "height=30", "border_radius=15"):
        if marker not in task_view_text:
            errors.append(f"task center compact filter marker missing: {marker}")

    settings_text = (ROOT / "app/ui/views/settings_view.py").read_text(encoding="utf-8")
    for marker in ("DOWNLOAD_STRATEGIES", "download_strategy_dropdown", "max_parallel_downloads_field", "apply_download_strategy", '"download_strategy_preset"', '"max_parallel_downloads"'):
        if marker not in settings_text:
            errors.append(f"settings download strategy marker missing: {marker}")
    if "on_change=self.apply_download_strategy" in settings_text:
        errors.append("settings download strategy must not pass on_change to Dropdown; current Flet build rejects it")
    if "应用策略" not in settings_text:
        errors.append("settings download strategy apply button missing")
    if "parse_cookie_pool(raw_douyin_cookie)" not in settings_text:
        errors.append("settings page should parse and sanitize Douyin Cookie pool before saving")

    diagnostic_text = (ROOT / "app/ui/views/diagnostic_health_view.py").read_text(encoding="utf-8")
    for marker in ("check_python_runtime", "check_disk_space", "check_download_strategy", "_safe_int_config", "sanitize_cookie_header", "shutil.disk_usage"):
        if marker not in diagnostic_text:
            errors.append(f"diagnostic environment marker missing: {marker}")

    if errors:
        print("ui_static_check: failed", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1
    print("ui_static_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
