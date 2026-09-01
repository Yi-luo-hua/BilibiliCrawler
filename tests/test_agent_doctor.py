"""Real CLI + local HTTP tests, isolated from installed credentials/network."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.service.diagnostics import diagnose, inspect_runs_directory


KEY = "sk-doctor-canary-123456789"
ROOT = Path(__file__).resolve().parents[1]


class DoctorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.profile = self.root / "credentials.json"
        self.profile.write_text(json.dumps({"api_key": KEY}), encoding="utf-8")
        self.ui = self.root / "ui.json"
        self.ui.write_text(json.dumps({"llm_base_url": "https://provider.invalid/v1", "llm_model": "中文模型"}), encoding="utf-8")
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("BILIBILI_")}
        self.env.update({
            "BILIBILI_AGENT_CREDENTIALS": str(self.profile),
            "BILIBILI_AGENT_RUNS_DIR": str(self.root / "runs"),
            "PYTHONDONTWRITEBYTECODE": "1",
        })

    def cli(self, *args):
        return subprocess.run(
            [sys.executable, "-m", "backend.agent", "doctor", *args],
            cwd=ROOT, env=self.env, capture_output=True, timeout=20,
        )

    def test_real_cli_reports_profile_and_never_creates_runs_or_edits_config(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(payload["profile"]["model"], "中文模型")
        self.assertEqual(payload["profile"]["base_url"], "https://provider.invalid/v1")
        self.assertEqual(payload["profile"]["credential_source"], "explicit_file")
        self.assertEqual(payload["profile"]["field_sources"]["model"], "ui_file")
        self.assertEqual(payload["provider"], {"checked": False})
        self.assertEqual(payload["runs"]["check"], "permissions_only")
        self.assertIn("version", payload["mcp"])
        self.assertNotIn(KEY.encode(), result.stdout + result.stderr)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_default_diagnostic_does_not_call_provider_or_runstore(self):
        with patch.dict(os.environ, self.env, clear=True), \
             patch("src.service.diagnostics._check_provider", side_effect=AssertionError("network")), \
             patch("src.service.paths.agent_runs_root", side_effect=AssertionError("write")):
            self.assertTrue(diagnose()["ok"])

    def test_config_error_is_json_and_never_echoes_raw_secret(self):
        self.ui.write_text('{"secret":"' + KEY, encoding="utf-8")
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertEqual(payload["profile"]["error_code"], "CONFIG_INVALID")
        self.assertNotIn(KEY.encode(), result.stdout + result.stderr)
        self.assertNotIn(b"Traceback", result.stderr)

    def test_unencodable_key_returns_safe_json_before_provider_request(self):
        key = "中文错误密钥测试"
        self.profile.write_text(json.dumps({"api_key": key}), encoding="utf-8")
        self.ui.write_text(json.dumps({"llm_base_url": "http://127.0.0.1:1/v1", "llm_model": "model"}), encoding="utf-8")
        result = self.cli("--check-provider")
        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["profile"]["error_code"], "CONFIG_INVALID")
        self.assertNotIn(key, str(payload))
        self.assertNotIn(b"Traceback", result.stderr)

    def test_short_key_in_model_is_masked_without_changing_json_schema(self):
        self.profile.write_text(json.dumps({"api_key": "ok"}), encoding="utf-8")
        self.ui.write_text(json.dumps({"llm_model": "model-ok"}), encoding="utf-8")
        result = self.cli()
        payload = json.loads(result.stdout.decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["profile"]["model"], "model-***")

    def test_non_directory_run_override_is_reported_without_mutation(self):
        self.env["BILIBILI_AGENT_RUNS_DIR"] = str(self.profile)
        result = self.cli()
        self.assertEqual(result.returncode, 1)
        self.assertFalse(json.loads(result.stdout)["runs"]["writable_hint"])

    def test_read_only_directory_selection_falls_back_without_writing(self):
        blocked = self.root / "blocked"
        blocked.write_text("not a directory", encoding="utf-8")
        fallback = self.root / "fallback"
        with patch.dict(os.environ, {}, clear=True), \
             patch("src.service.diagnostics.candidate_bases", return_value=[blocked, fallback]):
            result = inspect_runs_directory()
        self.assertEqual(result["path"], str(fallback / "analysis-runs"))
        self.assertTrue(result["writable_hint"])
        self.assertFalse(fallback.exists())

    def test_invalid_timeout_does_not_send_a_request(self):
        for value in ("0", "-1", "61", "nan", "inf"):
            with self.subTest(value=value):
                result = self.cli("--check-provider", "--timeout", value)
                self.assertEqual(result.returncode, 1)
                self.assertEqual(json.loads(result.stdout)["error_code"], "INVALID_INPUT")

    def test_opt_in_models_probe_uses_selected_endpoint_and_never_echoes_body(self):
        seen = []
        response_status = [200]

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path, self.headers.get("Authorization")))
                self.send_response(response_status[0])
                self.send_header("Location", "/redirect-should-never-be-followed")
                self.end_headers()
                self.wfile.write(KEY.encode())

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            self.ui.write_text(json.dumps({
                "llm_base_url": f"http://127.0.0.1:{server.server_port}/v1", "llm_model": "local-model",
            }), encoding="utf-8")
            for status, expected in ((200, None), (401, "PROVIDER_AUTH"), (302, "PROVIDER_REDIRECT"), (404, "PROVIDER_HTTP")):
                with self.subTest(status=status):
                    response_status[0] = status
                    result = self.cli("--check-provider", "--timeout", "2")
                    payload = json.loads(result.stdout)
                    self.assertEqual(payload["provider"].get("error_code"), expected)
                    self.assertEqual(result.returncode, 0 if status == 200 else 1)
                    self.assertNotIn(KEY.encode(), result.stdout + result.stderr)
            self.assertEqual(seen, [("/v1/models", f"Bearer {KEY}")] * 4)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
