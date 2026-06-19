from __future__ import annotations

import tempfile
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.core.runtime.task_center import TaskCenter


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "task_records.json")
        center = TaskCenter(storage_path=str(path))
        task_id = center.start(
            "批量下载",
            "内容监控下载",
            total=3,
            retry_action="content_download_items",
            retry_payload={"account_id": "a", "item_ids": ["1", "2", "3"]},
        )
        center.progress(task_id, completed=2, success_count=1, failed_count=1, retry_payload={"account_id": "a", "failed_item_ids": ["2"]})
        center.finish(task_id, success=False, detail="下载失败")

        restored = TaskCenter(storage_path=str(path))
        records = restored.snapshot()
        assert records and records[0]["retry_payload"]["failed_item_ids"] == ["2"]
        restored.clear_failed()
        assert restored.snapshot() == []
    print("task_center_persistence_check: OK")


if __name__ == "__main__":
    main()
