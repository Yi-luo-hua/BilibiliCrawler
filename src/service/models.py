"""Compatibility entry for bilibili_crawler.service.models; no duplicate runtime state."""
import sys

from bilibili_crawler.service import models as _implementation

sys.modules[__name__] = _implementation
