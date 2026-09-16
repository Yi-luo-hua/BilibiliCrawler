"""
Thin CLI over AgentService.

Contains no business logic: it parses arguments, calls the service and prints
the result. The `mcp` subcommand launches the stdio MCP server.

    python -m bilibili_crawler mcp
    python -m bilibili_crawler crawl-and-analyze <video-url>
    python -m bilibili_crawler crawl-comments <video-url>
    python -m bilibili_crawler analyze-run <run_id>
    python -m bilibili_crawler status --run-id <run_id>
    python -m bilibili_crawler list-runs
    python -m bilibili_crawler doctor
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bilibili_crawler.service.agent_service import AgentService
from bilibili_crawler import resolve_version
from bilibili_crawler.service.credentials import install_log_scrubbing, scrub
from bilibili_crawler.service.recovery import analysis_recovery_hint
from bilibili_crawler.service.models import (
    MAX_PAGES_DEFAULT,
    SAMPLE_SIZE_DEFAULT,
    ErrorCode,
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
    recovery = analysis_recovery_hint(snapshot, cli=True)
    if recovery:
        payload["next_step"] = recovery
    return payload


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    install_log_scrubbing()


def _print(payload: dict, *, ascii_safe: bool = False) -> None:
    print(json.dumps(payload, ensure_ascii=ascii_safe, indent=2))


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


class _VersionAction(argparse.Action):
    """argparse's own version action wants the string up front.

    Resolving it there would cost a dist-info scan on every invocation, for a
    flag almost nobody passes.
    """

    def __init__(self, option_strings, dest=argparse.SUPPRESS, help="输出版本号并退出"):
        super().__init__(option_strings=option_strings, dest=dest, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"bilibili-crawler {resolve_version()}")
        parser.exit()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bilibili-crawler", description=__doc__)
    parser.add_argument("--version", action=_VersionAction)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("mcp", help="以 stdio 方式启动 MCP 服务器")
    subparsers.add_parser("list-runs", help="列出本机已有的 run_id")
    doctor = subparsers.add_parser("doctor", help="只读检查 LLM 配置、MCP SDK 与运行目录；不显示 Key")
    doctor.add_argument("--check-provider", action="store_true", help="显式请求 GET /models 连通性检查，不发送分析")
    doctor.add_argument("--timeout", type=float, default=10.0, help="连通性检查连接/读取超时，0–60 秒（默认 10）")

    def add_crawl_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument("url", help="视频链接 / BV 号 / 动态链接 / 专栏链接")
        sub.add_argument(
            "--max-pages", type=int, default=MAX_PAGES_DEFAULT,
            help=f"主评论页数，每页 30 条（默认 {MAX_PAGES_DEFAULT}）；0 表示爬完整个评论区。楼中楼回复全部爬取、不计页数",
        )
        sub.add_argument("--no-replies", action="store_true", help="不爬取楼中楼回复")
        sub.add_argument("--sort-mode", type=int, default=3, help="3=按时间，2=按热度")
        sub.add_argument(
            "--cookie",
            default="",
            help="B 站 Cookie（形如 'SESSDATA=...; bili_jct=...'）；"
                 "不传则读环境变量 BILIBILI_COOKIE，都没有就匿名爬取（评论 IP 属地为空）",
        )

    def add_analysis_flags(sub: argparse.ArgumentParser) -> None:
        sub.add_argument(
            "--sample-size", type=int, default=SAMPLE_SIZE_DEFAULT,
            help=f"抽样分析的评论条数（默认 {SAMPLE_SIZE_DEFAULT}），不设上限；超过 2000 会提醒耗时和费用",
        )
        sub.add_argument("--strategy", choices=["sample", "all"], default="sample",
                         help="sample=抽样，all=全量（忽略 --sample-size）")
        sub.add_argument("--batch-size", type=int, default=None, help="每次 LLM 请求的评论条数（默认 80）")
        sub.add_argument(
            "--charts", default="",
            help="逗号分隔的分析模块；不传则用默认 6 个。可选：sentiment_distribution, topic_ranking, "
                 "time_trend, level_distribution, region_map, word_cloud, deep_analysis",
        )
        sub.add_argument(
            "--custom-module", action="append", default=[], metavar="标题=提示",
            help="自定义分析视角，可重复，例如 --custom-module \"传播路径=分析争议如何扩散\"",
        )

    crawl_analyze = subparsers.add_parser("crawl-and-analyze", help="爬取并分析")
    add_crawl_flags(crawl_analyze)
    add_analysis_flags(crawl_analyze)

    crawl_only = subparsers.add_parser("crawl-comments", help="只爬取评论")
    add_crawl_flags(crawl_only)

    analyze = subparsers.add_parser("analyze-run", help="对已有 run 重新分析")
    analyze.add_argument("run_id")
    add_analysis_flags(analyze)

    status = subparsers.add_parser("status", help="查询任务状态")
    status.add_argument("--task-id", default="")
    status.add_argument("--run-id", default="")

    return parser


def _analysis_kwargs(args: argparse.Namespace) -> dict:
    charts = [item.strip() for item in str(args.charts or "").split(",") if item.strip()]
    modules = []
    for raw in args.custom_module:
        title, separator, prompt = str(raw).partition("=")
        if not separator or not title.strip() or not prompt.strip():
            raise ServiceError(ErrorCode.INVALID_INPUT, f"--custom-module 需要写成 标题=提示：{raw!r}")
        modules.append({"title": title.strip(), "prompt": prompt.strip()})
    return {
        "sample_size": args.sample_size,
        "strategy": args.strategy,
        "batch_size": args.batch_size,
        "chart_keys": charts or None,
        "custom_modules": modules or None,
    }


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _configure_logging()

    if args.command == "doctor":
        from bilibili_crawler.service.diagnostics import diagnose

        if not 0 < args.timeout <= 60:
            _print({"ok": False, "error_code": "INVALID_INPUT", "error": "--timeout 必须大于 0 且不超过 60 秒。"}, ascii_safe=True)
            return 1
        payload = diagnose(check_provider=args.check_provider, timeout=args.timeout)
        # ASCII escapes keep this diagnostic JSON readable by UTF-8 hosts even
        # when launched from a legacy GBK Windows console.
        _print(payload, ascii_safe=True)
        return 0 if payload["ok"] else 1

    if args.command == "mcp":
        # Imported lazily so the other subcommands work without the MCP SDK.
        import importlib.util
        if importlib.util.find_spec("mcp") is None:
            print('MCP SDK 未安装；请运行 pip install "bilibili-crawler[mcp]"。', file=sys.stderr)
            return 2
        from bilibili_crawler.mcp_server import main as run_mcp

        run_mcp()
        return 0

    from bilibili_crawler.service.agent_service import AgentService

    # A cookie on the command line is visible to `ps`/history, so the flag is a
    # convenience over BILIBILI_COOKIE rather than the recommended channel.
    service = AgentService(cookie=getattr(args, "cookie", ""))

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
                **_analysis_kwargs(args),
            )
        else:  # analyze-run
            started = service.start_analyze(args.run_id, **_analysis_kwargs(args))
    except ServiceError as exc:
        _print({"ok": False, "error_code": exc.code, "error": scrub(str(exc)), **exc.context})
        return 1

    final = _run_blocking(service, started, timeout=0.25)
    _print(_snapshot_payload(final))
    return 0 if final.status == "completed" else 1


def mcp_main() -> int:
    """Dedicated console script, retaining argparse's --help support."""
    return main(["mcp", *sys.argv[1:]])


if __name__ == "__main__":
    raise SystemExit(main())
