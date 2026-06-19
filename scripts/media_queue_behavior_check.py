from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


try:
    import loguru  # noqa: F401
except ModuleNotFoundError:
    class DummyLogger:
        def __getattr__(self, _name):
            return self._noop

        def _noop(self, *_args, **_kwargs):
            return None

        def bind(self, **_kwargs):
            return self

    sys.modules["loguru"] = types.SimpleNamespace(logger=DummyLogger())

from app.core.runtime.media_task_queue import MediaTaskQueue
from app.core.runtime.task_center import TaskCenter


class Settings:
    user_config = {"max_parallel_downloads": 1, "media_download_retry_count": 1}


async def main() -> None:
    queue = MediaTaskQueue(Settings())
    queue.task_center = TaskCenter()

    attempts = {"count": 0}

    async def flaky_download() -> str:
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("temporary failure")
        return "ok"

    result = await queue.run("video_download", "retry-check", flaky_download, dedupe_key="retry-check-path")
    if result != "ok" or attempts["count"] != 2:
        raise AssertionError("download retry did not run exactly once")

    async def slow_download() -> str:
        await asyncio.sleep(10)
        return "late"

    task = asyncio.create_task(queue.run("video_download", "cancel-check", slow_download, dedupe_key="cancel-check-path"))
    await asyncio.sleep(0.1)
    snapshot = queue.snapshot()
    labels = snapshot.get("__global__", {}).get("running_labels", [])
    if "cancel-check" not in labels:
        raise AssertionError(f"running label missing from queue snapshot: {snapshot}")
    queue.cancel_all()
    try:
        await task
    except asyncio.CancelledError:
        pass
    else:
        raise AssertionError("download cancellation did not propagate")

    statuses = [record["status"] for record in queue.task_center.snapshot()]
    if "已取消" not in statuses:
        raise AssertionError(f"cancelled task status missing: {statuses}")

    print("media_queue_behavior_check: OK")


if __name__ == "__main__":
    asyncio.run(main())
