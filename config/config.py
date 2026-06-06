"""
B站评论爬虫配置文件
"""
# B站评论API端点
COMMENT_API_URL = "https://api.bilibili.com/x/v2/reply/main"
COMMENT_WBI_API_URL = "https://api.bilibili.com/x/v2/reply/wbi/main"
REPLY_API_URL = "https://api.bilibili.com/x/v2/reply/reply"
NAV_API_URL = "https://api.bilibili.com/x/web-interface/nav"

# 动态详情API（新版）
DYNAMIC_DETAIL_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/detail"

# 专栏文章信息API
ARTICLE_INFO_API_URL = "https://api.bilibili.com/x/article/viewinfo"

# 请求头配置
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.bilibili.com/",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "Origin": "https://www.bilibili.com",
}

# 请求配置
REQUEST_TIMEOUT = 10        # 请求超时时间（秒）
REQUEST_DELAY_MIN = 0.1     # 正常请求最小间隔（秒）
REQUEST_DELAY_MAX = 2.0     # 被限速时最大间隔（秒）
REQUEST_DELAY_DEFAULT = 0.15  # 默认请求间隔（秒）
MAX_RETRIES = 3             # 最大重试次数

# 分页配置
DEFAULT_PAGE_SIZE = 30      # 每页评论/回复数量（B站API最大30）
MAX_PAGES = 1000            # 最大爬取页数（防止无限爬取）

# 并发配置
MAX_REPLY_WORKERS = 4       # 子评论并发爬取线程数

# 用户空间动态API
SPACE_DYNAMICS_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/space"
# 关注页动态流API（需要登录Cookie）
FOLLOWING_FEED_API_URL = "https://api.bilibili.com/x/polymer/web-dynamic/v1/feed/all"
MAX_DYNAMICS_PAGES = 100

# 扫码登录API
PASSPORT_QR_GENERATE_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/generate"
PASSPORT_QR_POLL_URL = "https://passport.bilibili.com/x/passport-login/web/qrcode/poll"

# CSV导出配置
CSV_ENCODING = "utf-8-sig"  # UTF-8 with BOM，Excel可以正确识别中文
