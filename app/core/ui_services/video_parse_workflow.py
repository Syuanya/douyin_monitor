from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
import uuid

from ..media.video_parser_service import VideoParseBatchResult, VideoParserService
from ...utils.logger import logger


class VideoParseWorkflow:
    """Video-parse UI workflow: URL extraction, resource-library and parse-history persistence."""

    HISTORY_LIMIT = 200

    def __init__(self, app: Any):
        self.app = app

    def extract_urls(self, text: str) -> list[str]:
        parser = getattr(self.app.services, "video_parser", None)
        extractor = getattr(parser, "extract_urls", None)
        if callable(extractor):
            return list(dict.fromkeys(extractor(text)))
        return list(dict.fromkeys(VideoParserService.extract_urls(text)))

    def extract_url_report(self, text: str) -> dict[str, Any]:
        parser = getattr(self.app.services, "video_parser", None)
        reporter = getattr(parser, "extract_url_report", None)
        if callable(reporter):
            report = reporter(text)
        else:
            report = VideoParserService.extract_url_report(text)
        urls = list(dict.fromkeys(str(url) for url in report.get("urls", []) if url)) if isinstance(report, dict) else []
        return {
            "urls": urls,
            "raw_count": int(report.get("raw_count", len(urls))) if isinstance(report, dict) else len(urls),
            "duplicate_count": int(report.get("duplicate_count", 0)) if isinstance(report, dict) else 0,
            "invalid_count": int(report.get("invalid_count", 0)) if isinstance(report, dict) else 0,
        }

    def history_path(self) -> Path:
        return Path(self.app.run_path, "config", "parse_history.json")

    def load_history(self) -> list[dict[str, Any]]:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                if store.parse_history_count() > 0:
                    return store.load_parse_history(limit=self.HISTORY_LIMIT)
            except Exception as exc:
                logger.debug(f"load parse history from sqlite failed: {exc}")
        path = self.history_path()
        if not path.is_file():
            return []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            records = data.get("records", data) if isinstance(data, dict) else data
            history = [record for record in records if isinstance(record, dict)][: self.HISTORY_LIMIT]
            if store is not None and history:
                try:
                    store.save_parse_history(history, max_records=self.HISTORY_LIMIT)
                except Exception as exc:
                    logger.debug(f"migrate parse history to sqlite failed: {exc}")
            return history
        except Exception:
            return []

    def save_history(self, records: list[dict[str, Any]]) -> None:
        store = getattr(getattr(self.app, "services", None), "sqlite_store", None)
        if store is not None:
            try:
                store.save_parse_history(records[: self.HISTORY_LIMIT], max_records=self.HISTORY_LIMIT)
            except Exception as exc:
                logger.debug(f"save parse history to sqlite failed: {exc}")
        try:
            path = self.history_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"records": records[: self.HISTORY_LIMIT]}, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"save parse history failed: {exc}")

    def append_history(self, records: list[dict[str, Any]], result: VideoParseBatchResult, cancelled: bool) -> list[dict[str, Any]]:
        record = {
            "history_id": uuid.uuid4().hex,
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "已取消" if cancelled else ("完成" if result.failed_count == 0 else "有失败"),
            "total": result.total_count,
            "success": result.success_count,
            "failed": result.failed_count,
            "input_text": result.input_text,
            "work_links": [item.source_url for item in result.successes if item.source_url][:200],
            "failed_links": [failure.source_url for failure in result.failures if failure.source_url][:200],
            "resources": self.build_resource_records(result),
            "failure_details": self.build_failure_records(result),
            "failure_summary": self.failure_summary(result.failures),
        }
        updated = [record, *records]
        updated = updated[: self.HISTORY_LIMIT]
        self.save_history(updated)
        return updated

    @staticmethod
    def build_resource_records(result: VideoParseBatchResult) -> list[dict[str, Any]]:
        resources: list[dict[str, Any]] = []
        for item in result.successes[:500]:
            image_urls = item.image_urls or item.watermark_image_urls or []
            resources.append(
                {
                    "item_id": item.item_id,
                    "title": item.description,
                    "author": item.author_nickname,
                    "author_id": item.author_id,
                    "platform": item.platform,
                    "media_type": "图集" if item.media_type == "image" or image_urls else "视频",
                    "source_url": item.source_url,
                    "direct_url": item.primary_media_url,
                    "image_count": len(image_urls),
                    "downloadable": bool(item.primary_media_url or image_urls),
                }
            )
        return resources

    @staticmethod
    def build_failure_records(result: VideoParseBatchResult) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for failure in result.failures[:500]:
            failures.append(
                {
                    "source_url": failure.source_url,
                    "reason": failure.reason,
                    "category": failure.category,
                    "retryable": bool(failure.retryable),
                    "next_step": failure.next_step,
                }
            )
        return failures

    @staticmethod
    def failure_summary(failures: list[Any]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for failure in failures:
            category = str(getattr(failure, "category", "") or "unknown")
            summary[category] = summary.get(category, 0) + 1
        return summary

    @staticmethod
    def resource_summary(records: list[dict[str, Any]]) -> dict[str, int]:
        total = len(records)
        success = sum(int(record.get("success") or 0) for record in records)
        failed = sum(int(record.get("failed") or 0) for record in records)
        resources = sum(len(record.get("resources") or []) for record in records if isinstance(record.get("resources"), list))
        failed_links = sum(len(record.get("failed_links") or []) for record in records if isinstance(record.get("failed_links"), list))
        return {"batches": total, "success": success, "failed": failed, "resources": resources, "failed_links": failed_links}

    @staticmethod
    def filter_history(records: list[dict[str, Any]], query: str = "", status: str = "all", media_type: str = "all") -> list[dict[str, Any]]:
        query_text = str(query or "").strip().lower()
        status_text = str(status or "all").strip()
        media_text = str(media_type or "all").strip()
        filtered: list[dict[str, Any]] = []
        for record in records:
            if not isinstance(record, dict):
                continue
            if status_text == "failed" and int(record.get("failed") or 0) <= 0:
                continue
            if status_text == "success" and int(record.get("success") or 0) <= 0:
                continue
            resources = record.get("resources") if isinstance(record.get("resources"), list) else []
            if media_text != "all":
                labels = [str(item.get("media_type") or "") for item in resources if isinstance(item, dict)]
                if media_text == "video" and "视频" not in labels:
                    continue
                if media_text == "image" and "图集" not in labels:
                    continue
            if query_text:
                haystack = " ".join(
                    [
                        str(record.get("time") or ""),
                        str(record.get("status") or ""),
                        " ".join(str(link) for link in record.get("work_links") or []),
                        " ".join(str(link) for link in record.get("failed_links") or []),
                        " ".join(
                            " ".join(str(item.get(key) or "") for key in ("title", "author", "item_id", "source_url"))
                            for item in resources
                            if isinstance(item, dict)
                        ),
                    ]
                ).lower()
                if query_text not in haystack:
                    continue
            filtered.append(record)
        return filtered

    @staticmethod
    def collect_failed_links(records: list[dict[str, Any]], limit: int = 1000) -> list[str]:
        links: list[str] = []
        seen: set[str] = set()
        for record in records:
            for link in record.get("failed_links") or []:
                text = str(link or "").strip()
                if text and text not in seen:
                    seen.add(text)
                    links.append(text)
                    if len(links) >= limit:
                        return links
        return links

    def clear_history(self) -> list[dict[str, Any]]:
        self.save_history([])
        return []
