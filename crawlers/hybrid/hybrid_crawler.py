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

from crawlers.douyin.web.web_crawler import DouyinWebCrawler
from crawlers.tiktok.web.web_crawler import TikTokWebCrawler
from crawlers.tiktok.app.app_crawler import TikTokAPPCrawler


class HybridCrawler:
    def __init__(self):
        self.DouyinWebCrawler = DouyinWebCrawler()
        self.TikTokWebCrawler = TikTokWebCrawler()
        self.TikTokAPPCrawler = TikTokAPPCrawler()

    async def hybrid_parsing_single_video(self, url: str, minimal: bool = False):
        if "douyin" in url:
            platform = "douyin"
            aweme_id = await self.DouyinWebCrawler.get_aweme_id(url)
            data = await self.DouyinWebCrawler.fetch_one_video(aweme_id)
            data = data.get("aweme_detail")
            aweme_type = data.get("aweme_type")
        elif "tiktok" in url:
            platform = "tiktok"
            aweme_id = await self.TikTokWebCrawler.get_aweme_id(url)


            data = await self.TikTokAPPCrawler.fetch_one_video(aweme_id)
            aweme_type = data.get("aweme_type")
        else:
            raise ValueError("hybrid_parsing_single_video: Cannot judge the video source from the URL.")

        if not minimal:
            return data

        url_type_code_dict = {
            0: 'video',
            2: 'image',
            4: 'video',
            68: 'image',
            51: 'video',
            55: 'video',
            58: 'video',
            61: 'video',
            150: 'image'
        }
        url_type = url_type_code_dict.get(aweme_type, 'video')

        """
        以下为(视频||图片)数据处理的四个方法,如果你需要自定义数据处理请在这里修改.
        The following are four methods of (video || image) data processing. 
        If you need to customize data processing, please modify it here.
        """

        """
        创建已知数据字典(索引相同)，稍后使用.update()方法更新数据
        Create a known data dictionary (index the same), 
        and then use the .update() method to update the data
        """

        result_data = {
            'type': url_type,
            'platform': platform,
            'aweme_id': aweme_id,
            'desc': data.get("desc"),
            'create_time': data.get("create_time"),
            'author': data.get("author"),
            'music': data.get("music"),
            'statistics': data.get("statistics"),
            'cover_data': {
                'cover': data.get("video").get("cover"),
                'origin_cover': data.get("video").get("origin_cover"),
                'dynamic_cover': data.get("video").get("dynamic_cover")
            },
            'hashtags': data.get('text_extra'),
        }
        api_data = None
        if platform == 'douyin':
            if url_type == 'video':
                uri = data['video']['play_addr']['uri']
                wm_video_url_HQ = data['video']['play_addr']['url_list'][0]
                wm_video_url = f"https://aweme.snssdk.com/aweme/v1/playwm/?video_id={uri}&radio=1080p&line=0"
                nwm_video_url_HQ = wm_video_url_HQ.replace('playwm', 'play')
                nwm_video_url = f"https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0"
                api_data = {
                    'video_data':
                        {
                            'wm_video_url': wm_video_url,
                            'wm_video_url_HQ': wm_video_url_HQ,
                            'nwm_video_url': nwm_video_url,
                            'nwm_video_url_HQ': nwm_video_url_HQ
                        }
                }
            elif url_type == 'image':
                no_watermark_image_list = []
                watermark_image_list = []
                for i in data['images']:
                    no_watermark_image_list.append(i['url_list'][0])
                    watermark_image_list.append(i['download_url_list'][0])
                api_data = {
                    'image_data':
                        {
                            'no_watermark_image_list': no_watermark_image_list,
                            'watermark_image_list': watermark_image_list
                        }
                }
        elif platform == 'tiktok':
            if url_type == 'video':
                wm_video = (
                    data.get('video', {})
                    .get('download_addr', {})
                    .get('url_list', [None])[0]
                )

                api_data = {
                    'video_data':
                        {
                            'wm_video_url': wm_video,
                            'wm_video_url_HQ': wm_video,
                            'nwm_video_url': data['video']['play_addr']['url_list'][0],
                            'nwm_video_url_HQ': data['video']['bit_rate'][0]['play_addr']['url_list'][0]
                        }
                }
            elif url_type == 'image':
                no_watermark_image_list = []
                watermark_image_list = []
                for i in data['image_post_info']['images']:
                    no_watermark_image_list.append(i['display_image']['url_list'][0])
                    watermark_image_list.append(i['owner_watermark_image']['url_list'][0])
                api_data = {
                    'image_data':
                        {
                            'no_watermark_image_list': no_watermark_image_list,
                            'watermark_image_list': watermark_image_list
                        }
                }
        result_data.update(api_data)
        return result_data
