# ==============================================================================
# Copyright (C) 2021 Evil0ctal
#
# This file is part of the Douyin_TikTok_Download_API project.
# ============================================================================== 

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from crawlers.douyin.web.web_crawler import DouyinWebCrawler
from crawlers.tiktok.web.web_crawler import TikTokWebCrawler
from crawlers.tiktok.app.app_crawler import TikTokAPPCrawler
from crawlers.utils.api_exceptions import APIResponseError


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _nested(data: Any, *keys: Any) -> Any:
    current: Any = data
    for key in keys:
        if isinstance(current, Mapping):
            current = current.get(key)
        elif isinstance(current, (list, tuple)) and isinstance(key, int):
            if key < 0 or key >= len(current):
                return None
            current = current[key]
        else:
            return None
    return current


def _first_url(value: Any) -> str | None:
    if isinstance(value, Mapping):
        return _first_url(value.get("url_list"))
    if isinstance(value, (list, tuple)):
        for item in value:
            if isinstance(item, str) and item:
                return item
            nested = _first_url(item)
            if nested:
                return nested
    if isinstance(value, str) and value:
        return value
    return None


class HybridCrawler:
    def __init__(self):
        self.DouyinWebCrawler = DouyinWebCrawler()
        self.TikTokWebCrawler = TikTokWebCrawler()
        self.TikTokAPPCrawler = TikTokAPPCrawler()

    async def hybrid_parsing_single_video(self, url: str, minimal: bool = False, cookie: str | None = None):
        if "douyin" in url:
            platform = "douyin"
            aweme_id = await self.DouyinWebCrawler.get_aweme_id(url)
            raw_data = await self.DouyinWebCrawler.fetch_one_video(aweme_id, cookie=cookie)
            data = _as_dict(_as_dict(raw_data).get("aweme_detail"))
        elif "tiktok" in url:
            platform = "tiktok"
            aweme_id = await self.TikTokWebCrawler.get_aweme_id(url)
            data = _as_dict(await self.TikTokAPPCrawler.fetch_one_video(aweme_id))
        else:
            raise ValueError("hybrid_parsing_single_video: Cannot judge the video source from the URL.")

        if not data:
            raise APIResponseError(f"{platform} API response missing video detail for aweme_id={aweme_id}")

        aweme_type = data.get("aweme_type")
        if not minimal:
            return data

        url_type_code_dict = {
            0: "video",
            2: "image",
            4: "video",
            51: "video",
            55: "video",
            58: "video",
            61: "video",
            68: "image",
            150: "image",
        }
        url_type = url_type_code_dict.get(aweme_type, "video")

        result_data = {
            "type": url_type,
            "platform": platform,
            "aweme_id": aweme_id,
            "desc": data.get("desc"),
            "create_time": data.get("create_time"),
            "author": data.get("author"),
            "music": data.get("music"),
            "statistics": data.get("statistics"),
            "cover_data": {
                "cover": _nested(data, "video", "cover"),
                "origin_cover": _nested(data, "video", "origin_cover"),
                "dynamic_cover": _nested(data, "video", "dynamic_cover"),
            },
            "hashtags": data.get("text_extra"),
        }

        api_data: dict[str, Any] = {}
        if platform == "douyin":
            if url_type == "video":
                video = _as_dict(data.get("video"))
                play_addr = _as_dict(video.get("play_addr"))
                uri = str(play_addr.get("uri") or "")
                wm_video_url_hq = _first_url(play_addr.get("url_list"))
                if not uri and not wm_video_url_hq:
                    raise APIResponseError(f"Douyin video response missing play address for aweme_id={aweme_id}")
                wm_video_url = f"https://aweme.snssdk.com/aweme/v1/playwm/?video_id={uri}&radio=1080p&line=0" if uri else wm_video_url_hq
                nwm_video_url_hq = wm_video_url_hq.replace("playwm", "play") if wm_video_url_hq else None
                nwm_video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0" if uri else nwm_video_url_hq
                api_data = {
                    "video_data": {
                        "wm_video_url": wm_video_url,
                        "wm_video_url_HQ": wm_video_url_hq,
                        "nwm_video_url": nwm_video_url,
                        "nwm_video_url_HQ": nwm_video_url_hq,
                    }
                }
            elif url_type == "image":
                no_watermark_image_list: list[str] = []
                watermark_image_list: list[str] = []
                for item in data.get("images") or []:
                    image = _as_dict(item)
                    no_watermark = _first_url(image.get("url_list"))
                    watermark = _first_url(image.get("download_url_list"))
                    if no_watermark:
                        no_watermark_image_list.append(no_watermark)
                    if watermark:
                        watermark_image_list.append(watermark)
                if not no_watermark_image_list and not watermark_image_list:
                    raise APIResponseError(f"Douyin image response missing image urls for aweme_id={aweme_id}")
                api_data = {
                    "image_data": {
                        "no_watermark_image_list": no_watermark_image_list,
                        "watermark_image_list": watermark_image_list,
                    }
                }
        elif platform == "tiktok":
            if url_type == "video":
                video = _as_dict(data.get("video"))
                wm_video = _first_url(_nested(video, "download_addr", "url_list"))
                nwm_video = _first_url(_nested(video, "play_addr", "url_list"))
                nwm_video_hq = _first_url(_nested(video, "bit_rate", 0, "play_addr", "url_list")) or nwm_video
                if not wm_video and not nwm_video:
                    raise APIResponseError(f"TikTok video response missing play address for aweme_id={aweme_id}")
                api_data = {
                    "video_data": {
                        "wm_video_url": wm_video,
                        "wm_video_url_HQ": wm_video,
                        "nwm_video_url": nwm_video,
                        "nwm_video_url_HQ": nwm_video_hq,
                    }
                }
            elif url_type == "image":
                no_watermark_image_list = []
                watermark_image_list = []
                images = _nested(data, "image_post_info", "images") or []
                for item in images:
                    image = _as_dict(item)
                    display = _first_url(_nested(image, "display_image", "url_list"))
                    watermark = _first_url(_nested(image, "owner_watermark_image", "url_list"))
                    if display:
                        no_watermark_image_list.append(display)
                    if watermark:
                        watermark_image_list.append(watermark)
                if not no_watermark_image_list and not watermark_image_list:
                    raise APIResponseError(f"TikTok image response missing image urls for aweme_id={aweme_id}")
                api_data = {
                    "image_data": {
                        "no_watermark_image_list": no_watermark_image_list,
                        "watermark_image_list": watermark_image_list,
                    }
                }
        result_data.update(api_data)
        return result_data
