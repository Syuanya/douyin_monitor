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
import json
import os
import random
import re
import time
import urllib
from pathlib import Path
from typing import Union
from urllib.parse import urlencode, quote

import httpx
import qrcode
import yaml

from crawlers.douyin.web.xbogus import XBogus as XB
from crawlers.douyin.web.abogus import ABogus as AB

from crawlers.utils.api_exceptions import (
    APIError,
    APIConnectionError,
    APIResponseError,
    APIUnavailableError,
    APIUnauthorizedError,
    APINotFoundError,
)
from crawlers.utils.logger import logger
from crawlers.utils.httpx_compat import client_kwargs, async_client_kwargs
from crawlers.utils.utils import (
    gen_random_str,
    get_timestamp,
    extract_valid_urls,
    split_filename,
)

path = os.path.abspath(os.path.dirname(__file__))

with open(f"{path}/config.yaml", "r", encoding="utf-8") as f:
    config = yaml.safe_load(f) or {}


class TokenManager:
    douyin_manager = ((config.get("TokenManager") or {}).get("douyin") or {})
    token_conf = douyin_manager.get("msToken") or {}
    ttwid_conf = douyin_manager.get("ttwid") or {}
    proxies_conf = douyin_manager.get("proxies") or {}
    proxies = {
        "http://": proxies_conf.get("http"),
        "https://": proxies_conf.get("https"),
    }

    @classmethod
    def gen_real_msToken(cls) -> str:
        """
        生成真实的msToken,当出现错误时返回虚假的值
        (Generate a real msToken and return a false value when an error occurs)
        """

        payload = json.dumps(
            {
                "magic": cls.token_conf.get("magic", 538969122),
                "version": cls.token_conf.get("version", 1),
                "dataType": cls.token_conf.get("dataType", 8),
                "strData": cls.token_conf.get("strData", ""),
                "tspFromClient": get_timestamp(),
            }
        )
        headers = {
            "User-Agent": cls.token_conf.get("User-Agent") or (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36"
            ),
            "Content-Type": "application/json",
        }
        url = cls.token_conf.get("url")
        if not url:
            return cls.gen_false_msToken()

        transport = httpx.HTTPTransport(retries=5)
        with httpx.Client(**client_kwargs(proxies=cls.proxies, transport=transport)) as client:
            try:
                response = client.post(
                    url, content=payload, headers=headers
                )
                response.raise_for_status()

                msToken = str(httpx.Cookies(response.cookies).get("msToken"))
                if len(msToken) not in [120, 128]:
                    raise APIResponseError("响应内容：{0}， Douyin msToken API 的响应内容不符合要求。".format(msToken))

                return msToken


            except Exception as e:
                logger.debug("请求Douyin msToken API失败，已降级使用本地msToken：{0}".format(e))
                logger.debug("将使用本地生成的虚假msToken参数，以继续请求。")
                return cls.gen_false_msToken()

    @classmethod
    def gen_false_msToken(cls) -> str:
        """生成随机msToken (Generate random msToken)"""
        return gen_random_str(126) + "=="

    @classmethod
    def gen_ttwid(cls) -> str:
        """
        生成请求必带的ttwid
        (Generate the essential ttwid for requests)
        """

        transport = httpx.HTTPTransport(retries=5)
        with httpx.Client(transport=transport) as client:
            try:
                url = cls.ttwid_conf.get("url")
                data = cls.ttwid_conf.get("data", "{}")
                if not url:
                    raise APIUnavailableError("ttwid endpoint is not configured")
                response = client.post(url, content=data)
                response.raise_for_status()

                ttwid = str(httpx.Cookies(response.cookies).get("ttwid"))
                return ttwid

            except httpx.RequestError as exc:
                raise APIConnectionError(
                    "请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}"
                    .format(cls.ttwid_conf.get("url", ""), cls.proxies, cls.__name__, exc)
                )

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 401:
                    raise APIUnauthorizedError(
                        "参数验证失败，请更新 Douyin_TikTok_Download_API 配置文件中的 {0}，以匹配 {1} 新规则"
                        .format("ttwid", "douyin")
                    )

                elif e.response.status_code == 404:
                    raise APINotFoundError("ttwid无法找到API端点")
                else:
                    raise APIResponseError("链接：{0}，状态码 {1}：{2} ".format(
                        e.response.url, e.response.status_code, e.response.text
                    )
                    )


