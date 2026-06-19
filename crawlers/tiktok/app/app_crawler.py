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
import time
import yaml
import os

from crawlers.base_crawler import BaseCrawler
from crawlers.tiktok.app.endpoints import TikTokAPIEndpoints
from crawlers.utils.utils import model_to_query_string

from tenacity import *

from crawlers.tiktok.app.models import (
    BaseRequestModel, FeedVideoDetail
)

from crawlers.utils.deprecated import deprecated

path = os.path.abspath(os.path.dirname(__file__))

with open(f"{path}/config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f)


class TikTokAPPCrawler:

    async def get_tiktok_headers(self):
        tiktok_config = config["TokenManager"]["tiktok"]
        kwargs = {
            "headers": {
                "User-Agent": tiktok_config["headers"]["User-Agent"],
                "Referer": tiktok_config["headers"]["Referer"],
                "Cookie": tiktok_config["headers"]["Cookie"],
                "x-ladon": "Hello From Evil0ctal!",
            },
            "proxies": {"http://": tiktok_config["proxies"]["http"],
                        "https://": tiktok_config["proxies"]["https"]}
        }
        return kwargs
