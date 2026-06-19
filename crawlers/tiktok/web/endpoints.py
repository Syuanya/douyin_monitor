class TikTokAPIEndpoints:
    """
    API Endpoints for TikTok
    """

    TIKTOK_DOMAIN = "https://www.tiktok.com"

    WEBCAST_DOMAIN = "https://webcast.tiktok.com"

    LOGIN_ENDPOINT = f"{TIKTOK_DOMAIN}/login/"

    HOME_RECOMMEND = f"{TIKTOK_DOMAIN}/api/recommend/item_list/"

    USER_DETAIL = f"{TIKTOK_DOMAIN}/api/user/detail/"

    USER_POST = f"{TIKTOK_DOMAIN}/api/post/item_list/"

    USER_LIKE = f"{TIKTOK_DOMAIN}/api/favorite/item_list/"

    USER_COLLECT = f"{TIKTOK_DOMAIN}/api/user/collect/item_list/"

    USER_PLAY_LIST = f"{TIKTOK_DOMAIN}/api/user/playlist/"

    USER_MIX = f"{TIKTOK_DOMAIN}/api/mix/item_list/"

    GUESS_YOU_LIKE = f"{TIKTOK_DOMAIN}/api/related/item_list/"

    USER_FOLLOW = f"{TIKTOK_DOMAIN}/api/user/list/"

    USER_FANS = f"{TIKTOK_DOMAIN}/api/user/list/"

    POST_DETAIL = f"{TIKTOK_DOMAIN}/api/item/detail/"

    POST_COMMENT = f"{TIKTOK_DOMAIN}/api/comment/list/"

    POST_COMMENT_REPLY = f"{TIKTOK_DOMAIN}/api/comment/list/reply/"
