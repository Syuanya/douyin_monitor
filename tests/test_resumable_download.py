from __future__ import annotations

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

MISSING_HTTPX = importlib.util.find_spec("httpx") is None

if not MISSING_HTTPX:
    from app.core.media.resumable_download import download_http_file


class FakeResponse:
    def __init__(self, status_code: int, chunks: list[bytes], headers: dict[str, str] | None = None):
        self.status_code = status_code
        self._chunks = chunks
        self.headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_bytes(self, _chunk_size: int):
        for chunk in self._chunks:
            yield chunk


class FakeClient:
    last_headers: dict[str, str] = {}

    def __init__(self, headers=None, **_kwargs):
        FakeClient.last_headers = headers or {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def stream(self, _method: str, _url: str):
        return FakeResponse(206 if "Range" in FakeClient.last_headers else 200, [b"world"], {"content-range": "bytes 5-9/10"})


class ResumableDownloadTest(unittest.TestCase):
    @unittest.skipIf(MISSING_HTTPX, "runtime dependency missing: httpx")
    def test_download_resumes_existing_part_file(self) -> None:
        async def run_case():
            with tempfile.TemporaryDirectory() as temp_dir:
                save_path = Path(temp_dir) / "file.bin"
                (Path(str(save_path) + ".part")).write_bytes(b"hello")
                with patch("app.core.media.resumable_download.httpx.AsyncClient", FakeClient):
                    await download_http_file("https://example.test/file", str(save_path))
                return save_path.read_bytes(), FakeClient.last_headers

        content, headers = asyncio.run(run_case())

        self.assertEqual(content, b"helloworld")
        self.assertEqual(headers["Range"], "bytes=5-")

    @unittest.skipIf(MISSING_HTTPX, "runtime dependency missing: httpx")
    def test_download_can_disable_resume(self) -> None:
        async def run_case():
            with tempfile.TemporaryDirectory() as temp_dir:
                save_path = Path(temp_dir) / "file.bin"
                (Path(str(save_path) + ".part")).write_bytes(b"old")
                with patch("app.core.media.resumable_download.httpx.AsyncClient", FakeClient):
                    await download_http_file("https://example.test/file", str(save_path), resume_enabled=False)
                return save_path.read_bytes(), dict(FakeClient.last_headers)

        content, headers = asyncio.run(run_case())

        self.assertEqual(content, b"world")
        self.assertNotIn("Range", headers)
