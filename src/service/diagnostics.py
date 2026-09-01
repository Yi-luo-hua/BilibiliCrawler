"""Compatibility entry for bilibili_crawler.service.diagnostics; no duplicate runtime state."""
import sys

from bilibili_crawler.service import diagnostics as _implementation

sys.modules[__name__] = _implementation
