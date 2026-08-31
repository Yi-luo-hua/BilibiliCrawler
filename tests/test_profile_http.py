"""Drive the real service/processor through a local provider, including echoes."""
import hashlib
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.service.agent_service import AgentService
from src.service.run_store import RunStore


KEY = "sk-http-profile-canary-567890"
OVERRIDE_KEY = "sk-http-override-canary-123456"


class ProfileHTTPTests(unittest.TestCase):
    def test_profile_reaches_real_requests_and_echoes_are_scrubbed_from_all_run_files(self):
        seen = []

        class Provider(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                seen.append((self.path, self.headers.get("Authorization"), body["model"]))
                # Deliberately echo both keys in a field rendered to JSON and
                # Markdown; a benign processor would not test the leak boundary.
                content = {"summary": f"中文总结 {KEY} {OVERRIDE_KEY}", "summary_points": [KEY]}
                encoded = json.dumps({"choices": [{"message": {"content": json.dumps(content)}}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *args):
                pass

        class Crawler:
            def __init__(self, progress):
                pass

            def crawl_comments(self, *args, **kwargs):
                return [{"comment_id": 1, "content": "中文评论", "username": "测试用户",
                         "is_reply": False, "like_count": 2, "ctime": 1735660800}]

        server = ThreadingHTTPServer(("127.0.0.1", 0), Provider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                credential_path = root / "credentials.json"
                credential_path.write_text(json.dumps({"api_key": KEY}), encoding="utf-8")
                (root / "ui.json").write_text(json.dumps({
                    "llm_base_url": f"http://127.0.0.1:{server.server_port}/custom/v1",
                    "llm_model": "桌面模型",
                }), encoding="utf-8")
                with patch.dict(os.environ, {"BILIBILI_AGENT_CREDENTIALS": str(credential_path)}, clear=True):
                    store = RunStore(root / "runs")
                    service = AgentService(store=store, api=object(), crawler_factory=Crawler)
                    # Register the second test key before the first artificial
                    # provider echo. It models a previously used credential.
                    from src.service.credentials import register_secret
                    register_secret(OVERRIDE_KEY)
                    started = service.start_crawl_and_analyze("BV1xx411c7mD", max_pages=1)
                    final = service.wait(started.task_id, 15)
                    self.assertEqual(final.status, "completed", final.error)
                    from backend.agent import _snapshot_payload
                    self.assertNotIn(KEY, json.dumps(_snapshot_payload(final)))
                    comment_file = store.run_dir(final.run_id) / "comments.json"
                    digest = hashlib.sha256(comment_file.read_bytes()).hexdigest()
                    with patch.dict(os.environ, {
                        "BILIBILI_LLM_API_KEY": OVERRIDE_KEY, "BILIBILI_LLM_MODEL": "env-model",
                    }):
                        retried = service.start_analyze(final.run_id)
                        retry_result = service.wait(retried.task_id, 15)
                    self.assertEqual(retry_result.status, "completed", retry_result.error)
                    self.assertEqual(digest, hashlib.sha256(comment_file.read_bytes()).hexdigest())
                    paths = [p for p in store.root.rglob("*") if p.is_file()]
                    self.assertTrue(any("archive" in p.parts for p in paths))
                    self.assertTrue(any(p.name == "report.md" for p in paths))
                    for path in paths:
                        data = path.read_bytes()
                        self.assertNotIn(KEY.encode(), data, path.name)
                        self.assertNotIn(OVERRIDE_KEY.encode(), data, path.name)
                    self.assertNotIn(KEY, json.dumps(retry_result.to_dict()))
                    self.assertNotIn(OVERRIDE_KEY, json.dumps(_snapshot_payload(retry_result)))
                self.assertEqual(seen, [
                    ("/custom/v1/chat/completions", f"Bearer {KEY}", "桌面模型"),
                    ("/custom/v1/chat/completions", f"Bearer {OVERRIDE_KEY}", "env-model"),
                ])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
