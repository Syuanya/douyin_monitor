from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    errors: list[str] = []
    task_text = (ROOT / "app/ui/views/task_center_view.py").read_text(encoding="utf-8")
    download_text = (ROOT / "app/ui/views/download_history_view.py").read_text(encoding="utf-8")

    task_record_block = task_text.split("    def _record_card", 1)[1].split("    @staticmethod\n    def _has_locatable_payload", 1)[0]
    if "return ft.Container(" not in task_record_block:
        errors.append("task center _record_card must return a card before helper methods")
    if "_download_recovery_card" in task_text:
        errors.append("task center must not contain or render download recovery UI")
    if "下载历史与恢复" in task_text:
        errors.append("task center must not render download history title")

    for marker in ("ft.TextField", "expand=True", "ft.Container(", "bgcolor="):
        if marker in download_text:
            errors.append(f"download history page must not use grey-block risk marker: {marker}")
    if "暂无匹配下载记录" not in download_text:
        errors.append("download history compact empty state missing")
    if "class DownloadHistoryPage" not in download_text:
        errors.append("download history page class missing")

    if errors:
        print("ui_layout_regression_check: failed")
        for error in errors:
            print(f"  {error}")
        return 1
    print("ui_layout_regression_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
