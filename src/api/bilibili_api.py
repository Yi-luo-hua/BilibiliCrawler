"""Compatibility entry for bilibili_crawler.api.bilibili_api; no duplicate runtime state."""
import sys

from bilibili_crawler.api import bilibili_api as _implementation

sys.modules[__name__] = _implementation
