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

import asyncio
import os
import time
from urllib.parse import urlencode, quote
import yaml

from crawlers.base_crawler import BaseCrawler
from crawlers.douyin.web.endpoints import DouyinAPIEndpoints
from crawlers.douyin.web.models import (
    BaseRequestModel, LiveRoomRanking, PostComments,
    PostCommentsReply, PostDetail,
    UserProfile, UserCollection, UserLike, UserLive,
    UserLive2, UserMix, UserPost
)
from crawlers.douyin.web.utils import (AwemeIdFetcher,
                                       BogusManager,
                                       SecUserIdFetcher,
                                       TokenManager,
                                       VerifyFpManager,
                                       WebCastIdFetcher,
                                       extract_valid_urls
                                       )

path = os.path.abspath(os.path.dirname(__file__))

with open(f"{path}/config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}


class DouyinWebCrawler:

    async def get_douyin_headers(self):
        douyin_config = ((config.get("TokenManager") or {}).get("douyin") or {})
        headers_config = douyin_config.get("headers") or {}
        proxies_config = douyin_config.get("proxies") or {}
        kwargs = {
            "headers": {
                "Accept-Language": headers_config.get("Accept-Language") or "zh-CN,zh;q=0.9,en;q=0.8",
                "User-Agent": headers_config.get("User-Agent") or (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Referer": headers_config.get("Referer") or "https://www.douyin.com/",
                "Cookie": headers_config.get("Cookie") or "",
            },
            "proxies": {"http://": proxies_config.get("http"), "https://": proxies_config.get("https")},
        }
        return kwargs

    "-------------------------------------------------------handler接口列表-------------------------------------------------------"

    async def fetch_one_video(self, aweme_id: str):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = PostDetail(aweme_id=aweme_id)

            params_dict = params.dict()
            params_dict["msToken"] = ''
            a_bogus = BogusManager.ab_model_2_endpoint(params_dict, kwargs["headers"]["User-Agent"])
            endpoint = f"{DouyinAPIEndpoints.POST_DETAIL}?{urlencode(params_dict)}&a_bogus={a_bogus}"

            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_user_post_videos(self, sec_user_id: str, max_cursor: int, count: int):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserPost(sec_user_id=sec_user_id, max_cursor=max_cursor, count=count)

            params_dict = params.dict()
            params_dict["msToken"] = ''
            a_bogus = BogusManager.ab_model_2_endpoint(params_dict, kwargs["headers"]["User-Agent"])
            endpoint = f"{DouyinAPIEndpoints.USER_POST}?{urlencode(params_dict)}&a_bogus={a_bogus}"

            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_user_like_videos(self, sec_user_id: str, max_cursor: int, count: int):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserLike(sec_user_id=sec_user_id, max_cursor=max_cursor, count=count)

            params_dict = params.dict()
            params_dict["msToken"] = ''
            a_bogus = BogusManager.ab_model_2_endpoint(params_dict, kwargs["headers"]["User-Agent"])
            endpoint = f"{DouyinAPIEndpoints.USER_FAVORITE_A}?{urlencode(params_dict)}&a_bogus={a_bogus}"

            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_user_collection_videos(self, cookie: str, cursor: int = 0, count: int = 20):
        kwargs = await self.get_douyin_headers()
        kwargs["headers"]["Cookie"] = cookie
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserCollection(cursor=cursor, count=count)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.USER_COLLECTION, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_post_json(endpoint)
        return response

    async def fetch_user_mix_videos(self, mix_id: str, cursor: int = 0, count: int = 20):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserMix(mix_id=mix_id, cursor=cursor, count=count)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.MIX_AWEME, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_user_live_videos(self, webcast_id: str, room_id_str=""):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserLive(web_rid=webcast_id, room_id_str=room_id_str)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.LIVE_INFO, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_user_live_videos_by_room_id(self, room_id: str):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserLive2(room_id=room_id)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.LIVE_INFO_ROOM_ID, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_live_gift_ranking(self, room_id: str, rank_type: int = 30):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = LiveRoomRanking(room_id=room_id, rank_type=rank_type)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.LIVE_GIFT_RANK, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def handler_user_profile(self, sec_user_id: str):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = UserProfile(sec_user_id=sec_user_id)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.USER_DETAIL, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_video_comments(self, aweme_id: str, cursor: int = 0, count: int = 20):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = PostComments(aweme_id=aweme_id, cursor=cursor, count=count)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.POST_COMMENT, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_video_comments_reply(self, item_id: str, comment_id: str, cursor: int = 0, count: int = 20):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = PostCommentsReply(item_id=item_id, comment_id=comment_id, cursor=cursor, count=count)
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.POST_COMMENT_REPLY, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    async def fetch_hot_search_result(self):
        kwargs = await self.get_douyin_headers()
        base_crawler = BaseCrawler(proxies=kwargs["proxies"], crawler_headers=kwargs["headers"])
        async with base_crawler as crawler:
            params = BaseRequestModel()
            endpoint = BogusManager.xb_model_2_endpoint(
                DouyinAPIEndpoints.DOUYIN_HOT_SEARCH, params.dict(), kwargs["headers"]["User-Agent"]
            )
            response = await crawler.fetch_get_json(endpoint)
        return response

    "-------------------------------------------------------utils接口列表-------------------------------------------------------"

    async def gen_real_msToken(self, ):
        result = {
            "msToken": TokenManager().gen_real_msToken()
        }
        return result

    async def gen_ttwid(self, ):
        result = {
            "ttwid": TokenManager().gen_ttwid()
        }
        return result

    async def gen_verify_fp(self, ):
        result = {
            "verify_fp": VerifyFpManager.gen_verify_fp()
        }
        return result

    async def gen_s_v_web_id(self, ):
        result = {
            "s_v_web_id": VerifyFpManager.gen_s_v_web_id()
        }
        return result

    async def get_x_bogus(self, url: str, user_agent: str):
        url = BogusManager.xb_str_2_endpoint(url, user_agent)
        result = {
            "url": url,
            "x_bogus": url.split("&X-Bogus=")[1],
            "user_agent": user_agent
        }
        return result

    async def get_a_bogus(self, url: str, user_agent: str):
        endpoint = url.split("?")[0]
        params = dict([i.split("=") for i in url.split("?")[1].split("&")])
        params["msToken"] = ""
        a_bogus = BogusManager.ab_model_2_endpoint(params, user_agent)
        result = {
            "url": f"{endpoint}?{urlencode(params)}&a_bogus={a_bogus}",
            "a_bogus": a_bogus,
            "user_agent": user_agent
        }
        return result

    async def get_sec_user_id(self, url: str):
        return await SecUserIdFetcher.get_sec_user_id(url)

    async def get_all_sec_user_id(self, urls: list):
        urls = extract_valid_urls(urls)

        return await SecUserIdFetcher.get_all_sec_user_id(urls)

    async def get_aweme_id(self, url: str):
        return await AwemeIdFetcher.get_aweme_id(url)

    async def get_all_aweme_id(self, urls: list):
        urls = extract_valid_urls(urls)

        return await AwemeIdFetcher.get_all_aweme_id(urls)

    async def get_webcast_id(self, url: str):
        return await WebCastIdFetcher.get_webcast_id(url)

    async def get_all_webcast_id(self, urls: list):
        urls = extract_valid_urls(urls)

        return await WebCastIdFetcher.get_all_webcast_id(urls)
