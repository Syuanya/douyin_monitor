# ==============================================================================
# Copyright (C) 2021 Evil0ctal
#
# This file is part of the Douyin_TikTok_Download_API project.
#
# This project is licensed under the Apache License 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at:
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================

import httpx
import json
import asyncio
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from httpx import Response

from crawlers.utils.logger import logger
from crawlers.utils.httpx_compat import async_client_kwargs
from crawlers.utils.api_exceptions import (
    APIError,
    APIConnectionError,
    APIResponseError,
    APITimeoutError,
    APIUnavailableError,
    APIUnauthorizedError,
    APINotFoundError,
    APIRateLimitError,
    APIRetryExhaustedError,
)


class BaseCrawler:
    """
    基础爬虫客户端 (Base crawler client)
    """

    def __init__(
            self,
            proxies: dict = None,
            max_retries: int = 3,
            max_connections: int = 50,
            timeout: int = 10,
            max_tasks: int = 50,
            crawler_headers: dict = {},
    ):
        if isinstance(proxies, dict):
            self.proxies = proxies
        else:
            self.proxies = None

        self.crawler_headers = crawler_headers or {}

        self._max_tasks = max_tasks
        self.semaphore = asyncio.Semaphore(max_tasks)

        self._max_connections = max_connections
        self.limits = httpx.Limits(max_connections=max_connections)

        self._max_retries = max_retries
        self.atransport = httpx.AsyncHTTPTransport(retries=max_retries)

        self._timeout = timeout
        self.timeout = httpx.Timeout(timeout)
        self.aclient = httpx.AsyncClient(
            **async_client_kwargs(
                proxies=self.proxies,
                headers=self.crawler_headers,
                timeout=self.timeout,
                limits=self.limits,
                transport=self.atransport,
            )
        )

    @staticmethod
    def _safe_url_for_log(url: str, keep_params: set[str] | None = None) -> str:
        keep = keep_params or {"max_cursor", "count", "sec_user_id", "aweme_id", "item_id"}
        try:
            parts = urlsplit(str(url))
            query = []
            for key, value in parse_qsl(parts.query, keep_blank_values=True):
                if key not in keep:
                    continue
                text = value
                if key in {"sec_user_id", "a_bogus", "msToken"} and len(text) > 14:
                    text = f"{text[:8]}...{text[-4:]}"
                query.append((key, text))
            return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        except Exception:
            text = str(url)
            return text[:180] + "..." if len(text) > 180 else text

    def _empty_response_message(self, attempt: int, response: Response) -> str:
        return "第 {0} 次响应内容为空, 状态码: {1}, URL:{2}".format(
            attempt,
            getattr(response, "status_code", None),
            self._safe_url_for_log(str(getattr(response, "url", ""))),
        )

    async def fetch_response(self, endpoint: str) -> Response:
        """获取数据 (Get data)

        Args:
            endpoint (str): 接口地址 (Endpoint URL)

        Returns:
            Response: 原始响应对象 (Raw response object)
        """
        return await self.get_fetch_data(endpoint)

    async def fetch_get_json(self, endpoint: str) -> dict:
        """获取 JSON 数据 (Get JSON data)

        Args:
            endpoint (str): 接口地址 (Endpoint URL)

        Returns:
            dict: 解析后的JSON数据 (Parsed JSON data)
        """
        response = await self.get_fetch_data(endpoint)
        return self.parse_json(response)

    async def fetch_post_json(self, endpoint: str, params: dict = {}, data=None) -> dict:
        """获取 JSON 数据 (Post JSON data)

        Args:
            endpoint (str): 接口地址 (Endpoint URL)

        Returns:
            dict: 解析后的JSON数据 (Parsed JSON data)
        """
        response = await self.post_fetch_data(endpoint, params, data)
        return self.parse_json(response)

    def parse_json(self, response: Response) -> dict:
        """解析JSON响应对象 (Parse JSON response object)

        Args:
            response (Response): 原始响应对象 (Raw response object)

        Returns:
            dict: 解析后的JSON数据 (Parsed JSON data)
        """
        if (
                response is not None
                and isinstance(response, Response)
                and response.status_code == 200
        ):
            try:
                return response.json()
            except json.JSONDecodeError as e:
                match = re.search(r"\{.*\}", response.text)
                try:
                    return json.loads(match.group())
                except json.JSONDecodeError as e:
                    logger.error("解析 {0} 接口 JSON 失败： {1}".format(self._safe_url_for_log(str(response.url)), e))
                    raise APIResponseError("解析JSON数据失败")

        else:
            if isinstance(response, Response):
                logger.warning(
                    "获取数据失败。状态码: {0}".format(response.status_code)
                )
            else:
                logger.debug("无效响应类型。响应类型: {0}".format(type(response)))

            raise APIResponseError("获取数据失败")

    async def get_fetch_data(self, url: str):
        """
        获取GET端点数据 (Get GET endpoint data)

        Args:
            url (str): 端点URL (Endpoint URL)

        Returns:
            response: 响应内容 (Response content)
        """
        for attempt in range(self._max_retries):
            try:
                response = await self.aclient.get(url, follow_redirects=True)
                if not response.text.strip() or not response.content:
                    if attempt == self._max_retries - 1:
                        logger.warning(self._empty_response_message(attempt + 1, response))
                        raise APIRetryExhaustedError(
                            "获取端点数据失败, 次数达到上限"
                        )

                    logger.debug(self._empty_response_message(attempt + 1, response))

                    await asyncio.sleep(self._timeout)
                    continue

                response.raise_for_status()
                return response

            except httpx.RequestError:
                raise APIConnectionError("连接端点失败，检查网络环境或代理：{0} 代理：{1} 类名：{2}"
                                         .format(url, self.proxies, self.__class__.__name__)
                                         )

            except httpx.HTTPStatusError as http_error:
                self.handle_http_status_error(http_error, url, attempt + 1)

            except APIError as e:
                logger.debug(e.display_error())
                raise

    async def post_fetch_data(self, url: str, params: dict = {}, data=None):
        """
        获取POST端点数据 (Get POST endpoint data)

        Args:
            url (str): 端点URL (Endpoint URL)
            params (dict): POST请求参数 (POST request parameters)

        Returns:
            response: 响应内容 (Response content)
        """
        for attempt in range(self._max_retries):
            try:
                response = await self.aclient.post(
                    url,
                    json=None if not params else dict(params),
                    data=None if not data else data,
                    follow_redirects=True
                )
                if not response.text.strip() or not response.content:
                    if attempt == self._max_retries - 1:
                        logger.warning(self._empty_response_message(attempt + 1, response))
                        raise APIRetryExhaustedError(
                            "获取端点数据失败, 次数达到上限"
                        )

                    logger.debug(self._empty_response_message(attempt + 1, response))

                    await asyncio.sleep(self._timeout)
                    continue

                response.raise_for_status()
                return response

            except httpx.RequestError:
                raise APIConnectionError(
                    "连接端点失败，检查网络环境或代理：{0} 代理：{1} 类名：{2}".format(url, self.proxies,
                                                                                   self.__class__.__name__)
                )

            except httpx.HTTPStatusError as http_error:
                self.handle_http_status_error(http_error, url, attempt + 1)

            except APIError as e:
                logger.debug(e.display_error())
                raise

    async def head_fetch_data(self, url: str):
        """
        获取HEAD端点数据 (Get HEAD endpoint data)

        Args:
            url (str): 端点URL (Endpoint URL)

        Returns:
            response: 响应内容 (Response content)
        """
        try:
            response = await self.aclient.head(url)
            response.raise_for_status()
            return response

        except httpx.RequestError:
            raise APIConnectionError("连接端点失败，检查网络环境或代理：{0} 代理：{1} 类名：{2}".format(
                url, self.proxies, self.__class__.__name__
            )
            )

        except httpx.HTTPStatusError as http_error:
            self.handle_http_status_error(http_error, url, 1)

        except APIError as e:
            e.display_error()

    def handle_http_status_error(self, http_error, url: str, attempt):
        """
        处理HTTP状态错误 (Handle HTTP status error)

        Args:
            http_error: HTTP状态错误 (HTTP status error)
            url: 端点URL (Endpoint URL)
            attempt: 尝试次数 (Number of attempts)
        Raises:
            APIConnectionError: 连接端点失败 (Failed to connect to endpoint)
            APIResponseError: 响应错误 (Response error)
            APIUnavailableError: 服务不可用 (Service unavailable)
            APINotFoundError: 端点不存在 (Endpoint does not exist)
            APITimeoutError: 连接超时 (Connection timeout)
            APIUnauthorizedError: 未授权 (Unauthorized)
            APIRateLimitError: 请求频率过高 (Request frequency is too high)
            APIRetryExhaustedError: 重试次数达到上限 (The number of retries has reached the upper limit)
        """
        response = getattr(http_error, "response", None)
        status_code = getattr(response, "status_code", None)

        if response is None or status_code is None:
            logger.error("HTTP状态错误: {0}, URL: {1}, 尝试次数: {2}".format(
                http_error, self._safe_url_for_log(url), attempt
            )
            )
            raise APIResponseError(f"处理HTTP错误时遇到意外情况: {http_error}")

        if status_code == 302:
            pass
        elif status_code == 404:
            raise APINotFoundError(f"HTTP Status Code {status_code}")
        elif status_code == 503:
            raise APIUnavailableError(f"HTTP Status Code {status_code}")
        elif status_code == 408:
            raise APITimeoutError(f"HTTP Status Code {status_code}")
        elif status_code == 401:
            raise APIUnauthorizedError(f"HTTP Status Code {status_code}")
        elif status_code == 429:
            raise APIRateLimitError(f"HTTP Status Code {status_code}")
        else:
            logger.error("HTTP状态错误: {0}, URL: {1}, 尝试次数: {2}".format(
                status_code, self._safe_url_for_log(url), attempt
            )
            )
            raise APIResponseError(f"HTTP状态错误: {status_code}")

    async def close(self):
        await self.aclient.aclose()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclient.aclose()
