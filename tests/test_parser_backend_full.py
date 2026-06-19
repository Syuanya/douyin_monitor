from __future__ import annotations

import asyncio
import unittest

from app.core.parser.backend import FallbackParserBackend, ParserCapability, ParserHealth
from app.core.parser.douyin_backends import build_single_url_parser_backend


class DummyVideoParser:
    async def parse_url_direct(self, url: str):
        return {"aweme_id": "1", "platform": "douyin", "type": "video", "video_data": {}, "author": {}}


class FailingBackend:
    name = "failing"
    platform = "douyin"
    version = "1"
    capabilities = ParserCapability(single_url=True)

    async def health_check(self):
        return ParserHealth(False, self.name, "broken", self.capabilities, self.version)

    async def parse_url(self, url: str):
        raise RuntimeError("broken")

    async def fetch_profile_contents(self, sec_user_id: str, max_pages: int = 20, count: int = 20):
        raise RuntimeError("broken")


class ParserBackendFullTest(unittest.TestCase):
    def test_single_url_backend_capabilities_and_parse(self):
        backend = build_single_url_parser_backend(video_parser=DummyVideoParser())
        result = asyncio.run(backend.parse_url("https://v.douyin.com/test/"))
        self.assertEqual(result["aweme_id"], "1")
        self.assertTrue(backend.capabilities.single_url)
        self.assertTrue(backend.capabilities.fallback)

    def test_fallback_backend_reports_errors(self):
        backend = FallbackParserBackend([FailingBackend()])
        with self.assertRaises(RuntimeError) as ctx:
            asyncio.run(backend.parse_url("https://example.com"))
        self.assertIn("broken", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
