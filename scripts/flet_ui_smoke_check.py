from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> int:
    try:
        import flet  # noqa: F401
    except Exception as exc:
        print(f"flet_ui_smoke_check: skipped (flet unavailable: {exc.__class__.__name__})")
        return 0

    try:
        from app.ui.views.download_history_view import DownloadHistoryPage
        from app.ui.views.task_center_view import TaskCenterPage
        from app.ui.views.video_parse_view import VideoParsePage
    except Exception as exc:
        print(f"flet_ui_smoke_check: import failed: {exc}", file=sys.stderr)
        return 1

    pages = {
        "download_history": DownloadHistoryPage,
        "task_center": TaskCenterPage,
        "video_parse": VideoParsePage,
    }
    missing = [name for name, cls in pages.items() if not hasattr(cls, "load")]
    if missing:
        print(f"flet_ui_smoke_check: missing load(): {', '.join(missing)}", file=sys.stderr)
        return 1
    print("flet_ui_smoke_check: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
