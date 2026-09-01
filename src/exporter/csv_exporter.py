"""Compatibility entry for bilibili_crawler.exporter.csv_exporter; no duplicate runtime state."""
import sys

from bilibili_crawler.exporter import csv_exporter as _implementation

sys.modules[__name__] = _implementation