class VerifyFpManager:
    @classmethod
    def gen_verify_fp(cls) -> str:
        """
        生成verifyFp 与 s_v_web_id (Generate verifyFp)
        """
        base_str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
        t = len(base_str)
        milliseconds = int(round(time.time() * 1000))
        base36 = ""
        while milliseconds > 0:
            remainder = milliseconds % 36
            if remainder < 10:
                base36 = str(remainder) + base36
            else:
                base36 = chr(ord("a") + remainder - 10) + base36
            milliseconds = int(milliseconds / 36)
        r = base36
        o = [""] * 36
        o[8] = o[13] = o[18] = o[23] = "_"
        o[14] = "4"

        for i in range(36):
            if not o[i]:
                n = 0 or int(random.random() * t)
                if i == 19:
                    n = 3 & n | 8
                o[i] = base_str[n]

        return "verify_" + r + "_" + "".join(o)

    @classmethod
    def gen_s_v_web_id(cls) -> str:
        return cls.gen_verify_fp()


class BogusManager:

    @classmethod
    def xb_str_2_endpoint(cls, endpoint: str, user_agent: str) -> str:
        try:
            final_endpoint = XB(user_agent).getXBogus(endpoint)
        except Exception as e:
            raise RuntimeError("生成X-Bogus失败: {0})".format(e))

        return final_endpoint[0]

    @classmethod
    def xb_model_2_endpoint(cls, base_endpoint: str, params: dict, user_agent: str) -> str:
        if not isinstance(params, dict):
            raise TypeError("参数必须是字典类型")

        param_str = "&".join([f"{k}={v}" for k, v in params.items()])

        try:
            xb_value = XB(user_agent).getXBogus(param_str)
        except Exception as e:
            raise RuntimeError("生成X-Bogus失败: {0})".format(e))

        separator = "&" if "?" in base_endpoint else "?"

        final_endpoint = f"{base_endpoint}{separator}{param_str}&X-Bogus={xb_value[1]}"

        return final_endpoint

    @classmethod
    def ab_model_2_endpoint(cls, params: dict, user_agent: str) -> str:
        if not isinstance(params, dict):
            raise TypeError("参数必须是字典类型")

        try:
            ab_value = AB().get_value(params, )
        except Exception as e:
            raise RuntimeError("生成A-Bogus失败: {0})".format(e))

        return quote(ab_value, safe='')


class SecUserIdFetcher:
    _DOUYIN_URL_PATTERN = re.compile(r"user/([^/?]*)")
    _REDIRECT_URL_PATTERN = re.compile(r"sec_uid=([^&]*)")

    @classmethod
    async def get_sec_user_id(cls, url: str) -> str:
        """
        从单个url中获取sec_user_id (Get sec_user_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的sec_user_id (Matched sec_user_id)。
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        url = extract_valid_urls(url)

        if url is None:
            raise (
                APINotFoundError("输入的URL不合法。类名：{0}".format(cls.__name__))
            )

        pattern = (
            cls._REDIRECT_URL_PATTERN
            if "v.douyin.com" in url
            else cls._DOUYIN_URL_PATTERN
        )

        try:
            transport = httpx.AsyncHTTPTransport(retries=5)
            async with httpx.AsyncClient(
                    **async_client_kwargs(proxies=TokenManager.proxies, transport=transport, timeout=10)
            ) as client:
                response = await client.get(url, follow_redirects=True)
                if response.status_code in {200, 444}:
                    match = pattern.search(str(response.url))
                    if match:
                        return match.group(1)
                    else:
                        raise APIResponseError(
                            "未在响应的地址中找到sec_user_id，检查链接是否为用户主页类名：{0}"
                            .format(cls.__name__)
                        )

                elif response.status_code == 401:
                    raise APIUnauthorizedError("未授权的请求。类名：{0}".format(cls.__name__)
                                               )
                elif response.status_code == 404:
                    raise APINotFoundError("未找到API端点。类名：{0}".format(cls.__name__)
                                           )
                elif response.status_code == 503:
                    raise APIUnavailableError("API服务不可用。类名：{0}".format(cls.__name__)
                                              )
                else:
                    raise APIResponseError("链接：{0}，状态码 {1}：{2} ".format(
                        response.url, response.status_code, response.text
                    )
                    )

        except httpx.RequestError as exc:
            raise APIConnectionError("请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}"
                                     .format(url, TokenManager.proxies, cls.__name__, exc)
                                     )

    @classmethod
    async def get_all_sec_user_id(cls, urls: list) -> list:
        """
        获取列表sec_user_id列表 (Get list sec_user_id list)

        Args:
            urls: list: 用户url列表 (User url list)

        Return:
            sec_user_ids: list: 用户sec_user_id列表 (User sec_user_id list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        urls = extract_valid_urls(urls)

        if urls == []:
            raise (
                APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)
                                 )
            )

        sec_user_ids = [cls.get_sec_user_id(url) for url in urls]
        return await asyncio.gather(*sec_user_ids)


