"""Compatibility entry for bilibili_crawler.processor.provider_errors; no duplicate runtime state."""
import sys

from bilibili_crawler.processor import provider_errors as _implementation

sys.modules[__name__] = _implementation
