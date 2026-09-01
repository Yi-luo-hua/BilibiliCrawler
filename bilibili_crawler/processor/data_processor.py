"""
数据处理和清洗模块
"""
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class DataProcessor:
    """数据处理器类"""

    @staticmethod
    def clean_comments(comments: List[Dict]) -> List[Dict]:
        """
        清洗评论数据

        Args:
            comments: 原始评论列表

        Returns:
            清洗后的评论列表
        """
        cleaned = []
        for comment in comments:
            # 移除空评论
            if not comment.get('content', '').strip():
                continue

            # 清理内容中的多余空白
            content = comment.get('content', '')
            content = ' '.join(content.split())
            comment['content'] = content

            # 确保所有必需字段都存在
            comment.setdefault('comment_id', 0)
            comment.setdefault('root_id', 0)
            comment.setdefault('parent_id', 0)
            comment.setdefault('is_reply', False)
            comment.setdefault('user_id', 0)
            comment.setdefault('username', '')
            comment.setdefault('user_level', 0)
            comment.setdefault('like_count', 0)
            comment.setdefault('reply_count', 0)
            comment.setdefault('ctime', 0)
            comment.setdefault('ctime_text', '')
            comment.setdefault('ip_location', '')

            cleaned.append(comment)

        return cleaned

    @staticmethod
    def filter_comments(comments: List[Dict], filters: Optional[Dict] = None) -> List[Dict]:
        """
        过滤评论

        Args:
            comments: 评论列表
            filters: 过滤条件字典，例如：
                {
                    'min_likes': 10,
                    'min_level': 3,
                    'keyword': '关键词',
                }

        Returns:
            过滤后的评论列表
        """
        if not filters:
            return comments

        filtered = []
        for comment in comments:
            if 'min_likes' in filters:
                if comment.get('like_count', 0) < filters['min_likes']:
                    continue

            if 'min_level' in filters:
                if comment.get('user_level', 0) < filters['min_level']:
                    continue

            if 'keyword' in filters:
                keyword = filters['keyword'].lower()
                if keyword not in comment.get('content', '').lower():
                    continue

            filtered.append(comment)

        return filtered

    @staticmethod
    def filter_dynamics(dynamics: List[Dict], keyword: str = "") -> List[Dict]:
        """
        按关键词过滤动态数据

        Args:
            dynamics: 动态列表
            keyword: 过滤关键词（不区分大小写），为空则返回全部

        Returns:
            过滤后的动态列表
        """
        if not keyword:
            return dynamics

        kw = keyword.lower()
        return [d for d in dynamics if kw in d.get('content', '').lower()]

    @staticmethod
    def get_statistics(comments: List[Dict]) -> Dict:
        """
        获取评论统计信息

        Args:
            comments: 评论列表

        Returns:
            统计信息字典
        """
        if not comments:
            return {
                'total': 0,
                'main_comments': 0,
                'replies': 0,
                'total_likes': 0,
                'avg_likes': 0,
                'total_replies': 0,
                'ip_locations': 0,
                'missing_ip_locations': 0,
                'ip_location_coverage': 0,
            }

        main_comments = [c for c in comments if not c.get('is_reply', False)]
        replies = [c for c in comments if c.get('is_reply', False)]

        total_likes = sum(c.get('like_count', 0) for c in comments)
        total_replies = sum(c.get('reply_count', 0) for c in main_comments)
        ip_locations = sum(1 for c in comments if str(c.get('ip_location') or '').strip())
        missing_ip_locations = len(comments) - ip_locations

        return {
            'total': len(comments),
            'main_comments': len(main_comments),
            'replies': len(replies),
            'total_likes': total_likes,
            'avg_likes': round(total_likes / len(comments), 2) if comments else 0,
            'total_replies': total_replies,
            'ip_locations': ip_locations,
            'missing_ip_locations': missing_ip_locations,
            'ip_location_coverage': round(ip_locations / len(comments), 4) if comments else 0,
        }
