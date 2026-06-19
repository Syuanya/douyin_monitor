class DouyinAPIEndpoints:
    """
    API Endpoints for Douyin
    """

    DOUYIN_DOMAIN = "https://www.douyin.com"

    IESDOUYIN_DOMAIN = "https://www.iesdouyin.com"

    LIVE_DOMAIN = "https://live.douyin.com"

    LIVE_DOMAIN2 = "https://webcast.amemv.com"

    SSO_DOMAIN = "https://sso.douyin.com"

    WEBCAST_WSS_DOMAIN = "wss://webcast5-ws-web-lf.douyin.com"

    TAB_FEED = f"{DOUYIN_DOMAIN}/aweme/v1/web/tab/feed/"

    USER_SHORT_INFO = f"{DOUYIN_DOMAIN}/aweme/v1/web/im/user/info/"

    USER_DETAIL = f"{DOUYIN_DOMAIN}/aweme/v1/web/user/profile/other/"

    BASE_AWEME = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/"

    USER_POST = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/post/"

    LOCATE_POST = f"{DOUYIN_DOMAIN}/aweme/v1/web/locate/post/"

    GENERAL_SEARCH = f"{DOUYIN_DOMAIN}/aweme/v1/web/general/search/single/"

    VIDEO_SEARCH = f"{DOUYIN_DOMAIN}/aweme/v1/web/search/item/"

    USER_SEARCH = f"{DOUYIN_DOMAIN}/aweme/v1/web/discover/search/"

    LIVE_SEARCH = f"{DOUYIN_DOMAIN}/aweme/v1/web/live/search/"

    POST_DETAIL = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/detail/"

    POST_DANMAKU = f"{DOUYIN_DOMAIN}/aweme/v1/web/danmaku/get_v2/"

    USER_FAVORITE_A = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/favorite/"

    USER_FAVORITE_B = f"{IESDOUYIN_DOMAIN}/web/api/v2/aweme/like/"

    USER_FOLLOWING = f"{DOUYIN_DOMAIN}/aweme/v1/web/user/following/list/"

    USER_FOLLOWER = f"{DOUYIN_DOMAIN}/aweme/v1/web/user/follower/list/"

    MIX_AWEME = f"{DOUYIN_DOMAIN}/aweme/v1/web/mix/aweme/"

    USER_HISTORY = f"{DOUYIN_DOMAIN}/aweme/v1/web/history/read/"

    USER_COLLECTION = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/listcollection/"

    USER_COLLECTS = f"{DOUYIN_DOMAIN}/aweme/v1/web/collects/list/"

    USER_COLLECTS_VIDEO = f"{DOUYIN_DOMAIN}/aweme/v1/web/collects/video/list/"

    USER_MUSIC_COLLECTION = f"{DOUYIN_DOMAIN}/aweme/v1/web/music/listcollection/"

    FRIEND_FEED = f"{DOUYIN_DOMAIN}/aweme/v1/web/familiar/feed/"

    FOLLOW_FEED = f"{DOUYIN_DOMAIN}/aweme/v1/web/follow/feed/"

    POST_RELATED = f"{DOUYIN_DOMAIN}/aweme/v1/web/aweme/related/"

    FOLLOW_USER_LIVE = f"{DOUYIN_DOMAIN}/webcast/web/feed/follow/"

    LIVE_INFO = f"{LIVE_DOMAIN}/webcast/room/web/enter/"

    LIVE_INFO_ROOM_ID = f"{LIVE_DOMAIN2}/webcast/room/reflow/info/"

    LIVE_GIFT_RANK = f"{LIVE_DOMAIN}/webcast/ranklist/audience/"

    LIVE_USER_INFO = f"{LIVE_DOMAIN}/webcast/user/me/"

    SUGGEST_WORDS = f"{DOUYIN_DOMAIN}/aweme/v1/web/api/suggest_words/"

    SSO_LOGIN_GET_QR = f"{SSO_DOMAIN}/get_qrcode/"

    SSO_LOGIN_CHECK_QR = f"{SSO_DOMAIN}/check_qrconnect/"

    SSO_LOGIN_CHECK_LOGIN = f"{SSO_DOMAIN}/check_login/"

    SSO_LOGIN_REDIRECT = f"{DOUYIN_DOMAIN}/login/"

    SSO_LOGIN_CALLBACK = f"{DOUYIN_DOMAIN}/passport/sso/login/callback/"

    POST_COMMENT = f"{DOUYIN_DOMAIN}/aweme/v1/web/comment/list/"

    POST_COMMENT_REPLY = f"{DOUYIN_DOMAIN}/aweme/v1/web/comment/list/reply/"

    POST_COMMENT_PUBLISH = f"{DOUYIN_DOMAIN}/aweme/v1/web/comment/publish"

    POST_COMMENT_DELETE = f"{DOUYIN_DOMAIN}/aweme/v1/web/comment/delete/"

    POST_COMMENT_DIGG = f"{DOUYIN_DOMAIN}/aweme/v1/web/comment/digg"

    DOUYIN_HOT_SEARCH = f"{DOUYIN_DOMAIN}/aweme/v1/web/hot/search/list/"

    DOUYIN_VIDEO_CHANNEL = f"{DOUYIN_DOMAIN}/aweme/v1/web/channel/feed/"

