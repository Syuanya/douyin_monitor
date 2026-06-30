from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from app.ui.views.douyin_content_download_controller import DouyinContentDownloadController


class TaskCenter:
    def __init__(self):
        self.started = []
        self.progresses = []
        self.finished = []
        self.retry_payloads = []
        self.cancelled = []

    def start(self, title, category, total=0, retry_action=None, retry_payload=None):
        self.started.append({"title": title, "category": category, "total": total, "retry_action": retry_action, "retry_payload": retry_payload})
        return "task-1"

    def progress(self, task_id, **kwargs):
        self.progresses.append({"task_id": task_id, **kwargs})

    def update_retry_payload(self, task_id, payload):
        self.retry_payloads.append({"task_id": task_id, "payload": payload})

    def finish(self, task_id, **kwargs):
        self.finished.append({"task_id": task_id, **kwargs})

    def cancel(self, task_id, reason):
        self.cancelled.append({"task_id": task_id, "reason": reason})


class Manager:
    def __init__(self, account, results):
        self.account = account
        self.results = results
        self.downloaded = []

    def find_account(self, account_id):
        return self.account if account_id == self.account.account_id else None

    async def download_item(self, account_id, item_id):
        self.downloaded.append(item_id)
        result = self.results[item_id]
        if isinstance(result, Exception):
            raise result
        return result

    def sort_items_newest_first(self, items):
        return sorted(items, key=lambda item: getattr(item, "first_seen_time", ""), reverse=True)


def owner_with(*, settings=None, results=None, task_center=None, stop=False):
    items = [
        SimpleNamespace(item_id="new", title="新作品", status="new", first_seen_time="2026-06-30 10:00", media_type="video", image_urls=[]),
        SimpleNamespace(item_id="failed", title="失败作品", status="download_failed", first_seen_time="2026-06-30 11:00", media_type="video", image_urls=[]),
        SimpleNamespace(item_id="done", title="已下载", status="downloaded", first_seen_time="2026-06-30 09:00", media_type="video", image_urls=[]),
    ]
    account = SimpleNamespace(account_id="a1", display_name="账号", douyin_nickname="", items=items)
    services = SimpleNamespace(
        settings_config=SimpleNamespace(user_config=settings or {}),
        task_center=task_center,
    )
    owner = SimpleNamespace(
        app=SimpleNamespace(services=services),
        manager=Manager(account, results or {}),
        download_stop_requested=stop,
        download_failure_reasons=[],
        download_progress_text="",
        render_count=0,
    )

    async def render_current_view():
        owner.render_count += 1

    owner.render_current_view = render_current_view
    return owner


def test_parallel_limit_uses_unified_batch_download_concurrency():
    controller = DouyinContentDownloadController(owner_with(settings={"batch_download_concurrency": "50", "max_parallel_downloads": 1}))
    assert controller.parallel_limit() == 12

    controller = DouyinContentDownloadController(owner_with(settings={"batch_download_concurrency": "0"}))
    assert controller.parallel_limit() == 1

    controller = DouyinContentDownloadController(owner_with(settings={"batch_download_concurrency": "bad", "max_parallel_downloads": 7}))
    assert controller.parallel_limit() == 3


def test_filter_items_delegates_download_filter_and_keeps_sorting():
    controller = DouyinContentDownloadController(owner_with())
    account = controller.owner.manager.account

    assert [item.item_id for item in controller.filter_items(account, "failed")] == ["failed"]
    assert [item.item_id for item in controller.filter_items(account, "pending")] == ["new"]
    assert controller.filter_label("failed") == "下载失败作品"


def test_download_location_resolves_file_to_parent_directory(tmp_path):
    file_path = tmp_path / "video.mp4"
    file_path.write_text("x", encoding="utf-8")

    assert Path(DouyinContentDownloadController.download_location(str(file_path))) == tmp_path
    assert Path(DouyinContentDownloadController.download_location(str(tmp_path))) == tmp_path


@pytest.mark.asyncio
async def test_run_items_until_stopped_deduplicates_updates_task_center_and_records_failures():
    task_center = TaskCenter()
    owner = owner_with(
        settings={"batch_download_concurrency": 2},
        task_center=task_center,
        results={
            "new": {"success": True, "reason": "完成"},
            "failed": {"success": False, "reason": "地址过期"},
        },
    )
    controller = DouyinContentDownloadController(owner)

    success, failed, stopped = await controller.run_items_until_stopped("a1", ["new", "failed", "new"])

    assert (success, failed, stopped) == (1, 1, False)
    assert sorted(owner.manager.downloaded) == ["failed", "new"]
    assert owner.download_failure_reasons == ["failed：地址过期"]
    assert task_center.started[0]["total"] == 2
    assert task_center.finished[-1]["success"] is False
    assert task_center.retry_payloads[-1]["payload"]["failed_item_ids"] == ["failed"]
    assert "成功 1，失败 1" in owner.download_progress_text


@pytest.mark.asyncio
async def test_run_items_until_stopped_marks_stopped_when_user_cancelled_before_workers_run():
    task_center = TaskCenter()
    owner = owner_with(settings={"batch_download_concurrency": 2}, task_center=task_center, results={}, stop=True)
    controller = DouyinContentDownloadController(owner)

    success, failed, stopped = await controller.run_items_until_stopped("a1", ["new", "failed"])

    assert (success, failed, stopped) == (0, 0, True)
    assert task_center.cancelled[-1]["reason"] == "下载已停止"
