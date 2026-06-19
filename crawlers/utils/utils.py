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

import re
import sys
import random
import secrets
import datetime
import browser_cookie3
try:
    from importlib import resources as importlib_resources
except ImportError:  # pragma: no cover - compatibility for old Python.
    import importlib_resources

from pydantic import BaseModel

from urllib.parse import quote, urlencode
from typing import Union, List, Any
from pathlib import Path

seed_bytes = secrets.token_bytes(16)

seed_int = int.from_bytes(seed_bytes, "big")

random.seed(seed_int)


def model_to_query_string(model: BaseModel) -> str:
    model_dict = model.dict()
    query_string = urlencode(model_dict)
    return query_string


def gen_random_str(randomlength: int) -> str:
    """
    根据传入长度产生随机字符串 (Generate a random string based on the given length)

    Args:
        randomlength (int): 需要生成的随机字符串的长度 (The length of the random string to be generated)

    Returns:
        str: 生成的随机字符串 (The generated random string)
    """

    base_str = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+-"
    return "".join(random.choice(base_str) for _ in range(randomlength))


def get_timestamp(unit: str = "milli"):
    """
    根据给定的单位获取当前时间 (Get the current time based on the given unit)

    Args:
        unit (str): 时间单位，可以是 "milli"、"sec"、"min" 等
            (The time unit, which can be "milli", "sec", "min", etc.)

    Returns:
        int: 根据给定单位的当前时间 (The current time based on the given unit)
    """

    now = datetime.datetime.utcnow() - datetime.datetime(1970, 1, 1)
    if unit == "milli":
        return int(now.total_seconds() * 1000)
    elif unit == "sec":
        return int(now.total_seconds())
    elif unit == "min":
        return int(now.total_seconds() / 60)
    else:
        raise ValueError("Unsupported time unit")


def timestamp_2_str(
        timestamp: Union[str, int, float], format: str = "%Y-%m-%d %H-%M-%S"
) -> str:
    """
    将 UNIX 时间戳转换为格式化字符串 (Convert a UNIX timestamp to a formatted string)

    Args:
        timestamp (int): 要转换的 UNIX 时间戳 (The UNIX timestamp to be converted)
        format (str, optional): 返回的日期时间字符串的格式。
                                默认为 '%Y-%m-%d %H-%M-%S'。
                                (The format for the returned date-time string
                                Defaults to '%Y-%m-%d %H-%M-%S')

    Returns:
        str: 格式化的日期时间字符串 (The formatted date-time string)
    """
    if timestamp is None or timestamp == "None":
        return ""

    if isinstance(timestamp, str):
        if len(timestamp) == 30:
            return datetime.datetime.strptime(timestamp, "%a %b %d %H:%M:%S %z %Y")

    return datetime.datetime.fromtimestamp(float(timestamp)).strftime(format)


def num_to_base36(num: int) -> str:
    """数字转换成base32 (Convert number to base 36)"""

    base_str = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"

    if num == 0:
        return "0"

    base36 = []
    while num:
        num, i = divmod(num, 36)
        base36.append(base_str[i])

    return "".join(reversed(base36))


def split_set_cookie(cookie_str: str) -> str:
    """
    拆分Set-Cookie字符串并拼接 (Split the Set-Cookie string and concatenate)

    Args:
        cookie_str (str): 待拆分的Set-Cookie字符串 (The Set-Cookie string to be split)

    Returns:
        str: 拼接后的Cookie字符串 (Concatenated cookie string)
    """

    if not isinstance(cookie_str, str):
        raise TypeError("`set-cookie` must be str")

    return ";".join(
        cookie.split(";")[0] for cookie in re.split(", (?=[a-zA-Z])", cookie_str)
    )


def split_dict_cookie(cookie_dict: dict) -> str:
    return "; ".join(f"{key}={value}" for key, value in cookie_dict.items())


def extract_valid_urls(inputs: Union[str, List[str]]) -> Union[str, List[str], None]:
    """从输入中提取有效的URL (Extract valid URLs from input)

    Args:
        inputs (Union[str, list[str]]): 输入的字符串或字符串列表 (Input string or list of strings)

    Returns:
        Union[str, list[str]]: 提取出的有效URL或URL列表 (Extracted valid URL or list of URLs)
    """
    url_pattern = re.compile(r"https?://\S+")

    if isinstance(inputs, str):
        match = url_pattern.search(inputs)
        return match.group(0) if match else None

    elif isinstance(inputs, list):
        valid_urls = []

        for input_str in inputs:
            matches = url_pattern.findall(input_str)
            if matches:
                valid_urls.extend(matches)

        return valid_urls


def _get_first_item_from_list(_list) -> list:
    if _list and isinstance(_list, list):
        if isinstance(_list[0], list):
            return [inner[0] for inner in _list if inner]
        else:
            return [_list[0]]
    return []


