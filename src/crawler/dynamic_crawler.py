"""Compatibility entry for bilibili_crawler.crawler.dynamic_crawler; no duplicate runtime state."""
import sys

from bilibili_crawler.crawler import dynamic_crawler as _implementation

sys.modules[__name__] = _implementation
