"""Compatibility entry for bilibili_crawler.service.paths; no duplicate runtime state."""
import sys

from bilibili_crawler.service import paths as _implementation

sys.modules[__name__] = _implementation
