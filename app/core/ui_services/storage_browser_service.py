from __future__ import annotations

from pathlib import Path
from typing import Any

from ...utils import utils
from .common import default_douyin_download_path


class StorageBrowserService:
    """Filesystem browsing, filtering and sorting for the storage page."""

    IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".avif"}

    def __init__(self, app: Any):
        self.app = app

    def root_path(self) -> Path:
        settings = self.app.services.settings_config
        configured = str(getattr(settings, "user_config", {}).get("douyin_content_download_path") or "").strip()
        return Path(configured or default_douyin_download_path(self.app))

    @staticmethod
    def is_inside_root(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return path == root

    def resolve_target(self, path: str | Path | None) -> tuple[Path, Path]:
        """Resolve a storage browser path under the configured download root.

        The Web UI passes relative paths returned by ``storage_snapshot``.
        Older code resolved those relative paths against the process working
        directory, so opening a folder like ``account/video`` was treated as
        ``/app/account/video`` and then rejected as outside the download root.
        That made folder navigation appear to work but always returned the root
        directory and therefore never showed the media files inside.
        """
        root = self.root_path().resolve()
        raw = "" if path is None else str(path).strip()
        if not raw or raw in {".", "/"}:
            target = root
        else:
            candidate = Path(raw)
            target = candidate.resolve() if candidate.is_absolute() else (root / candidate).resolve()
        if not self.is_inside_root(target, root):
            target = root
        # Only create directories for directory browsing.  File preview callers
        # use the same resolver and must not accidentally create a directory
        # with a media filename when the file does not exist.
        if not target.suffix:
            target.mkdir(parents=True, exist_ok=True)
        return root, target

    def scan(self, path: Path, *, query: str = "", media_filter: str = "all", sort_mode: str = "name_asc") -> tuple[list[Path], list[Path]]:
        entries = sorted(path.iterdir(), key=lambda item: (item.is_file(), item.name.lower())) if path.exists() else []
        folders = [item for item in entries if item.is_dir()]
        media_files = [item for item in entries if item.is_file() and self.is_media_file(item)]
        query = str(query or "").strip().lower()
        if query:
            folders = [item for item in folders if query in item.name.lower()]
            media_files = [item for item in media_files if query in item.name.lower()]
        if media_filter == "video":
            media_files = [item for item in media_files if self.is_video_file(item)]
        elif media_filter == "image":
            media_files = [item for item in media_files if self.is_image_file(item)]
        elif media_filter == "empty":
            media_files = [item for item in media_files if self.safe_file_size(item) <= 0]
        self.sort_entries(folders, media_files, sort_mode)
        return folders, media_files

    @staticmethod
    def sort_entries(folders: list[Path], media_files: list[Path], sort_mode: str) -> None:
        reverse = str(sort_mode or "").endswith("_desc")
        if str(sort_mode).startswith("time"):
            media_files.sort(key=lambda item: item.stat().st_mtime, reverse=reverse)
            folders.sort(key=lambda item: item.stat().st_mtime, reverse=reverse)
        elif str(sort_mode).startswith("size"):
            media_files.sort(key=lambda item: item.stat().st_size, reverse=reverse)
            folders.sort(key=lambda item: item.name.lower())
        else:
            media_files.sort(key=lambda item: item.name.lower(), reverse=reverse)
            folders.sort(key=lambda item: item.name.lower(), reverse=reverse)

    @staticmethod
    def safe_file_size(path: Path) -> int:
        try:
            return path.stat().st_size
        except OSError:
            return 0

    @staticmethod
    def is_video_file(path: Path) -> bool:
        return utils.is_valid_video_file(str(path))

    @classmethod
    def is_image_file(cls, path: Path) -> bool:
        return path.suffix.lower() in cls.IMAGE_SUFFIXES

    @classmethod
    def is_media_file(cls, path: Path) -> bool:
        return cls.is_video_file(path) or cls.is_image_file(path)