def get_resource_path(filepath: str):
    """获取资源文件的路径 (Get the path of the resource file)

    Args:
        filepath: str: 文件路径 (file path)
    """

    return importlib_resources.files("f2") / filepath


def replaceT(obj: Union[str, Any]) -> Union[str, Any]:
    """
    替换文案非法字符 (Replace illegal characters in the text)

    Args:
        obj (str): 传入对象 (Input object)

    Returns:
        new: 处理后的内容 (Processed content)
    """

    reSub = r"[^\u4e00-\u9fa5a-zA-Z0-9#]"

    if isinstance(obj, list):
        return [re.sub(reSub, "_", i) for i in obj]

    if isinstance(obj, str):
        return re.sub(reSub, "_", obj)

    return obj


def split_filename(text: str, os_limit: dict) -> str:
    """
    根据操作系统的字符限制分割文件名，并用 '......' 代替。

    Args:
        text (str): 要计算的文本
        os_limit (dict): 操作系统的字符限制字典

    Returns:
        str: 分割后的文本
    """
    os_name = sys.platform
    filename_length_limit = os_limit.get(os_name, 200)

    chinese_length = sum(1 for char in text if "\u4e00" <= char <= "\u9fff") * 3
    english_length = sum(1 for char in text if char.isalpha())
    num_underscores = text.count("_")

    total_length = chinese_length + english_length + num_underscores

    if total_length > filename_length_limit:
        split_index = min(total_length, filename_length_limit) // 2 - 6
        split_text = text[:split_index] + "......" + text[-split_index:]
        return split_text
    else:
        return text


def ensure_path(path: Union[str, Path]) -> Path:
    """确保路径是一个Path对象 (Ensure the path is a Path object)"""
    return Path(path) if isinstance(path, str) else path


def get_cookie_from_browser(browser_choice: str, domain: str = "") -> dict:
    """
    根据用户选择的浏览器获取domain的cookie。

    Args:
        browser_choice (str): 用户选择的浏览器名称

    Returns:
        str: *.domain的cookie值
    """

    if not browser_choice or not domain:
        return ""

    BROWSER_FUNCTIONS = {
        "chrome": browser_cookie3.chrome,
        "firefox": browser_cookie3.firefox,
        "edge": browser_cookie3.edge,
        "opera": browser_cookie3.opera,
        "opera_gx": browser_cookie3.opera_gx,
        "safari": browser_cookie3.safari,
        "chromium": browser_cookie3.chromium,
        "brave": browser_cookie3.brave,
        "vivaldi": browser_cookie3.vivaldi,
        "librewolf": browser_cookie3.librewolf,
    }
    cj_function = BROWSER_FUNCTIONS.get(browser_choice)
    cj = cj_function(domain_name=domain)
    cookie_value = {c.name: c.value for c in cj if c.domain.endswith(domain)}
    return cookie_value


def check_invalid_naming(
        naming: str, allowed_patterns: list, allowed_separators: list
) -> list:
    """
    检查命名是否符合命名模板 (Check if the naming conforms to the naming template)

    Args:
        naming (str): 命名字符串 (Naming string)
        allowed_patterns (list): 允许的模式列表 (List of allowed patterns)
        allowed_separators (list): 允许的分隔符列表 (List of allowed separators)
    Returns:
        list: 无效的模式列表 (List of invalid patterns)
    """
    if not naming or not allowed_patterns or not allowed_separators:
        return []

    temp_naming = naming
    invalid_patterns = []

    for pattern in allowed_patterns:
        if pattern in temp_naming:
            temp_naming = temp_naming.replace(pattern, "")

    for char in temp_naming:
        if char not in allowed_separators:
            invalid_patterns.append(char)

    for pattern in allowed_patterns:
        if pattern + pattern in naming:
            invalid_patterns.append(pattern + pattern)
        for sep in allowed_patterns:
            if pattern + sep + pattern in naming:
                invalid_patterns.append(pattern + sep + pattern)

    return invalid_patterns


def merge_config(
        main_conf: dict = ...,
        custom_conf: dict = ...,
        **kwargs,
):
    """
    合并配置参数，使 CLI 参数优先级高于自定义配置，自定义配置优先级高于主配置，最终生成完整配置参数字典。

    Args:
        main_conf (dict): 主配置参数字典
        custom_conf (dict): 自定义配置参数字典
        **kwargs: CLI 参数和其他额外的配置参数

    Returns:
        dict: 合并后的配置参数字典
    """
    merged_conf = {}
    for key, value in main_conf.items():
        merged_conf[key] = value
    for key, value in custom_conf.items():
        if value is not None and value != "":
            merged_conf[key] = value

    for key, value in kwargs.items():
        if key not in merged_conf:
            merged_conf[key] = value
        elif value is not None and value != "":
            merged_conf[key] = value

    return merged_conf