class AwemeIdFetcher:
    _DOUYIN_VIDEO_URL_PATTERN = re.compile(r"video/([^/?]*)")
    _DOUYIN_NOTE_URL_PATTERN = re.compile(r"note/([^/?]*)")
    _DOUYIN_DISCOVER_URL_PATTERN = re.compile(r"modal_id=([0-9]+)")

    @classmethod
    async def get_aweme_id(cls, url: str) -> str:
        """
        从单个url中获取aweme_id (Get aweme_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的aweme_id (Matched aweme_id)。
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        url = extract_valid_urls(url)

        if url is None:
            raise (
                APINotFoundError("输入的URL不合法。类名：{0}".format(cls.__name__))
            )

        transport = httpx.AsyncHTTPTransport(retries=5)
        async with httpx.AsyncClient(
                **async_client_kwargs(proxies=TokenManager.proxies, transport=transport, timeout=10)
        ) as client:
            try:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()

                video_pattern = cls._DOUYIN_VIDEO_URL_PATTERN
                note_pattern = cls._DOUYIN_NOTE_URL_PATTERN
                discover_pattern = cls._DOUYIN_DISCOVER_URL_PATTERN

                match = video_pattern.search(str(response.url))
                if video_pattern.search(str(response.url)):
                    aweme_id = match.group(1)
                else:
                    match = note_pattern.search(str(response.url))
                    if match:
                        aweme_id = match.group(1)
                    else:
                        match = discover_pattern.search(str(response.url))
                        if match:
                            aweme_id = match.group(1)
                        else:
                            raise APIResponseError(
                                "未在响应的地址中找到aweme_id，检查链接是否为作品页"
                            )
                return aweme_id

            except httpx.RequestError as exc:
                raise APIConnectionError("请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}"
                                         .format(url, TokenManager.proxies, cls.__name__, exc)
                                         )

            except httpx.HTTPStatusError as e:
                raise APIResponseError("链接：{0}，状态码 {1}：{2} ".format(
                    e.response.url, e.response.status_code, e.response.text
                )
                )

    @classmethod
    async def get_all_aweme_id(cls, urls: list) -> list:
        """
        获取视频aweme_id,传入列表url都可以解析出aweme_id (Get video aweme_id, pass in the list url can parse out aweme_id)

        Args:
            urls: list: 列表url (list url)

        Return:
            aweme_ids: list: 视频的唯一标识，返回列表 (The unique identifier of the video, return list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        urls = extract_valid_urls(urls)

        if urls == []:
            raise (
                APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)
                                 )
            )

        aweme_ids = [cls.get_aweme_id(url) for url in urls]
        return await asyncio.gather(*aweme_ids)


class MixIdFetcher:
    @classmethod
    async def get_mix_id(cls, url: str) -> str:
        return


