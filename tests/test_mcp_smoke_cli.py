"""The optional live command must stay inert until explicitly requested."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SmokeCommandTests(unittest.TestCase):
    def test_default_invocation_is_inert_even_with_live_environment_values(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory) / "must-not-exist"
            env = {**os.environ, "BILIBILI_AGENT_RUNS_DIR": str(run_root),
                   "BILIBILI_AGENT_CREDENTIALS": str(Path(directory) / "missing.json"),
                   "BILIBILI_LLM_API_KEY": "sk-live-smoke-canary-123456",
                   "BILIBILI_MCP_SMOKE_URL": "BV1xx411c7mD", "BILIBILI_MCP_SMOKE_MAX_PAGES": "1",
                   "BILIBILI_MCP_SMOKE_SAMPLE_SIZE": "20"}
            child = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "smoke_mcp_stdio.py")],
                                   env=env, capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 0, child.stderr)
            self.assertTrue(json.loads(child.stdout)["skipped"])
            self.assertFalse(run_root.exists())
            self.assertNotIn(b"sk-live-smoke-canary", child.stdout + child.stderr)

    def test_invalid_live_settings_fail_before_starting_a_server(self):
        with tempfile.TemporaryDirectory() as directory:
            run_root = Path(directory) / "must-not-exist"
            env = {**os.environ, "BILIBILI_AGENT_RUNS_DIR": str(run_root),
                   "BILIBILI_MCP_SMOKE_URL": "BV1xx411c7mD", "BILIBILI_MCP_SMOKE_MAX_PAGES": "0",
                   "BILIBILI_MCP_SMOKE_SAMPLE_SIZE": "20"}
            child = subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "scripts" / "smoke_mcp_stdio.py"), "--live"],
                                   env=env, capture_output=True, timeout=10)
            self.assertEqual(child.returncode, 1, child.stderr)
            self.assertEqual(json.loads(child.stdout)["error_code"], "INVALID_SMOKE_CONFIG")
            self.assertFalse(run_root.exists())
