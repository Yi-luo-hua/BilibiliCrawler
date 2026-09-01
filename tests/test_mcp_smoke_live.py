"""Exercise opt-in smoke failure paths without external services or credentials."""
import contextlib
import importlib.util
import io
import json
import logging
import os
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import mcp
    from mcp.client.stdio import get_default_environment
except ImportError as exc:
    raise unittest.SkipTest("MCP SDK not installed; smoke transport tests skipped") from exc

ROOT = Path(__file__).resolve().parents[1]
CANARY = "sk-smoke-transport-canary-444555"


class SmokeLiveFailureTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("smoke", ROOT / "scripts" / "smoke_mcp_stdio.py")
        self.smoke = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.smoke)
        env = get_default_environment() | {
            "BILIBILI_MCP_SMOKE_URL": "BV1xx411c7mD", "BILIBILI_MCP_SMOKE_MAX_PAGES": "1",
            "BILIBILI_MCP_SMOKE_SAMPLE_SIZE": "20", "BILIBILI_MCP_SMOKE_WAIT_SECONDS": "1",
        }
        environment = patch.dict(os.environ, env, clear=True)
        environment.start()
        self.addCleanup(environment.stop)

    def test_real_stdio_parser_error_cannot_echo_key_through_parent_sdk_logger(self):
        real_params = mcp.StdioServerParameters

        def params(**kwargs):
            # This child only prints a known canary. It never starts the real
            # service, reads a profile, or opens a network connection.
            return real_params(command=sys.executable,
                               args=["-c", f"print({CANARY!r}, flush=True)"],
                               env={"PYTHONIOENCODING": "utf-8"})

        stdout, stderr = io.StringIO(), io.StringIO()
        logger = logging.getLogger("mcp")
        previous_level, previous_propagate = logger.level, logger.propagate
        previous_disable = logging.root.manager.disable
        handler = logging.StreamHandler(stderr)
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logging.disable(logging.NOTSET)
        try:
            with patch.object(mcp, "StdioServerParameters", side_effect=params), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = self.smoke.main(["--live"])
            self.assertEqual(logging.root.manager.disable, logging.NOTSET)
        finally:
            logger.removeHandler(handler)
            logger.setLevel(previous_level)
            logger.propagate = previous_propagate
            logging.disable(previous_disable)
            handler.close()
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout.getvalue())["error_code"], "SMOKE_FAILED")
        self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("Traceback", stderr.getvalue())

    def test_success_and_transport_failures_preserve_metadata_and_close_client(self):
        for failure in (None, "stop_task", "get_task_status", "close"):
            with self.subTest(failure=failure):
                calls, closed = [], []
                payload = {"done": False, "status": "analyzing", "task_id": "task-smoke-review",
                           "run_id": "known-existing-run", "counts": {"comments": 20},
                           "artifacts": {"comments_json": "not-for-the-report"},
                           "summary": CANARY, "error": CANARY}
                if failure is None:
                    payload.update(done=True, status="completed")

                class Client:
                    def __init__(self, *args, **kwargs):
                        pass

                    async def __aenter__(self):
                        return self

                    async def __aexit__(self, *args):
                        closed.append(True)
                        if failure == "close":
                            raise TimeoutError(CANARY)

                    async def list_tools(self):
                        return SimpleNamespace(tools=[SimpleNamespace(name="crawl_and_analyze")])

                    async def call_tool(self, name, arguments):
                        calls.append(name)
                        if name == failure:
                            raise TimeoutError(CANARY)
                        if name == "stop_task":
                            return SimpleNamespace(is_error=False, structured_content={**payload, "status": "cancelling"})
                        if name == "get_task_status":
                            return SimpleNamespace(is_error=False, structured_content={**payload, "done": True, "status": "cancelled"})
                        return SimpleNamespace(is_error=False, structured_content=payload)

                stdout, stderr = io.StringIO(), io.StringIO()
                with patch.object(mcp, "Client", Client), \
                        patch("mcp.client.stdio.stdio_client", return_value=object()), \
                        contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                    code = self.smoke.main(["--live"])
                report = json.loads(stdout.getvalue())
                self.assertEqual(code, 0 if failure is None else 1)
                self.assertEqual(report["ok"], failure is None)
                self.assertEqual(report.get("error_code"), None if failure is None else "SMOKE_FAILED")
                self.assertEqual(report["run_id"], payload["run_id"])
                self.assertEqual(report["task_id"], payload["task_id"])
                self.assertEqual(report["counts"], payload["counts"])
                self.assertEqual(report["artifact_names"], ["comments_json"])
                expected_status = {None: "completed", "stop_task": "analyzing", "get_task_status": "cancelling", "close": "cancelled"}
                self.assertEqual(report["status"], expected_status[failure])
                self.assertEqual(report["wait_window_exceeded"], failure is not None)
                self.assertEqual(closed, [True])
                self.assertEqual(calls.count("crawl_and_analyze"), 1)
                if failure is None:
                    self.assertEqual(calls, ["crawl_and_analyze"])
                self.assertNotIn(CANARY, stdout.getvalue() + stderr.getvalue())
                self.assertNotIn("not-for-the-report", stdout.getvalue())
