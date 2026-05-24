"""
B站API调用封装模块
- 自适应请求延迟（正常时快速，被限速时退避）
- 迭代式重试（非递归）
- 统一日志接口
- 支持视频、动态、专栏文章
"""
import time
import logging
import requests
from typing import Dict, Optional, Any
from config.config import (
    COMMENT_API_URL,
    REPLY_API_URL,
    DYNAMIC_DETAIL_API_URL,
    ARTICLE_INFO_API_URL,
    SPACE_DYNAMICS_API_URL,
    FOLLOWING_FEED_API_URL,
    PASSPORT_QR_GENERATE_URL,
    PASSPORT_QR_POLL_URL,
    DEFAULT_HEADERS,
    REQUEST_TIMEOUT,
    REQUEST_DELAY_MIN,
    REQUEST_DELAY_MAX,
    REQUEST_DELAY_DEFAULT,
    MAX_RETRIES,
    DEFAULT_PAGE_SIZE,
)

logger = logging.getLogger(__name__)


class BilibiliAPI:
    """B站API调用封装类"""

    def __init__(self, headers: Optional[Dict[str, str]] = None):
        self.headers = headers or DEFAULT_HEADERS.copy()
        self.session = requests.Session()
        self.session.trust_env = False  # 忽略系统代理，避免连接干扰
        self.session.headers.update(self.headers)
        # 自适应延迟：初始值较小，被限速后动态增大
        self._current_delay = REQUEST_DELAY_DEFAULT

    def _adaptive_sleep(self, was_rate_limited: bool = False):
        """
        自适应延迟控制。
        正常时逐步缩短到最小值；被限速时倍增到最大值。
        """
        if was_rate_limited:
            self._current_delay = min(self._current_delay * 2, REQUEST_DELAY_MAX)
        else:
            # 成功时缓慢恢复到最小延迟
            self._current_delay = max(self._current_delay * 0.8, REQUEST_DELAY_MIN)
        time.sleep(self._current_delay)

    def _request(self, url: str, params: Dict[str, Any]) -> Optional[Dict]:
        """
        发送HTTP请求（带重试机制，迭代式）

        Args:
            url: 请求URL
            params: 请求参数

        Returns:
            JSON响应数据，如果请求失败则返回None
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                self._adaptive_sleep(was_rate_limited=(attempt > 0))
                response = self.session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                response.raise_for_status()
                data = response.json()

                code = data.get('code', -1)
                if code == 0:
                    return data

                # -412 = 被风控限速
                if code == -412:
                    logger.warning(f"触发风控(code=-412)，第 {attempt+1} 次重试...")
                    self._adaptive_sleep(was_rate_limited=True)
                    continue

                logger.warning(f"API返回错误: code={code}, message={data.get('message')}")
                return None

            except requests.exceptions.Timeout:
                if attempt < MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(f"请求超时，{wait}s 后重试 ({attempt+1}/{MAX_RETRIES})")
                    time.sleep(wait)
                else:
                    logger.error("请求超时，已达到最大重试次数")
                    return None

            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES:
                    wait = 2 ** attempt
                    logger.warning(f"请求失败 ({attempt+1}/{MAX_RETRIES}): {e}")
                    time.sleep(wait)
                else:
                    logger.error(f"请求失败，已达到最大重试次数: {e}")
                    return None

            except ValueError as e:
                logger.error(f"JSON解析错误: {e}")
                return None

        return None

    # ============================================================
    #  视频相关
    # ============================================================
    def get_video_info(self, bvid: str) -> Optional[Dict]:
        """
        获取视频基本信息（用于获取真实的AV号）

        Args:
            bvid: BV号

        Returns:
            视频信息字典
        """
        url = "https://api.bilibili.com/x/web-interface/view"
        params = {"bvid": bvid}
        return self._request(url, params)

    # ============================================================
    #  动态相关
    # ============================================================
    def get_dynamic_detail(self, dynamic_id: int) -> Optional[Dict]:
        """
        获取动态详情（新版API）

        通过动态详情可以获取评论区的 oid 和 type

        Args:
            dynamic_id: 动态ID

        Returns:
            动态详情字典
        """
        params = {
            "id": dynamic_id,
            "timezone_offset": -480,
        }
        return self._request(DYNAMIC_DETAIL_API_URL, params)

    # ============================================================
    #  专栏文章相关
    # ============================================================
    def get_article_info(self, cvid: int) -> Optional[Dict]:
        """
        获取专栏文章信息

        Args:
            cvid: 文章CV号

        Returns:
            文章信息字典
        """
        params = {"id": cvid}
        return self._request(ARTICLE_INFO_API_URL, params)

    # ============================================================
    #  评论相关（通用）
    # ============================================================
    def get_comments(
        self,
        oid: int,
        page: int = 1,
        mode: int = 3,
        type_id: int = 1,
        next_page: int = 0,
    ) -> Optional[Dict]:
        """
        获取评论列表（通用，支持视频/动态/文章）

        Args:
            oid: 对象ID（视频aid / 动态ID / 文章cvid）
            page: 页码（兼容旧版API）
            mode: 排序模式，3=按时间排序，2=按热度排序
            type_id: 类型ID，1=视频, 11=图文动态, 12=专栏, 17=文字动态
            next_page: 下一页标识（cursor.next值），用于新版API分页

        Returns:
            评论数据字典
        """
        params = {
            "oid": oid,
            "type": type_id,
            "mode": mode,
            "pn": page,
            "ps": DEFAULT_PAGE_SIZE,
            "next": next_page,
        }
        return self._request(COMMENT_API_URL, params)

    def get_replies(
        self, oid: int, root: int, page: int = 1, type_id: int = 1
    ) -> Optional[Dict]:
        """
        获取评论的回复（子评论）

        Args:
            oid: 对象ID
            root: 根评论ID
            page: 页码
            type_id: 类型ID

        Returns:
            回复数据字典
        """
        params = {
            "oid": oid,
            "type": type_id,
            "root": root,
            "pn": page,
            "ps": DEFAULT_PAGE_SIZE,
        }
        return self._request(REPLY_API_URL, params)

    # ============================================================
    #  用户空间动态
    # ============================================================
    def get_user_dynamics(self, host_mid: int, offset: str = "") -> Optional[Dict]:
        """
        获取用户空间动态列表

        Args:
            host_mid: 目标用户UID
            offset: 分页游标（首次请求为空字符串）

        Returns:
            包含 items 列表和翻页信息的字典，失败返回None
        """
        params = {
            "host_mid": host_mid,
            "timezone_offset": -480,
        }
        if offset:
            params["offset"] = offset
        return self._request(SPACE_DYNAMICS_API_URL, params)

    def get_following_feed(self, offset: str = "") -> Optional[Dict]:
        """
        获取关注页动态流（需要登录Cookie）

        Args:
            offset: 分页游标（首次请求为空字符串）

        Returns:
            包含 items 列表和翻页信息的字典，失败返回None
        """
        params = {
            "timezone_offset": -480,
        }
        if offset:
            params["offset"] = offset
        return self._request(FOLLOWING_FEED_API_URL, params)

    # ============================================================
    #  扫码登录
    # ============================================================
    def generate_qrcode(self) -> Optional[tuple]:
        """
        获取登录二维码URL和key

        Returns:
            (url, qrcode_key) 元组，失败返回None
        """
        try:
            r = self.session.get(PASSPORT_QR_GENERATE_URL, timeout=REQUEST_TIMEOUT)
            data = r.json()
            if data.get('code') == 0:
                d = data['data']
                return d['url'], d['qrcode_key']
            logger.error(f"获取二维码失败: code={data.get('code')}, msg={data.get('message')}")
            return None
        except Exception as e:
            logger.error(f"获取二维码异常: {e}")
            return None

    def poll_qrcode(self, qrcode_key: str) -> tuple:
        """
        轮询扫码状态

        Args:
            qrcode_key: 二维码key

        Returns:
            (status_code, cookies_dict_or_none)
            status_code: 0=成功, 86101=未扫码, 86090=已扫码待确认, 86038=过期
        """
        try:
            r = self.session.get(
                PASSPORT_QR_POLL_URL,
                params={"qrcode_key": qrcode_key},
                timeout=REQUEST_TIMEOUT,
            )
            data = r.json()
            # 扫码状态在 data.data.code 中（嵌套结构）
            inner = data.get('data', {})
            status_code = inner.get('code', data.get('code', -1))
            if status_code == 0:
                # 登录成功，从响应头提取cookies
                cookies = {}
                for cookie_name in ['SESSDATA', 'bili_jct', 'DedeUserID', 'sid']:
                    if cookie_name in r.cookies:
                        cookies[cookie_name] = r.cookies[cookie_name]
                cookie_str = '; '.join(f'{k}={v}' for k, v in r.cookies.items())
                if cookie_str:
                    self.set_cookie(cookie_str)
                return 0, cookies
            return status_code, None
        except Exception as e:
            logger.error(f"轮询扫码状态异常: {e}")
            return -1, None

    def set_cookie(self, cookie: str):
        """
        设置Cookie（用于需要登录的场景）

        Args:
            cookie: Cookie字符串
        """
        self.session.headers.update({"Cookie": cookie})
