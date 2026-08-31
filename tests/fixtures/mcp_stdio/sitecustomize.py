"""Opt-in injection for the real ``python -m backend.agent mcp`` test child."""
import os
import sys


def guard_network(event, args):
    # Reject names before the resolver can send DNS, and cover UDP as well as
    # TCP. Literal loopback addresses need no external name resolution.
    if event in {"socket.gethostbyaddr", "socket.getnameinfo"}:
        # Reverse lookup may query DNS even for a literal loopback address;
        # these tests have no reason to resolve a peer's name.
        raise RuntimeError("stdio test only permits loopback network")
    if event in {"socket.getaddrinfo", "socket.gethostbyname"}:
        host = args[0]
    elif event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}:
        address = args[1]
        host = address[0] if isinstance(address, tuple) and address else None
    else:
        return
    if host not in {"127.0.0.1", "::1"}:
        raise RuntimeError("stdio test only permits loopback network")


def configure():
    sys.addaudithook(guard_network)
    from backend.mcp_server import set_service
    from src.service.agent_service import AgentService

    class Crawler:
        def __init__(self, progress):
            self.progress = progress
            self.stopped = False
            self.target_info = {"title": "中文测试视频", "owner": "测试作者"}

        def stop(self):
            self.stopped = True

        def crawl_comments(self, *args, **kwargs):
            self.progress("正在爬取第 1 页中文评论")
            return [] if self.stopped else [{
                "comment_id": 1, "content": "这条中文评论用于真实管道验收", "username": "测试用户",
                "is_reply": False, "like_count": 3, "ctime": 1735660800,
                "ctime_text": "2025-01-01 00:00:00", "ip_location": "广东",
            }]

    set_service(AgentService(api=object(), crawler_factory=Crawler))


if os.environ.get("BILIBILI_TEST_MCP_STDIO") == "1":
    # Fail closed: Python normally continues when sitecustomize raises.
    try:
        configure()
    except Exception:
        os._exit(86)
