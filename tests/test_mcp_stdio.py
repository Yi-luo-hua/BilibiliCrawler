"""Real CLI subprocesses and SDK stdio, with only external services replaced."""
import asyncio
import hashlib
import json
import os
import tempfile
import threading
import unittest
from contextlib import ExitStack, asynccontextmanager, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

try:
    import anyio
    from mcp import Client, StdioServerParameters
    from mcp.client.stdio import stdio_client
    from mcp.types import jsonrpc_message_adapter
    import mcp.client.stdio as sdk_stdio
except ImportError as exc:
    raise unittest.SkipTest("MCP SDK not installed; stdio tests skipped") from exc

import sys

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "mcp_stdio"
KEY = "sk-stdio-profile-canary-777888"
OVERRIDE_KEY = "sk-stdio-env-canary-999111"
SUMMARY = "中文舆情总结：大家关注内容质量"


@contextmanager
def local_provider():
    calls, releases = [], []
    entered = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append({"path": self.path, "key": self.headers.get("Authorization"), "model": data["model"]})
            if data["model"] == "slow-model":
                release = threading.Event()
                releases.append(release)
                entered.set()
                release.wait(10)
            if data["model"] == "bad-model":
                status, response = 401, {"error": {"message": f"{KEY} {OVERRIDE_KEY} private-error-body"}}
            else:
                # Echo the credential actually sent, including env overrides.
                echo = self.headers.get("Authorization", "").removeprefix("Bearer ")
                status, response = 200, {"choices": [{"message": {"content": json.dumps(
                    {"summary": f"{SUMMARY} {echo}", "insights": ["中文观点"]}, ensure_ascii=False,
                )}}]}
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/profile/v1", calls, entered, releases
    finally:
        for release in releases:
            release.set()
        server.shutdown()
        server.server_close()
        thread.join(3)


class StdioTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="mcp-中文-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.runs = self.root / "中文运行目录"
        self.profile = self.root / "桌面配置"
        self.profile.mkdir()
        self.keyfile = self.profile / "credentials.json"
        self.keyfile.write_text(json.dumps({"api_key": KEY}), encoding="utf-8")
        self.transcripts = []

    def configure_profile(self, url, model="桌面模型"):
        (self.profile / "ui.json").write_text(json.dumps({"llm_base_url": url, "llm_model": model}, ensure_ascii=False), encoding="utf-8")

    @asynccontextmanager
    async def child(self, overrides=None, mode="legacy", fixture=True):
        env = {
            "BILIBILI_AGENT_RUNS_DIR": str(self.runs), "BILIBILI_AGENT_CREDENTIALS": str(self.keyfile),
            "BILIBILI_TEST_MCP_STDIO": "1" if fixture else "0",
            "PYTHONPATH": os.pathsep.join([str(FIXTURE), str(ROOT)]) if fixture else str(ROOT),
            "PYTHONIOENCODING": "gbk", "PYTHONUTF8": "0", "PYTHONDONTWRITEBYTECODE": "1",
            **(overrides or {}),
        }
        params = StdioServerParameters(command=sys.executable, args=["-m", "backend.agent", "mcp"], cwd=ROOT, env=env)
        chunks, processes = [], []
        real_spawn = sdk_stdio._create_platform_compatible_process

        async def spawn(**kwargs):
            process = await real_spawn(**kwargs)
            processes.append(process)
            real_receive = process.stdout.receive

            async def receive(*args, **kwargs):
                chunk = await real_receive(*args, **kwargs)
                chunks.append(chunk)
                return chunk

            # Keep the real Process identity (Windows SDK job tracking), but
            # capture bytes before decoding, including EOF tails and drain.
            streams.enter_context(patch.object(process.stdout, "receive", side_effect=receive))
            return process

        with tempfile.TemporaryFile(mode="w+", encoding="utf-8") as stderr, ExitStack() as streams, \
                patch.object(sdk_stdio, "_create_platform_compatible_process", side_effect=spawn):
            try:
                async with Client(stdio_client(params, errlog=stderr), mode=mode, read_timeout_seconds=15) as client:
                    self.assertTrue(client.session.protocol_version)
                    yield client
            finally:
                stderr.seek(0)
                text = stderr.read()
                raw = b"".join(chunks)
                stdout = raw.decode("utf-8", errors="strict")
                lines = stdout.splitlines()
                self.transcripts.append((list(lines), text))
                self.assertEqual(len(processes), 1)
                self.assertEqual(processes[0].returncode, 0, "stdio child must exit cleanly when client closes")
                for secret in (KEY, OVERRIDE_KEY):
                    self.assertFalse(secret in stdout + text, "credential canary in subprocess output")
                self.assertTrue(raw.endswith(b"\n"), "unterminated stdout protocol frame")
                for line in lines:
                    try:
                        jsonrpc_message_adapter.validate_json(line, by_name=False)
                    except ValueError:
                        self.fail("invalid JSON-RPC stdout frame")
                self.assertIn("starting bilibili-crawler MCP server on stdio", text)

    async def call(self, client, name, arguments=None, **kwargs):
        result = await client.call_tool(name, arguments or {}, **kwargs)
        self.assertFalse(result.is_error, result.content)
        return result.structured_content

    async def wait_done(self, client, task_id):
        with anyio.fail_after(5):
            while True:
                status = await self.call(client, "get_task_status", {"task_id": task_id})
                if status["done"]:
                    return status
                await asyncio.sleep(0.05)

    async def test_real_entrypoint_handshakes_and_discovers_tools_without_fixture(self):
        for mode in ("legacy", "auto"):
            async with self.child(mode=mode, fixture=False) as client:
                names = {tool.name for tool in (await client.list_tools()).tools}
                self.assertEqual(names, {"crawl_comments", "crawl_and_analyze", "analyze_run", "get_task_status",
                                         "stop_task", "list_runs", "delete_run"})
        self.assertFalse(self.runs.exists())

    async def test_stdout_audit_rejects_shutdown_tails_including_secret_without_newline(self):
        poison = self.root / "exit-fixture"
        poison.mkdir()
        for tail, reason in (
            (b"not-a-frame", "unterminated stdout"),
            (KEY.encode(), "credential canary"),
            (b'{"jsonrpc":"2.0","log":"noise"}\n', "invalid JSON-RPC"),
        ):
            with self.subTest(reason=reason):
                (poison / "sitecustomize.py").write_text(
                    "import atexit, os, runpy\n"
                    f"runpy.run_path({str(FIXTURE / 'sitecustomize.py')!r})\n"
                    f"atexit.register(lambda: os.write(1, {tail!r}))\n", encoding="utf-8",
                )
                with self.assertRaisesRegex(AssertionError, reason):
                    async with self.child({"PYTHONPATH": os.pathsep.join([str(poison), str(ROOT)])}) as client:
                        self.assertEqual(len((await client.list_tools()).tools), 7)
                self.assertEqual(self.transcripts[-1][0][-1], tail.decode().rstrip("\n"))

    async def test_profile_unicode_restart_and_environment_override_over_real_stdio(self):
        progress = []
        async def on_progress(value, total, message):
            progress.append(message)

        with local_provider() as (url, calls, _, _):
            self.configure_profile(url)
            profile_bytes = {path.name: path.read_bytes() for path in self.profile.iterdir()}
            async with self.child() as client:
                first = await self.call(client, "crawl_and_analyze", {"url": "BV1xx411c7mD", "max_pages": 1}, progress_callback=on_progress)
                self.assertEqual(first["status"], "completed")
                self.assertIn(SUMMARY, first["summary"])
                comments = Path(first["artifacts"]["comments_json"])
                digest = hashlib.sha256(comments.read_bytes()).hexdigest()
                listing = await self.call(client, "list_runs")
                self.assertEqual(listing["result"][0]["run_id"], first["run_id"])
            self.assertTrue(progress)
            self.assertTrue(any("中文" in str(message) or "分析" in str(message) for message in progress))
            async with self.child({"BILIBILI_LLM_MODEL": "env-model", "BILIBILI_LLM_API_KEY": OVERRIDE_KEY}) as client:
                recovered = await self.call(client, "get_task_status", {"run_id": first["run_id"]})
                self.assertEqual(recovered["status"], "completed")
                self.assertEqual(recovered["artifacts"], first["artifacts"])
                second = await self.call(client, "analyze_run", {"run_id": first["run_id"]})
                self.assertEqual(second["status"], "completed")
                self.assertEqual(hashlib.sha256(comments.read_bytes()).hexdigest(), digest)
                self.assertIn("中文", Path(second["artifacts"]["report_markdown"]).read_text(encoding="utf-8"))
                for path in self.runs.rglob("*"):
                    if path.is_file():
                        for secret in (KEY, OVERRIDE_KEY):
                            self.assertNotIn(secret.encode(), path.read_bytes())
                removed = await self.call(client, "delete_run", {"run_id": first["run_id"]})
                self.assertEqual(removed["deleted"], [first["run_id"]])
                self.assertFalse(comments.exists())
            self.assertEqual(calls, [
                {"path": "/profile/v1/chat/completions", "key": f"Bearer {KEY}", "model": "桌面模型"},
                {"path": "/profile/v1/chat/completions", "key": f"Bearer {OVERRIDE_KEY}", "model": "env-model"},
            ])
            self.assertEqual({path.name: path.read_bytes() for path in self.profile.iterdir()}, profile_bytes)
            self.assertIn("成功导出", "\n".join(stderr for _, stderr in self.transcripts))

    async def test_provider_failure_cancellation_and_recovery_do_not_replace_old_report(self):
        with local_provider() as (url, calls, entered, releases):
            self.configure_profile(url)
            async with self.child() as client:
                crawled = await self.call(client, "crawl_comments", {"url": "BV1xx411c7mD"})
                first = await self.call(client, "analyze_run", {"run_id": crawled["run_id"]})
            async with self.child({"BILIBILI_LLM_MODEL": "bad-model"}) as client:
                failed = await self.call(client, "analyze_run", {"run_id": first["run_id"]})
                self.assertEqual(failed["error_code"], "LLM_AUTH")
                self.assertIn(f'analyze_run(run_id="{first["run_id"]}")', failed["next_step"])
                self.assertNotIn("private-error-body", json.dumps(failed))
            received = self.root / "late-http-completion.txt"
            async with self.child({"BILIBILI_LLM_MODEL": "slow-model",
                                   "BILIBILI_TEST_HTTP_COMPLETION_MARKER": str(received)}) as client:
                running = await self.call(client, "analyze_run", {"run_id": first["run_id"], "wait_seconds": 0})
                self.assertFalse(running["done"])
                self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                with anyio.fail_after(2):
                    status = await self.call(client, "get_task_status", {"task_id": running["task_id"]})
                    self.assertFalse(status["done"])
                    self.assertTrue(any("\u4e00" <= character <= "\u9fff" for character in status["stage"]))
                    await self.call(client, "stop_task", {"task_id": running["task_id"]})
                    cancelled = await self.wait_done(client, running["task_id"])
                self.assertEqual(cancelled["status"], "cancelled")
                self.assertFalse(received.exists(), "response must remain blocked until after cancellation")
                for release in releases:
                    release.set()
                with anyio.fail_after(5):
                    while not received.exists():
                        await asyncio.sleep(0.02)
                self.assertEqual(received.read_text(encoding="utf-8"), "response-received-and-worker-finished")
                after_response = await self.call(client, "get_task_status", {"task_id": running["task_id"]})
                self.assertEqual(after_response, cancelled)
                aggregate = await self.call(client, "get_task_status", {"run_id": first["run_id"]})
                self.assertEqual(aggregate["status"], "completed")
                self.assertEqual(aggregate["artifacts"], first["artifacts"])
            async with self.child() as client:
                recovered = await self.call(client, "get_task_status", {"run_id": first["run_id"]})
                self.assertEqual(recovered["status"], "completed")
                self.assertEqual(recovered["artifacts"], first["artifacts"])
                retried = await self.call(client, "analyze_run", {"run_id": first["run_id"]})
                self.assertEqual(retried["status"], "completed")
            self.assertEqual([call["model"] for call in calls], ["桌面模型", "bad-model", "slow-model", "桌面模型"])
            self.assertTrue(all(call["key"] == f"Bearer {KEY}" and call["path"] == "/profile/v1/chat/completions" for call in calls))
