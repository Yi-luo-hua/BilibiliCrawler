"""Compatibility entry for bilibili_crawler.utils.helpers; no duplicate runtime state."""
import sys

from bilibili_crawler.utils import helpers as _implementation

sys.modules[__name__] = _implementation
