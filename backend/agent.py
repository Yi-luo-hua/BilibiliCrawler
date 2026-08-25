"""
Thin CLI over AgentService.

Contains no business logic: it parses arguments, calls the service and prints
the result. The `mcp` subcommand launches the stdio MCP server.

    python -m backend.agent mcp
    python -m backend.agent crawl-and-analyze <video-url>
    python -m backend.agent crawl-comments <video-url>
    python -m backend.agent analyze-run <run_id>
    python -m backend.agent status --run-id <run_id>
    python -m backend.agent list-runs
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.service.agent_service import AgentService
from src.service.credentials import install_log_scrubbing, scrub
from src.service.models import (
    MAX_PAGES_DEFAULT,
    SAMPLE_SIZE_DEFAULT,
    ServiceError,
    TaskSnapshot,
    mark_untrusted,
)


def _snapshot_payload(snapshot: TaskSnapshot) -> dict:
    """Render a snapshot for stdout, marking comment-derived text.

    The CLI is a supported way for an agent to drive this tool, so the summary
    gets the same untrusted-data treatment it receives over MCP.
    """
    payload = snapshot.to_dict()
    payload["summary"] = mark_untrusted(payload.get("summary"))
    return payload


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    install_log_scrubbing()


def _print(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _run_blocking(service: AgentService, snapshot: TaskSnapshot, timeout: float) -> TaskSnapshot:
    """Wait for a task, echoing progress to stderr so stdout stays pure JSON."""
    while True:
        for percent, message in service.drain_progress(snapshot.task_id):
            print(f"[{percent:3d}%] {message}", file=sys.stderr)
        current = service.wait(snapshot.task_id, timeout=0.25)
        if current.done:
            for percent, message in service.drain_progress(snapshot.task_id):
                print(f"[{percent:3d}%] {message}", file=sys.stderr)
            return current


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m backend.agent", description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("mcp", help="以 stdio 方式启动 MCP 服务器")
    subparsers.add_parser("list-runs", help="列出本机已有的 run_id")

    def add_crawl_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("url", help="视频链接 / BV 号 / 动态链接 / 专栏链接")
        sub.add_argument("--max-pages", type=int, default=MAX_PAGES_DEFAULT)
        sub.add_argument("--no-replies", action="store_true", help="不爬取楼中楼回复")
        sub.add_argument("--sort-mode", type=int, default=3, help="3=按时间，2=按热度")

    crawl_analyze = subparsers.add_parser("crawl-and-analyze", help="爬取并分析")
    add_crawl_flags(crawl_analyze)
    crawl_analyze.add_argument("--sample-size", type=int, default=SAMPLE_SIZE_DEFAULT)

    crawl_only = subparsers.add_parser("crawl-comments", help="只爬取评论")
    add_crawl_flags(crawl_only)

    analyze = subparsers.add_parser("analyze-run", help="对已有 run 重新分析")
    analyze.add_argument("run_id")
    analyze.add_argument("--sample-size", type=int, default=SAMPLE_SIZE_DEFAULT)
    analyze.add_argument("--strategy", choices=["sample", "all"], default="sample")

    status = subparsers.add_parser("status", help="查询任务状态")
    status.add_argument("--task-id", default="")
    status.add_argument("--run-id", default="")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging()

    if args.command == "mcp":
        # Imported lazily so the other subcommands work without the MCP SDK.
        from backend.mcp_server import main as run_mcp

        run_mcp()
        return 0

    service = AgentService()

    try:
        if args.command == "list-runs":
            _print({"runs": service.store.list_runs(), "root": str(service.store.root)})
            return 0

        if args.command == "status":
            snapshot = service.get_status(task_id=args.task_id or None, run_id=args.run_id or None)
            _print(_snapshot_payload(snapshot))
            return 0

        if args.command == "crawl-comments":
            started = service.start_crawl(
                args.url,
                max_pages=args.max_pages,
                include_replies=not args.no_replies,
                sort_mode=args.sort_mode,
            )
        elif args.command == "crawl-and-analyze":
            started = service.start_crawl_and_analyze(
                args.url,
                max_pages=args.max_pages,
                include_replies=not args.no_replies,
                sort_mode=args.sort_mode,
                sample_size=args.sample_size,
            )
        else:  # analyze-run
            started = service.start_analyze(
                args.run_id,
                sample_size=args.sample_size,
                strategy=args.strategy,
            )
    except ServiceError as exc:
        _print({"ok": False, "error_code": exc.code, "error": scrub(str(exc)), **exc.context})
        return 1

    final = _run_blocking(service, started, timeout=0.25)
    _print(_snapshot_payload(final))
    return 0 if final.status == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
