from __future__ import annotations

import asyncio
import glob
import html
import json
import os
import re
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit, urlunsplit

import httpx

from ...diagnostics.diagnostic_tools import sanitize_text, sanitize_url
from ...media.cookie_utils import parse_cookie_pool, sanitize_cookie_header
from ...media.file_naming import DEFAULT_FILENAME_TEMPLATE, format_media_filename
from ...media.image_urls import deduplicate_image_urls
from ...media.parser_models import ParsedVideoResult
from ...media.resumable_download import download_http_file
from ...parser import build_douyin_parser_backend
from ...runtime.media_task_queue import report_media_task_progress
from ....utils.logger import logger
from ..models import DouyinContentItem, DouyinMonitorAccount

DOUYIN_HOST_RE = re.compile(r"(^|\.)(douyin\.com|iesdouyin\.com|snssdk\.com)$", re.IGNORECASE)
ITEM_ID_PATTERNS = [
    re.compile(r'"(?:aweme_id|awemeId|item_id|itemId|itemID|id)"\s*:\s*"(\d{8,})"'),
    re.compile(r'"(?:aweme_id|awemeId|item_id|itemId|itemID|id)"\s*:\s*(\d{8,})'),
    re.compile(r'"(?:group_id|groupId|groupID)"\s*:\s*"(\d{8,})"'),
    re.compile(r'"(?:group_id|groupId|groupID)"\s*:\s*(\d{8,})'),
    re.compile(r"/video/(\d{8,})"),
    re.compile(r"/note/(\d{8,})"),
    re.compile(r"/share/video/(\d{8,})"),
]
ITEM_ID_KEYS = ("aweme_id", "awemeId", "item_id", "itemId", "itemID", "group_id", "groupId", "id")
TITLE_KEYS = ("desc", "caption", "title", "text", "share_title", "shareTitle")
CREATE_TIME_KEYS = ("create_time", "createTime", "publish_time", "publishTime")
DOWNLOAD_CHUNK_SIZE = 1024 * 1024
DOWNLOAD_TIMEOUT = httpx.Timeout(60.0, connect=10.0, read=60.0, write=30.0, pool=10.0)
