"""Opt-in live stdio smoke; without --live this script does nothing external."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_ENV = ("BILIBILI_MCP_SMOKE_URL", "BILIBILI_MCP_SMOKE_MAX_PAGES", "BILIBILI_MCP_SMOKE_SAMPLE_SIZE")


def settings_from_environment() -> dict:
    raw = os.environ.get(REQUIRED_ENV[0], "").strip()
    if re.fullmatch(r"BV[0-9A-Za-z]{10}", raw):
        video = raw
    else:
        parsed = urlsplit(raw)
        match = re.fullmatch(r"/video/(BV[0-9A-Za-z]{10})/?", parsed.path)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"bilibili.com", "www.bilibili.com", "m.bilibili.com"}
                or parsed.username or parsed.password or not match):
            raise ValueError("invalid video")
        video = match.group(1)
    pages = int(os.environ.get(REQUIRED_ENV[1], ""))
    sample = int(os.environ.get(REQUIRED_ENV[2], ""))
    wait = int(os.environ.get("BILIBILI_MCP_SMOKE_WAIT_SECONDS", "90"))
    if not (1 <= pages <= 5 and 20 <= sample <= 300 and 1 <= wait <= 120):
        raise ValueError("invalid smoke bounds")
    return {"video": video, "max_pages": pages, "sample_size": sample, "wait_seconds": wait}


@contextmanager
def quiet_transport_logs():
    # This is a standalone command, not a shared long-running SDK host. A
    # parser's exception logger can echo the offending bytes before we catch
    # its exception. Suppress logging until asyncio transport teardown ends,
    # then restore the caller's setting; never persist those raw records.
    previous = logging.root.manager.disable
    logging.disable(sys.maxsize)
    try:
        yield
    finally:
        logging.disable(previous)


def remember_payload(report: dict, payload: dict) -> None:
    # Update only metadata, never summary/error text or artifact paths. Commit
    # each received snapshot before another await can fail (including close).
    for name in ("run_id", "task_id", "status", "error_code", "counts"):
        if name in payload:
            report[name] = payload[name]
    if "artifacts" in payload:
        report["artifact_names"] = sorted(payload["artifacts"])


async def run_live(settings: dict, report: dict) -> None:
    # These imports are deliberately after the explicit opt-in and validation:
    # the default command works without MCP and never reads a profile.
    from importlib.metadata import version
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client

    report.update(ok=False, sdk_version=version("mcp"))
    env = {name: os.environ[name] for name in (
        "BILIBILI_AGENT_RUNS_DIR", "BILIBILI_AGENT_CREDENTIALS", "BILIBILI_LLM_API_KEY",
        "BILIBILI_LLM_BASE_URL", "BILIBILI_LLM_MODEL",
    ) if name in os.environ}
    env.update(PYTHONPATH=str(ROOT), PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    params = StdioServerParameters(command=sys.executable, args=["-m", "backend.agent", "mcp"], cwd=ROOT, env=env)
    with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr:
        async with Client(stdio_client(params, errlog=stderr), read_timeout_seconds=settings["wait_seconds"] + 15) as client:
            tools = await client.list_tools()
            report["tools"] = sorted(tool.name for tool in tools.tools)
            result = await client.call_tool("crawl_and_analyze", {
                "url": settings["video"], "max_pages": settings["max_pages"], "include_replies": False,
                "sample_size": settings["sample_size"], "wait_seconds": settings["wait_seconds"],
            })
            payload = result.structured_content or {}
            remember_payload(report, payload)
            incomplete = not payload.get("done", True)
            report["wait_window_exceeded"] = incomplete
            if incomplete and payload.get("task_id"):
                # Do not leave a background paid task running after a bounded
                # smoke. A remote provider may still bill an in-flight request.
                task_id = payload["task_id"]
                stopped = await client.call_tool("stop_task", {"task_id": task_id})
                payload = stopped.structured_content or payload
                remember_payload(report, payload)
                deadline = time.monotonic() + 5
                while not payload.get("done") and time.monotonic() < deadline:
                    await asyncio.sleep(0.1)
                    status = await client.call_tool("get_task_status", {"task_id": task_id})
                    payload = status.structured_content or payload
                    remember_payload(report, payload)
            report.setdefault("status", "tool_error")
            report["ok"] = not result.is_error and not incomplete and payload.get("status") == "completed"


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="明确允许访问 B 站及已配置的模型；可能产生费用")
    args = parser.parse_args(argv)
    if not args.live:
        print(json.dumps({"live": False, "skipped": True, "required_environment": REQUIRED_ENV,
                          "next_step": "设置目标、页数和样本量后显式传 --live；可能产生模型费用。"}, ensure_ascii=True))
        return 0
    try:
        settings = settings_from_environment()
    except ValueError:
        print(json.dumps({"ok": False, "error_code": "INVALID_SMOKE_CONFIG", "required_environment": REQUIRED_ENV,
                          "limits": "BV号或视频URL；max_pages=1..5；sample_size=20..300；wait_seconds=1..120"}, ensure_ascii=True))
        return 1
    started = time.monotonic()
    report = {"live": True, "started_at": datetime.now(timezone.utc).isoformat(), **settings, "include_replies": False}
    with quiet_transport_logs():
        try:
            asyncio.run(run_live(settings, report))
        except Exception as exc:
            # Preserve already received metadata, but never raw exception text.
            report.update(ok=False, error_code="SMOKE_FAILED", error_type=type(exc).__name__)
    report["elapsed_seconds"] = round(time.monotonic() - started, 2)
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
