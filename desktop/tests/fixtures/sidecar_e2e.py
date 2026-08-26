"""Deterministic process fixture for the desktop-to-Python sidecar contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.sidecar import Sidecar, SidecarServices
from src.processor.analysis_processor import AnalysisCancelled


COMMENT = {
    "comment_id": 1,
    "root_id": 0,
    "is_reply": False,
    "username": "端到端用户",
    "user_level": 5,
    "content": "端到端评论",
    "like_count": 3,
    "reply_count": 0,
    "ctime": 1735660800,
    "ctime_text": "2025-01-01 00:00:00",
    "ip_location": "广东",
}


class FixtureCrawler:
    def __init__(self, progress: Callable[[str], None]) -> None:
        self._progress = progress
        self._stopped = False

    def stop(self) -> None:
        self._stopped = True
        self._progress("正在停止爬取...")

    def crawl_comments(
        self,
        url_or_id: str,
        include_replies: bool = True,
        max_pages: int = 100,
        mode: int = 3,
    ) -> list[dict[str, Any]]:
        self._progress("正在爬取第 1 页评论...")
        return [] if self._stopped else [dict(COMMENT)]


class FixtureAnalysisProcessor:
    def analyze(
        self,
        comments: list[dict[str, Any]],
        dynamics: list[dict[str, Any]],
        params: dict[str, Any],
        progress: Callable[[str, int], None] | None = None,
        cancel_event: Any = None,
    ) -> dict[str, Any]:
        if progress:
            progress("正在调用 LLM", 50)
        model = str((params.get("llm_config") or {}).get("model") or "")
        if model == "block-until-cancel":
            if cancel_event is None or not cancel_event.wait(timeout=5):
                raise AssertionError("fixture analysis did not receive cancellation")
            raise AnalysisCancelled("分析已被取消")
        return {
            "summary": "端到端分析完成",
            "overview": {
                "total_records": len(comments),
                "analyzed_records": len(comments),
                "risk_count": 0,
                "ip_locations": 1,
                "missing_ip_locations": 0,
            },
            "report_markdown": "# 端到端报告",
            "meta": {
                "source": "comments",
                "strategy": params.get("strategy", "sample"),
                "model": model,
                "total_records": len(comments),
                "analyzed_records": len(comments),
                "batch_count": 1,
                "generated_at": "2026-08-26T00:00:00",
                "chart_keys": list(params.get("chart_keys") or []),
                "config": dict(params),
            },
        }


def main() -> None:
    services = SidecarServices(
        api=object(),
        comment_crawler_factory=FixtureCrawler,
        analysis_processor=FixtureAnalysisProcessor(),
    )
    sidecar = Sidecar(services=services)
    sidecar.emit("ready")
    for raw_line in sys.stdin.buffer:
        line = raw_line.decode("utf-8-sig", errors="replace").replace("\x00", "").strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as exc:
            sidecar.emit("error", message=f"请求 JSON 无效: {exc}")
            continue
        sidecar.handle(request)


if __name__ == "__main__":
    main()
