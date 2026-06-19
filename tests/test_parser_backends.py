from __future__ import annotations

import asyncio
import unittest

from app.core.parser import (
    ExternalDouyinParserBackend,
    FallbackDouyinParserBackend,
    InternalDouyinParserBackend,
    build_douyin_parser_backend,
    parser_backend_registry,
)


class DummyVideoParser:
    async def fetch_all_douyin_user_posts(self, sec_user_id: str, max_pages: int = 20, count: int = 20):
        return [{"sec_user_id": sec_user_id, "max_pages": max_pages, "count": count}]

    async def parse_url(self, url: str):
        return {"url": url, "aweme_id": "123456789"}


class ParserBackendTest(unittest.TestCase):
    def test_internal_backend_fetches_profile_contents(self) -> None:
        async def run_case():
            backend = InternalDouyinParserBackend(DummyVideoParser())
            health = await backend.health_check()
            result = await backend.fetch_profile_contents("sec", max_pages=3, count=10)
            return health, result

        health, result = asyncio.run(run_case())

        self.assertTrue(health.ok)
        self.assertEqual(result[0]["sec_user_id"], "sec")
        self.assertEqual(result[0]["max_pages"], 3)
        self.assertEqual(result[0]["count"], 10)

    def test_external_backend_requires_base_url(self) -> None:
        async def run_case():
            backend = ExternalDouyinParserBackend("")
            return await backend.health_check()

        health = asyncio.run(run_case())

        self.assertFalse(health.ok)

    def test_backend_factory_defaults_to_internal(self) -> None:
        backend = build_douyin_parser_backend("unknown", video_parser=DummyVideoParser())

        self.assertIsInstance(backend, InternalDouyinParserBackend)

    def test_internal_backend_parse_url(self) -> None:
        async def run_case():
            backend = InternalDouyinParserBackend(DummyVideoParser())
            return await backend.parse_url("https://v.douyin.com/test/")

        result = asyncio.run(run_case())

        self.assertEqual(result["aweme_id"], "123456789")
        self.assertTrue(InternalDouyinParserBackend(DummyVideoParser()).capabilities().parse_url)

    def test_external_factory_uses_internal_parse_fallback(self) -> None:
        async def run_case():
            backend = build_douyin_parser_backend(
                "external",
                video_parser=DummyVideoParser(),
                external_base_url="https://parser.example.test",
            )
            health = await backend.health_check()
            result = await backend.parse_url("https://v.douyin.com/test/")
            return backend, health, result

        backend, health, result = asyncio.run(run_case())

        self.assertIsInstance(backend, FallbackDouyinParserBackend)
        self.assertTrue(health.ok)
        self.assertEqual(result["aweme_id"], "123456789")
        self.assertTrue(backend.capabilities().parse_url)
        self.assertTrue(backend.capabilities().profile_contents)

    def test_parser_registry_exposes_douyin_backends(self) -> None:
        keys = parser_backend_registry.keys()

        self.assertIn("douyin_internal", keys)
        self.assertIn("douyin_external", keys)
        self.assertIn("douyin_fallback", keys)
        descriptors = parser_backend_registry.descriptors(platform="douyin")
        self.assertGreaterEqual(len(descriptors), 3)
        backend = parser_backend_registry.create("douyin_internal", video_parser=DummyVideoParser())
        self.assertIsInstance(backend, InternalDouyinParserBackend)
