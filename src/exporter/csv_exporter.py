"""
CSV export helpers without heavyweight dataframe dependencies.
"""
import csv
import logging
from typing import Dict, List, Optional

from config.config import CSV_ENCODING

logger = logging.getLogger(__name__)


class CSVExporter:
    COLUMN_MAPPING = {
        "comment_id": "评论ID",
        "root_id": "根评论ID",
        "parent_id": "父评论ID",
        "is_reply": "是否为回复",
        "video_oid": "视频OID",
        "user_id": "用户ID",
        "username": "用户名",
        "user_level": "用户等级",
        "content": "评论内容",
        "like_count": "点赞数",
        "reply_count": "回复数",
        "ctime": "时间戳",
        "ctime_text": "时间",
        "ip_location": "IP归属地",
    }

    DEFAULT_COLUMNS = [
        "comment_id",
        "root_id",
        "is_reply",
        "username",
        "user_level",
        "content",
        "like_count",
        "reply_count",
        "ctime_text",
        "ip_location",
    ]

    COLUMN_MAPPING_DYNAMICS = {
        "dynamic_id": "动态ID",
        "type": "类型",
        "content": "内容",
        "username": "用户名",
        "timestamp": "时间戳",
        "publish_time": "发布时间",
        "like_count": "点赞数",
        "comment_count": "评论数",
        "forward_count": "转发数",
    }

    DEFAULT_COLUMNS_DYNAMICS = [
        "dynamic_id",
        "username",
        "type",
        "content",
        "publish_time",
        "like_count",
        "comment_count",
        "forward_count",
    ]

    @classmethod
    def export(
        cls,
        comments: List[Dict],
        filepath: str,
        columns: Optional[List[str]] = None,
        index: bool = False,
    ) -> bool:
        if not comments:
            logger.warning("没有评论数据可导出")
            return False
        columns = columns or cls.DEFAULT_COLUMNS
        return cls._write_csv(comments, filepath, columns, cls.COLUMN_MAPPING, index)

    @classmethod
    def export_dynamics(
        cls,
        dynamics: List[Dict],
        filepath: str,
        columns: Optional[List[str]] = None,
        index: bool = False,
    ) -> bool:
        if not dynamics:
            logger.warning("没有动态数据可导出")
            return False
        columns = columns or cls.DEFAULT_COLUMNS_DYNAMICS
        return cls._write_csv(dynamics, filepath, columns, cls.COLUMN_MAPPING_DYNAMICS, index)

    @staticmethod
    def _write_csv(
        rows: List[Dict],
        filepath: str,
        columns: Optional[List[str]],
        mapping: Dict[str, str],
        index: bool,
    ) -> bool:
        try:
            if not rows:
                logger.warning("没有数据可导出")
                return False
            if columns is None:
                available = []
                for row in rows:
                    for col in row.keys():
                        if col not in available:
                            available.append(col)
            else:
                available = [col for col in columns if any(col in row for row in rows)]
            if not available:
                available = list(rows[0].keys())
            headers = (["index"] if index else []) + [mapping.get(col, col) for col in available]
            with open(filepath, "w", newline="", encoding=CSV_ENCODING) as fh:
                writer = csv.writer(fh)
                writer.writerow(headers)
                for idx, row in enumerate(rows):
                    values = [row.get(col, "") for col in available]
                    if index:
                        values = [idx] + values
                    writer.writerow(values)
            logger.info("成功导出 %s 条数据到: %s", len(rows), filepath)
            return True
        except Exception as exc:
            logger.error("导出 CSV 时出错: %s", exc)
            return False
