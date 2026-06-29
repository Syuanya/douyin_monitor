from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from app.core.media.parsed_media_downloader import ParsedMediaDownloader
from app.core.media.video_parser_service import ParsedVideoResult


class ParsedMediaDownloaderP2Test(unittest.TestCase):
    def _downloader(self, save_format: str = "original") -> ParsedMediaDownloader:
        services = SimpleNamespace(
            run_path="/tmp/douyin-monitor-test",
            settings_config=SimpleNamespace(user_config={"gallery_image_save_format": save_format}),
        )
        return ParsedMediaDownloader(services)

    def _item(self) -> ParsedVideoResult:
        return ParsedVideoResult(
            source_url="https://www.douyin.com/video/1",
            media_type="image",
            platform="douyin",
            item_id="aweme123",
            image_urls=["https://example.test/path/cover.webp?x=1"],
        )

    def test_gallery_original_format_keeps_url_suffix(self) -> None:
        downloader = self._downloader("original")
        path = downloader._gallery_image_save_path("/tmp/gallery", self._item(), 1, "https://example.test/a/b.webp?token=1", "original")

        self.assertTrue(path.endswith("aweme123_001.webp"))

    def test_gallery_png_format_forces_png_suffix(self) -> None:
        downloader = self._downloader("png")
        path = downloader._gallery_image_save_path("/tmp/gallery", self._item(), 2, "https://example.test/a/b.jpg", "png")

        self.assertTrue(path.endswith("aweme123_002.png"))

    def test_gallery_files_include_original_image_extensions(self) -> None:
        downloader = self._downloader("original")
        with tempfile.TemporaryDirectory() as temp_dir:
            folder = Path(temp_dir)
            (folder / "aweme123_001.jpg").write_bytes(b"jpg")
            (folder / "aweme123_002.webp").write_bytes(b"webp")
            (folder / "notes.txt").write_text("ignore")

            files = downloader._gallery_files(str(folder))

        self.assertEqual(len(files), 2)
        self.assertTrue(any(path.endswith(".jpg") for path in files))
        self.assertTrue(any(path.endswith(".webp") for path in files))


if __name__ == "__main__":
    unittest.main()
