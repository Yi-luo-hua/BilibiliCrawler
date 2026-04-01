"""
评论爬取核心逻辑模块
- 支持视频、动态、专栏文章的评论爬取
- 主评论串行爬取（保持稳定性）
- 子评论/回复使用 ThreadPoolExecutor 并发爬取（大幅提速）
- 线程安全的日志回调
"""
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import List, Dict, Optional, Callable

from src.api.bilibili_api import BilibiliAPI
from config.config import MAX_REPLY_WORKERS
from utils.helpers import (
    parse_input, ParsedInput, ContentType,
    parse_video_id, validate_bvid,
)

logger = logging.getLogger(__name__)


class CommentCrawler:
    """评论爬虫类（支持视频/动态/专栏文章）"""

    def __init__(self, progress_callback: Optional[Callable[[str], None]] = None):
        """
        初始化爬虫

        Args:
            progress_callback: 进度回调函数，接收日志消息（需线程安全，由调用方保证）
        """
        self.api = BilibiliAPI()
        self.progress_callback = progress_callback or (lambda x: None)
        self._stop_flag = False

    def _log(self, message: str):
        """统一日志输出（同时写 logging 和回调）"""
        logger.info(message)
        self.progress_callback(message)

    def stop(self):
        """停止爬取"""
        self._stop_flag = True
        self._log("正在停止爬取...")

    # ============================================================
    #  OID 解析（支持多种内容类型）
    # ============================================================
    def resolve_target(self, url_or_id: str) -> Optional[ParsedInput]:
        """
        解析用户输入, 返回内容类型和对应的 oid + type_id

        Args:
            url_or_id: 用户输入的 URL 或 ID

        Returns:
            ParsedInput 对象（含 content_type 和 oid），失败返回 None
        """
        parsed = parse_input(url_or_id)
        if not parsed:
            self._log("无法识别输入内容，请输入视频链接/BV号、动态链接或文章链接")
            return None

        # --- 视频 ---
        if parsed.content_type == ContentType.VIDEO:
            return self._resolve_video(parsed)

        # --- 动态 (文字/转发 或 图文/opus) ---
        if parsed.content_type == ContentType.TEXT_DYNAMIC:
            return self._resolve_dynamic(parsed)

        # --- 专栏文章 ---
        if parsed.content_type == ContentType.ARTICLE:
            self._log(f"识别为专栏文章，CV号: {parsed.oid}")
            # 专栏文章的 oid 就是 cvid，type=12
            return parsed

        return None

    def _resolve_video(self, parsed: ParsedInput) -> Optional[ParsedInput]:
        """解析视频，获取 aid 作为 oid"""
        if parsed.oid:
            # 已经有 avid
            self._log(f"识别为视频，AV号: {parsed.oid}")
            return parsed

        if parsed.bvid and validate_bvid(parsed.bvid):
            self._log(f"识别为视频，正在获取信息: {parsed.bvid}")
            video_info = self.api.get_video_info(parsed.bvid)
            if video_info and video_info.get('data'):
                aid = video_info['data'].get('aid')
                if aid:
                    parsed.oid = aid
                    self._log(f"成功获取视频OID: {aid}")
                    return parsed

        self._log("无法获取视频OID，请检查输入的视频ID或URL")
        return None

    def _resolve_dynamic(self, parsed: ParsedInput) -> Optional[ParsedInput]:
        """
        解析动态，通过动态详情 API 获取评论区的真实 oid 和 type

        B站动态评论区的 oid 和 type 取决于动态的具体类型：
        - 纯文字动态: type=17, oid=dynamic_id
        - 图文动态: type=11, oid=图文资源ID
        - 转发动态: type=17, oid=dynamic_id
        """
        dynamic_id = parsed.oid
        self._log(f"识别为动态，ID: {dynamic_id}，正在获取详情...")

        detail = self.api.get_dynamic_detail(dynamic_id)
        if not detail or not detail.get('data'):
            self._log("无法获取动态详情，将使用默认参数(type=17)尝试")
            # fallback: 直接用 dynamic_id 作为 oid, type=17
            parsed.content_type = ContentType.TEXT_DYNAMIC
            return parsed

        item = detail['data'].get('item', {})
        basic = item.get('basic', {})

        # 从 basic.comment_id_str 和 basic.comment_type 获取评论区参数
        comment_id_str = basic.get('comment_id_str', '')
        comment_type = basic.get('comment_type', 0)

        if comment_id_str and comment_type:
            try:
                parsed.oid = int(comment_id_str)
                parsed.content_type = comment_type
                type_label = ContentType.label(comment_type)
                self._log(
                    f"动态详情解析成功: type={comment_type}({type_label}), "
                    f"oid={parsed.oid}"
                )
                return parsed
            except (ValueError, TypeError):
                pass

        # fallback: 用 dynamic_id 作为 oid
        self._log("动态详情解析失败，使用 dynamic_id 作为 oid (type=17)")
        parsed.content_type = ContentType.TEXT_DYNAMIC
        parsed.oid = dynamic_id
        return parsed

    # ============================================================
    #  兼容旧接口
    # ============================================================
    def get_video_oid(self, url_or_id: str) -> Optional[int]:
        """
        获取视频的OID（AV号）—— 兼容旧调用方式

        Args:
            url_or_id: 视频URL、BV号或AV号

        Returns:
            视频OID（AV号），如果获取失败则返回None
        """
        bvid, avid = parse_video_id(url_or_id)

        if avid:
            return avid

        if bvid and validate_bvid(bvid):
            self._log(f"正在获取视频信息: {bvid}")
            video_info = self.api.get_video_info(bvid)
            if video_info and video_info.get('data'):
                oid = video_info['data'].get('aid')
                if oid:
                    self._log(f"成功获取视频OID: {oid}")
                    return oid

        self._log("无法获取视频OID，请检查输入的视频ID或URL")
        return None

    # ============================================================
    #  主爬取逻辑
    # ============================================================
    def crawl_comments(
        self,
        url_or_id: str,
        include_replies: bool = True,
        max_pages: int = 1000,
        mode: int = 3,
    ) -> List[Dict]:
        """
        爬取评论（通用入口，支持视频/动态/文章）

        Args:
            url_or_id: 视频URL/BV号/AV号、动态链接、文章链接
            include_replies: 是否包含子评论（回复）
            max_pages: 最大爬取页数
            mode: 排序模式，3=按时间，2=按热度

        Returns:
            评论列表
        """
        self._stop_flag = False
        all_comments = []

        # 1. 解析用户输入
        target = self.resolve_target(url_or_id)
        if not target or target.oid is None:
            self._log("错误: 无法解析目标内容的OID")
            return all_comments

        oid = target.oid
        type_id = target.content_type
        type_label = ContentType.label(type_id)

        self._log(f"开始爬取评论 | 类型: {type_label} | OID: {oid} | type: {type_id}")

        # 2. 爬取评论
        page = 1
        next_page = 0
        total_replies = 0
        seen_comment_ids = set()

        while page <= max_pages and not self._stop_flag:
            self._log(f"正在爬取第 {page} 页评论...")

            comment_data = self.api.get_comments(
                oid, page=page, mode=mode,
                type_id=type_id, next_page=next_page,
            )

            if not comment_data or not comment_data.get('data'):
                self._log(f"第 {page} 页没有更多评论")
                break

            replies = comment_data['data'].get('replies', [])
            if not replies:
                self._log(f"第 {page} 页评论为空")
                break

            # 去重
            current_page_ids = {r.get('rpid') for r in replies if r.get('rpid')}
            if current_page_ids.issubset(seen_comment_ids):
                self._log("检测到重复数据，已到达最后一页")
                break

            seen_comment_ids.update(current_page_ids)
            self._log(f"第 {page} 页获取到 {len(replies)} 条评论")

            # ---- 收集需要爬取子评论的主评论 ----
            reply_tasks = []  # (root_rpid, rcount)
            for reply in replies:
                if self._stop_flag:
                    break
                comment = self._process_comment(reply, oid, is_reply=False)
                all_comments.append(comment)

                if include_replies:
                    rcount = reply.get('rcount', 0)
                    if rcount > 0:
                        reply_tasks.append((reply.get('rpid'), rcount))

            # ---- 并发爬取子评论 ----
            if reply_tasks and not self._stop_flag:
                self._log(f"  并发爬取 {len(reply_tasks)} 条评论的回复 (workers={MAX_REPLY_WORKERS})...")
                sub_comments = self._crawl_replies_concurrent(oid, reply_tasks, type_id)
                all_comments.extend(sub_comments)
                total_replies += len(sub_comments)

            # 翻页
            cursor = comment_data['data'].get('cursor', {})
            is_end = cursor.get('is_end', True) if cursor else True
            next_page = cursor.get('next', 0) if cursor else 0

            if not is_end and len(replies) > 0 and next_page > 0:
                page += 1
            else:
                self._log("已到达最后一页")
                break

        main_count = len(all_comments) - total_replies
        self._log(
            f"爬取完成！共获取 {len(all_comments)} 条评论"
            f"（主评论: {main_count}, 回复: {total_replies}）"
        )
        return all_comments

    def _crawl_replies_concurrent(
        self, oid: int, tasks: List[tuple], type_id: int = 1,
    ) -> List[Dict]:
        """
        并发爬取多条评论的回复

        Args:
            oid: 对象OID
            tasks: [(root_rpid, rcount), ...]
            type_id: 评论区类型

        Returns:
            所有回复列表
        """
        all_replies = []

        with ThreadPoolExecutor(max_workers=MAX_REPLY_WORKERS) as executor:
            futures = {
                executor.submit(self._crawl_single_reply, oid, root_rpid, type_id): root_rpid
                for root_rpid, rcount in tasks
            }

            for future in as_completed(futures):
                if self._stop_flag:
                    executor.shutdown(wait=False, cancel_futures=True)
                    break
                root_rpid = futures[future]
                try:
                    replies = future.result()
                    all_replies.extend(replies)
                except Exception as e:
                    logger.error(f"爬取评论 {root_rpid} 的回复时出错: {e}")

        return all_replies

    def _crawl_single_reply(
        self, oid: int, root: int, type_id: int = 1,
    ) -> List[Dict]:
        """
        爬取单条评论的所有回复（在工作线程中执行）

        Args:
            oid: 对象OID
            root: 根评论ID
            type_id: 评论区类型

        Returns:
            回复列表
        """
        replies = []
        page = 1

        while not self._stop_flag:
            reply_data = self.api.get_replies(oid, root, page=page, type_id=type_id)

            if not reply_data or not reply_data.get('data'):
                break

            reply_list = reply_data['data'].get('replies', [])
            if not reply_list:
                break

            for reply in reply_list:
                comment = self._process_comment(reply, oid, is_reply=True, root_id=root)
                replies.append(comment)

            cursor = reply_data['data'].get('cursor', {})
            is_end = cursor.get('is_end', True) if cursor else True
            if is_end:
                break

            page += 1

        return replies

    def _process_comment(
        self,
        reply: Dict,
        oid: int,
        is_reply: bool = False,
        root_id: Optional[int] = None,
    ) -> Dict:
        """
        处理单条评论数据

        Args:
            reply: 原始评论数据
            oid: 对象OID
            is_reply: 是否为回复
            root_id: 根评论ID（如果是回复）

        Returns:
            处理后的评论字典
        """
        member = reply.get('member', {})
        content = reply.get('content', {})

        return {
            'comment_id': reply.get('rpid'),
            'root_id': root_id or reply.get('rpid'),
            'parent_id': reply.get('parent'),
            'is_reply': is_reply,
            'video_oid': oid,
            # 用户信息
            'user_id': member.get('mid'),
            'username': member.get('uname', ''),
            'user_level': member.get('level_info', {}).get('current_level', 0),
            # 评论内容
            'content': content.get('message', ''),
            # 统计
            'like_count': reply.get('like', 0),
            'reply_count': reply.get('rcount', 0),
            # 时间
            'ctime': reply.get('ctime', 0),
            'ctime_text': self._timestamp_to_str(reply.get('ctime', 0)),
            # 其他
            'ip_location': reply.get('reply_control', {}).get('location', ''),
        }

    @staticmethod
    def _timestamp_to_str(timestamp: int) -> str:
        """将时间戳转换为可读字符串"""
        if timestamp:
            return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')
        return ''
