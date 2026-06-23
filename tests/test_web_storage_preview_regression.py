from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app.core.ui_services.storage_browser_service import StorageBrowserService
from app.web.context import WebRuntime


class DummyApp:
    def __init__(self, root: Path) -> None:
        self.services = SimpleNamespace(settings_config=SimpleNamespace(user_config={"douyin_content_download_path": str(root)}))


def test_storage_browser_resolves_relative_paths_under_download_root(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    folder = root / "account_a"
    folder.mkdir(parents=True)
    service = StorageBrowserService(DummyApp(root))

    resolved_root, target = service.resolve_target("account_a")

    assert resolved_root == root.resolve()
    assert target == folder.resolve()
    assert service.is_inside_root(target, resolved_root)


def test_storage_browser_resolves_relative_media_file_without_creating_directory(tmp_path: Path) -> None:
    root = tmp_path / "downloads"
    folder = root / "account_a"
    folder.mkdir(parents=True)
    file_path = folder / "video.mp4"
    file_path.write_bytes(b"mp4")
    service = StorageBrowserService(DummyApp(root))

    resolved_root, target = service.resolve_target("account_a/video.mp4")

    assert resolved_root == root.resolve()
    assert target == file_path.resolve()
    assert target.is_file()


def test_download_queue_realtime_accepts_string_timestamps() -> None:
    assert WebRuntime._coerce_epoch("2026-06-22 17:18:08") > 0
    assert WebRuntime._coerce_epoch("not-a-time") == 0
