"""Compatibility entry for bilibili_crawler.service.credentials; no duplicate runtime state."""
import sys

from bilibili_crawler.service import credentials as _implementation

sys.modules[__name__] = _implementation
