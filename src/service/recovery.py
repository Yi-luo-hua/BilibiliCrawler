"""Compatibility entry for bilibili_crawler.service.recovery; no duplicate runtime state."""
import sys

from bilibili_crawler.service import recovery as _implementation

sys.modules[__name__] = _implementation
