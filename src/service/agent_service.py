"""Compatibility entry for bilibili_crawler.service.agent_service; no duplicate runtime state."""
import sys

from bilibili_crawler.service import agent_service as _implementation

sys.modules[__name__] = _implementation
