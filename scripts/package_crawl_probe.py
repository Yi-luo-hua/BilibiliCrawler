"""Copied beside the installed smoke; only external HTTP endpoints are fixtures."""
import contextlib
import hashlib
import io
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit


def main():
    import requests
    from bilibili_crawler.agent import main as cli

    calls = []
    key = os.environ["BILIBILI_LLM_API_KEY"]

    class Handler(BaseHTTPRequestHandler):
        def reply(self, data):
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = urlsplit(self.path).path
            calls.append(path)
            if path == "/x/web-interface/view":
                data = {"aid": 170001, "bvid": "BV17x411w7KC", "title": "安装验收视频"}
            elif path == "/x/web-interface/nav":
                data = {"wbi_img": {"img_url": "https://example.invalid/" + "a" * 32 + ".png",
                                     "sub_url": "https://example.invalid/" + "b" * 32 + ".png"}}
            elif path in {"/x/v2/reply/wbi/main", "/x/v2/reply/main"}:
                data = {"replies": [{"rpid": 123, "content": {"message": "真实爬虫安装验证"},
                                     "member": {"uname": "测试用户", "mid": "1"}, "ctime": 1735660800}],
                        "cursor": {"is_end": True, "next": 0}}
            else:
                self.send_error(404)
                return
            self.reply({"code": 0, "data": data})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path == "/v1/chat/completions"
            assert self.headers.get("Authorization") == "Bearer " + key
            assert body["model"] == "test-model"
            calls.append(self.path)
            self.reply({"choices": [{"message": {"content": json.dumps(
                {"summary": "真实分析安装验证 " + key, "insights": ["中文观点"]}, ensure_ascii=False)}}]})

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    origin = f"http://127.0.0.1:{server.server_port}"
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def network_guard(event, args):
        if event in {"socket.gethostbyaddr", "socket.getnameinfo"}:
            raise RuntimeError("package probe forbids DNS")
        if event in {"socket.getaddrinfo", "socket.gethostbyname"}:
            host = args[0]
        elif event in {"socket.connect", "socket.bind", "socket.sendto", "socket.sendmsg"}:
            address = args[1]
            host = address[0] if isinstance(address, tuple) and address else None
        else:
            return
        if host not in {"127.0.0.1", "::1"}:
            raise RuntimeError("package probe only permits loopback")

    sys.addaudithook(network_guard)
    real_send = requests.Session.send

    def send(session, request, **kwargs):
        parsed = urlsplit(request.url)
        if parsed.hostname == "api.bilibili.com":
            request.url = origin + parsed.path + ("?" + parsed.query if parsed.query else "")
        return real_send(session, request, **kwargs)

    def invoke(arguments):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = cli(arguments)
        assert code == 0
        text = output.getvalue()
        assert key not in text
        return json.loads(text)

    try:
        with patch.object(requests.Session, "send", send), patch.dict(
                os.environ, {"BILIBILI_LLM_BASE_URL": origin + "/v1"}):
            crawl = invoke(["crawl-comments", "BV17x411w7KC", "--max-pages", "1", "--no-replies"])
            comments = Path(crawl["artifacts"]["comments_json"])
            assert json.loads(comments.read_text(encoding="utf-8"))[0]["content"] == "真实爬虫安装验证"
            digest = hashlib.sha256(comments.read_bytes()).hexdigest()
            analysis = invoke(["analyze-run", crawl["run_id"], "--sample-size", "1"])
            assert analysis["run_id"] == crawl["run_id"] and analysis["status"] == "completed"
            assert hashlib.sha256(comments.read_bytes()).hexdigest() == digest
            assert "真实分析安装验证" in analysis["summary"]
            for path in comments.parent.rglob("*"):
                if path.is_file():
                    assert key.encode() not in path.read_bytes()
            assert "/x/web-interface/view" in calls and "/v1/chat/completions" in calls
            assert any("/reply/" in path for path in calls)
        print(json.dumps({"real_crawl_and_analysis": True, "http_requests": len(calls)}))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(3)


if __name__ == "__main__":
    main()
