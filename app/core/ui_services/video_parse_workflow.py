from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from ..media.video_parser_service import VideoParseBatchResult, VideoParserService
from ...utils.logger import logger


class VideoParseWorkflow:
    """Video-parse UI workflow: URL extraction and parse-history persistence."""

    def __init__(self, app: Any):
        self.app = app

    def extract_urls(self, text: str) -> list[str]:
        parser = getattr(self.app.services, "video_parser", None)
        extractor = getattr(parser, "extract_urls", None)
        if callable(extractor):
            return list(dict.fromkeys(extractor(text)))
        return list(dict.fromkeys(VideoParserService.extract_urls(text)))

    def history_path(self) -> Path:
        return Path(self.app.run_path, "config", "parse_history.json")

    def load_history(self) -> list[dict[str, Any]]:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                if store.parse_history_count() > 0:
                    return store.load_parse_history(limit=50)
            except Exception as exc:
                logger.debug(f"load parse history from sqlite failed: {exc}")
        path = self.history_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = data.get("records", data) if isinstance(data, dict) else data
            history = [record for record in records if isinstance(record, dict)][:50]
            if store is not None and history:
                try:
                    store.save_parse_history(history, max_records=50)
                except Exception as exc:
                    logger.debug(f"migrate parse history to sqlite failed: {exc}")
            return history
        except Exception:
            return []

    def save_history(self, records: list[dict[str, Any]]) -> None:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                store.save_parse_history(records[:50], max_records=50)
            except Exception as exc:
                logger.debug(f"save parse history to sqlite failed: {exc}")
        try:
            path = self.history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"records": records[:50]}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"save parse history failed: {exc}")

    def append_history(self, records: list[dict[str, Any]], result: VideoParseBatchResult, cancelled: bool) -> list[dict[str, Any]]:
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已取消" if cancelled else ("完成" if result.failed_count == 0 else "有失败"),
            "total": result.total_count,
            "success": result.success_count,
            "failed": result.failed_count,
            "work_links": [item.source_url for item in result.successes if item.source_url][:100],
            "failed_links": [failure.source_url for failure in result.failures][:100],
        }
        updated = [record, *records]
        updated = updated[:50]
        self.save_history(updated)
        return updated
