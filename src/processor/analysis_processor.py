"""Compatibility entry for bilibili_crawler.processor.analysis_processor; no duplicate runtime state."""
import sys

from bilibili_crawler.processor import analysis_processor as _implementation

sys.modules[__name__] = _implementation