class WebCastIdFetcher:
    _DOUYIN_LIVE_URL_PATTERN = re.compile(r"live/([^/?]*)")
    _DOUYIN_LIVE_URL_PATTERN2 = re.compile(r"http[s]?://live.douyin.com/(\d+)")
    _DOUYIN_LIVE_URL_PATTERN3 = re.compile(r"reflow/([^/?]*)")

    @classmethod
    async def get_webcast_id(cls, url: str) -> str:
        """
        从单个url中获取webcast_id (Get webcast_id from a single url)

        Args:
            url (str): 输入的url (Input url)

        Returns:
            str: 匹配到的webcast_id (Matched webcast_id)。
        """

        if not isinstance(url, str):
            raise TypeError("参数必须是字符串类型")

        url = extract_valid_urls(url)

        if url is None:
            raise (
                APINotFoundError("输入的URL不合法。类名：{0}".format(cls.__name__))
            )
        try:
            transport = httpx.AsyncHTTPTransport(retries=5)
            async with httpx.AsyncClient(
                    **async_client_kwargs(proxies=TokenManager.proxies, transport=transport, timeout=10)
            ) as client:
                response = await client.get(url, follow_redirects=True)
                response.raise_for_status()
                url = str(response.url)

                live_pattern = cls._DOUYIN_LIVE_URL_PATTERN
                live_pattern2 = cls._DOUYIN_LIVE_URL_PATTERN2
                live_pattern3 = cls._DOUYIN_LIVE_URL_PATTERN3

                if live_pattern.search(url):
                    match = live_pattern.search(url)
                elif live_pattern2.search(url):
                    match = live_pattern2.search(url)
                elif live_pattern3.search(url):
                    match = live_pattern3.search(url)
                    logger.warning("该链接返回的是room_id，请使用`fetch_user_live_videos_by_room_id`接口"

                                   )
                else:
                    raise APIResponseError("未在响应的地址中找到webcast_id，检查链接是否为直播页"
                                           )

                return match.group(1)

        except httpx.RequestError as exc:
            raise APIConnectionError("请求端点失败，请检查当前网络环境。 链接：{0}，代理：{1}，异常类名：{2}，异常详细信息：{3}"
                                     .format(url, TokenManager.proxies, cls.__name__, exc)
                                     )

        except httpx.HTTPStatusError as e:
            raise APIResponseError("链接：{0}，状态码 {1}：{2} ".format(
                e.response.url, e.response.status_code, e.response.text
            )
            )

    @classmethod
    async def get_all_webcast_id(cls, urls: list) -> list:
        """
        获取直播webcast_id,传入列表url都可以解析出webcast_id (Get live webcast_id, pass in the list url can parse out webcast_id)

        Args:
            urls: list: 列表url (list url)

        Return:
            webcast_ids: list: 直播的唯一标识，返回列表 (The unique identifier of the live, return list)
        """

        if not isinstance(urls, list):
            raise TypeError("参数必须是列表类型")

        urls = extract_valid_urls(urls)

        if urls == []:
            raise (
                APINotFoundError("输入的URL List不合法。类名：{0}".format(cls.__name__)
                                 )
            )

        webcast_ids = [cls.get_webcast_id(url) for url in urls]
        return await asyncio.gather(*webcast_ids)


def format_file_name(
        naming_template: str,
        aweme_data: dict = {},
        custom_fields: dict = {},
) -> str:
    """
    根据配置文件的全局格式化文件名
    (Format file name according to the global conf file)

    Args:
        aweme_data (dict): 抖音数据的字典 (dict of douyin data)
        naming_template (str): 文件的命名模板, 如 "{create}_{desc}" (Naming template for files, such as "{create}_{desc}")
        custom_fields (dict): 用户自定义字段, 用于替代默认的字段值 (Custom fields for replacing default field values)

    Note:
        windows 文件名长度限制为 255 个字符, 开启了长文件名支持后为 32,767 个字符
        (Windows file name length limit is 255 characters, 32,767 characters after long file name support is enabled)
        Unix 文件名长度限制为 255 个字符
        (Unix file name length limit is 255 characters)
        取去除后的50个字符, 加上后缀, 一般不会超过255个字符
        (Take the removed 50 characters, add the suffix, and generally not exceed 255 characters)
        详细信息请参考: https://en.wikipedia.org/wiki/Filename#Length
        (For more information, please refer to: https://en.wikipedia.org/wiki/Filename#Length)

    Returns:
        str: 格式化的文件名 (Formatted file name)
    """

    os_limit = {
        "win32": 200,
        "cygwin": 60,
        "darwin": 60,
        "linux": 60,
    }

    fields = {
        "create": aweme_data.get("create_time", ""),
        "nickname": aweme_data.get("nickname", ""),
        "aweme_id": aweme_data.get("aweme_id", ""),
        "desc": split_filename(aweme_data.get("desc", ""), os_limit),
        "uid": aweme_data.get("uid", ""),
    }

    if custom_fields:
        fields.update(custom_fields)

    try:
        return naming_template.format(**fields)
    except KeyError as e:
        raise KeyError("文件名模板字段 {0} 不存在，请检查".format(e))


