"""Compatibility entry for bilibili_crawler.service.run_store; no duplicate runtime state."""
import sys

from bilibili_crawler.service import run_store as _implementation

sys.modules[__name__] = _implementation
