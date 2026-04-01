"""
工具函数模块
- 支持视频(BV号/AV号)、动态(dynamic_id)、文章(cv号)、opus链接解析
"""
import re
from typing import Optional, Tuple


# ============================================================
#  内容类型常量
# ============================================================
class ContentType:
    """B站评论区 type 参数枚举"""
    VIDEO = 1       # 视频
    PHOTO_DYNAMIC = 11  # 图文动态/相簿
    ARTICLE = 12    # 专栏文章
    TEXT_DYNAMIC = 17   # 纯文字/转发动态

    @staticmethod
    def label(type_id: int) -> str:
        return {
            1: "视频",
            11: "图文动态",
            12: "专栏文章",
            17: "动态",
        }.get(type_id, f"未知类型({type_id})")


# ============================================================
#  视频 ID 解析
# ============================================================
def extract_bvid(url_or_id: str) -> Optional[str]:
    """
    从URL或字符串中提取BV号

    Args:
        url_or_id: 视频URL或BV号字符串

    Returns:
        BV号字符串，如果无法提取则返回None
    """
    bv_pattern = r'[Bb][Vv]([A-Za-z0-9]{10})'
    match = re.search(bv_pattern, url_or_id)
    if match:
        return f"BV{match.group(1)}"
    return None


def extract_avid(url_or_id: str) -> Optional[int]:
    """
    从URL或字符串中提取AV号

    Args:
        url_or_id: 视频URL或AV号字符串

    Returns:
        AV号整数，如果无法提取则返回None
    """
    av_pattern = r'[Aa][Vv](\d+)'
    match = re.search(av_pattern, url_or_id)
    if match:
        return int(match.group(1))
    return None


def parse_video_id(url_or_id: str) -> Tuple[Optional[str], Optional[int]]:
    """
    解析视频ID，返回BV号和AV号

    Args:
        url_or_id: 视频URL、BV号或AV号

    Returns:
        (BV号, AV号) 元组
    """
    bvid = extract_bvid(url_or_id)
    avid = extract_avid(url_or_id)
    return bvid, avid


def validate_bvid(bvid: str) -> bool:
    """
    验证BV号格式是否正确

    Args:
        bvid: BV号字符串

    Returns:
        如果格式正确返回True，否则返回False
    """
    if not bvid:
        return False
    pattern = r'^[Bb][Vv][A-Za-z0-9]{10}$'
    return bool(re.match(pattern, bvid))


# ============================================================
#  动态 ID 解析
# ============================================================
def extract_dynamic_id(url_or_id: str) -> Optional[int]:
    """
    从URL或字符串中提取动态ID

    支持的格式:
        - https://t.bilibili.com/123456789
        - https://www.bilibili.com/opus/123456789
        - 纯数字 (长度 > 12 位的大数字视为动态ID)

    Args:
        url_or_id: 动态URL或ID字符串

    Returns:
        动态ID整数，如果无法提取则返回None
    """
    url_or_id = url_or_id.strip()

    # t.bilibili.com/数字
    match = re.search(r't\.bilibili\.com/(\d+)', url_or_id)
    if match:
        return int(match.group(1))

    # bilibili.com/opus/数字
    match = re.search(r'bilibili\.com/opus/(\d+)', url_or_id)
    if match:
        return int(match.group(1))

    return None


# ============================================================
#  专栏文章 CV 号解析
# ============================================================
def extract_cvid(url_or_id: str) -> Optional[int]:
    """
    从URL或字符串中提取专栏文章CV号

    支持的格式:
        - https://www.bilibili.com/read/cv12345
        - cv12345
        - CV12345

    Args:
        url_or_id: 文章URL或CV号字符串

    Returns:
        CV号整数，如果无法提取则返回None
    """
    url_or_id = url_or_id.strip()

    # bilibili.com/read/cv数字
    match = re.search(r'bilibili\.com/read/[Cc][Vv](\d+)', url_or_id)
    if match:
        return int(match.group(1))

    # 纯cv号: cv12345
    match = re.match(r'^[Cc][Vv](\d+)$', url_or_id)
    if match:
        return int(match.group(1))

    return None


# ============================================================
#  统一输入解析
# ============================================================
class ParsedInput:
    """解析后的用户输入"""
    __slots__ = ('content_type', 'oid', 'bvid', 'raw_input')

    def __init__(self, content_type: int, oid: Optional[int] = None,
                 bvid: Optional[str] = None, raw_input: str = ''):
        self.content_type = content_type
        self.oid = oid
        self.bvid = bvid
        self.raw_input = raw_input

    def __repr__(self):
        return (f"ParsedInput(type={ContentType.label(self.content_type)}, "
                f"oid={self.oid}, bvid={self.bvid})")


def parse_input(url_or_id: str) -> Optional[ParsedInput]:
    """
    统一解析用户输入，自动识别内容类型

    优先级: 专栏文章 > 动态 > 视频

    Args:
        url_or_id: 用户输入的URL或ID

    Returns:
        ParsedInput 对象，如果无法解析则返回None
    """
    url_or_id = url_or_id.strip()
    if not url_or_id:
        return None

    # 1. 专栏文章 (cv号)
    cvid = extract_cvid(url_or_id)
    if cvid:
        return ParsedInput(
            content_type=ContentType.ARTICLE,
            oid=cvid,
            raw_input=url_or_id,
        )

    # 2. 动态 (t.bilibili.com 或 opus)
    dynamic_id = extract_dynamic_id(url_or_id)
    if dynamic_id:
        return ParsedInput(
            content_type=ContentType.TEXT_DYNAMIC,
            oid=dynamic_id,
            raw_input=url_or_id,
        )

    # 3. 视频 (BV号 / AV号)
    bvid, avid = parse_video_id(url_or_id)
    if bvid or avid:
        return ParsedInput(
            content_type=ContentType.VIDEO,
            oid=avid,
            bvid=bvid,
            raw_input=url_or_id,
        )

    return None
