"""Compatibility entry for bilibili_crawler.crawler.comment_crawler; no duplicate runtime state."""
import sys

from bilibili_crawler.crawler import comment_crawler as _implementation

sys.modules[__name__] = _implementation
