"""Compatibility entry for bilibili_crawler.config.config; no duplicate runtime state."""
import sys

from bilibili_crawler.config import config as _implementation

sys.modules[__name__] = _implementation