def create_user_folder(kwargs: dict, nickname: Union[str, int]) -> Path:
    """
    根据提供的配置文件和昵称，创建对应的保存目录。
    (Create the corresponding save directory according to the provided conf file and nickname.)

    Args:
        kwargs (dict): 配置文件，字典格式。(Conf file, dict format)
        nickname (Union[str, int]): 用户的昵称，允许字符串或整数。  (User nickname, allow strings or integers)

    Note:
        如果未在配置文件中指定路径，则默认为 "Download"。
        (If the path is not specified in the conf file, it defaults to "Download".)
        支持绝对与相对路径。
        (Support absolute and relative paths)

    Raises:
        TypeError: 如果 kwargs 不是字典格式，将引发 TypeError。
        (If kwargs is not in dict format, TypeError will be raised.)
    """

    if not isinstance(kwargs, dict):
        raise TypeError("kwargs 参数必须是字典")

    base_path = Path(kwargs.get("path", "Download"))

    user_path = (
            base_path / "douyin" / kwargs.get("mode", "PLEASE_SETUP_MODE") / str(nickname)
    )

    resolve_user_path = user_path.resolve()

    resolve_user_path.mkdir(parents=True, exist_ok=True)

    return resolve_user_path


def rename_user_folder(old_path: Path, new_nickname: str) -> Path:
    """
    重命名用户目录 (Rename User Folder).

    Args:
        old_path (Path): 旧的用户目录路径 (Path of the old user folder)
        new_nickname (str): 新的用户昵称 (New user nickname)

    Returns:
        Path: 重命名后的用户目录路径 (Path of the renamed user folder)
    """
    parent_directory = old_path.parent

    new_path = old_path.rename(parent_directory / new_nickname).resolve()

    return new_path


def create_or_rename_user_folder(
        kwargs: dict, local_user_data: dict, current_nickname: str
) -> Path:
    """
    创建或重命名用户目录 (Create or rename user directory)

    Args:
        kwargs (dict): 配置参数 (Conf parameters)
        local_user_data (dict): 本地用户数据 (Local user data)
        current_nickname (str): 当前用户昵称 (Current user nickname)

    Returns:
        user_path (Path): 用户目录路径 (User directory path)
    """
    user_path = create_user_folder(kwargs, current_nickname)

    if not local_user_data:
        return user_path

    if local_user_data.get("nickname") != current_nickname:
        user_path = rename_user_folder(user_path, current_nickname)

    return user_path


def show_qrcode(qrcode_url: str, show_image: bool = False) -> None:
    """
    显示二维码 (Show QR code)

    Args:
        qrcode_url (str): 登录二维码链接 (Login QR code link)
        show_image (bool): 是否显示图像，True 表示显示，False 表示在控制台显示
        (Whether to display the image, True means display, False means display in the console)
    """
    if show_image:
        qr_code_img = qrcode.make(qrcode_url)
        qr_code_img.show()
    else:
        qr = qrcode.QRCode()
        qr.add_data(qrcode_url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)


def json_2_lrc(data: Union[str, list, dict]) -> str:
    """
    从抖音原声json格式歌词生成lrc格式歌词
    (Generate lrc lyrics format from Douyin original json lyrics format)

    Args:
        data (Union[str, list, dict]): 抖音原声json格式歌词 (Douyin original json lyrics format)

    Returns:
        str: 生成的lrc格式歌词 (Generated lrc format lyrics)
    """
    try:
        lrc_lines = []
        for item in data:
            text = item["text"]
            time_seconds = float(item["timeId"])
            minutes = int(time_seconds // 60)
            seconds = int(time_seconds % 60)
            milliseconds = int((time_seconds % 1) * 1000)
            time_str = f"{minutes:02}:{seconds:02}.{milliseconds:03}"
            lrc_lines.append(f"[{time_str}] {text}")
    except KeyError as e:
        raise KeyError("歌词数据字段错误：{0}".format(e))
    except RuntimeError as e:
        raise RuntimeError("生成歌词文件失败：{0}，请检查歌词 `data` 内容".format(e))
    except TypeError as e:
        raise TypeError("歌词数据类型错误：{0}".format(e))
    return "\n".join(lrc_lines)
