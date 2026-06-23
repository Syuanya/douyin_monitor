from __future__ import annotations

import asyncio
import unittest

import httpx

from crawlers.base_crawler import BaseCrawler
from crawlers.utils.api_exceptions import APIResponseError


class BaseCrawlerRobustnessTest(unittest.TestCase):
    def test_parse_json_non_json_response_raises_api_response_error(self) -> None:
        request = httpx.Request("GET", "https://example.invalid/api?a_bogus=secret")
        response = httpx.Response(200, text="<html>risk control</html>", request=request)
        crawler = BaseCrawler(max_retries=1)
        try:
            with self.assertRaises(APIResponseError):
                crawler.parse_json(response)
        finally:
            asyncio.run(crawler.close())

    def test_http_302_does_not_get_silently_swallowed(self) -> None:
        request = httpx.Request("GET", "https://example.invalid/api")
        response = httpx.Response(302, headers={"location": "https://example.invalid/login?token=secret"}, request=request)
        error = httpx.HTTPStatusError("redirect", request=request, response=response)
        crawler = BaseCrawler(max_retries=1)
        try:
            with self.assertRaises(APIResponseError):
                crawler.handle_http_status_error(error, str(request.url), 1)
        finally:
            asyncio.run(crawler.close())
