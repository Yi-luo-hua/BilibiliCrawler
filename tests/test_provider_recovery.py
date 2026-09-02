"""Provider failures must be actionable without replaying permanent errors."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from src.processor.analysis_processor import AnalysisCancelled, AnalysisError, LLMAnalysisProcessor
from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.run_store import RunStore, new_run_id


KEY = "sk-provider-recovery-canary-987654"
BODY_MARKER = "untrusted-provider-body-must-not-escape"
SUCCESS = {"choices": [{"message": {"content": '{"summary":"recovered"}'}}]}


@contextmanager
def provider(responses):
    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            calls.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            status, body, headers = responses[min(len(calls) - 1, len(responses) - 1)]
            encoded = body if isinstance(body, bytes) else json.dumps(body).encode()
            self.send_response(status)
            for key, value in headers.items():
                self.send_header(key, value)
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", calls
    finally:
        server.shutdown()
        server.server_close()
        worker.join(2)


def error_body(code="", param=None):
    return {"error": {"code": code, "param": param, "message": f"{KEY} {BODY_MARKER}"}}


class ProviderTests(unittest.TestCase):
    def call(self, base_url, cancel=None):
        return LLMAnalysisProcessor._call_llm(
            base_url, KEY, "test-model", [{"id": 1, "type": "comment", "content": "评论",
                                          "likes": 0, "replies": 0, "time_text": ""}],
            "comments", "sample", ["topic_ranking"],
            cancel_event=cancel,
        )

    def test_permanent_http_errors_do_not_retry_or_echo_provider_text(self):
        cases = [(401, "", None, "LLM_AUTH"), (403, "model_not_found", "model", "LLM_AUTH"),
                 (404, "", None, "LLM_ENDPOINT"), (404, "model_not_found", None, "LLM_MODEL"),
                 (400, "invalid_value", "model", "LLM_MODEL"), (422, "", None, "LLM_REQUEST_INVALID"),
                 (400, "", None, "LLM_REQUEST_INVALID"), (429, "insufficient_quota", None, "LLM_RATE_LIMIT")]
        for status, code, param, expected in cases:
            with self.subTest(status=status, code=code), provider([(status, error_body(code, param), {})]) as (url, calls):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(url)
                self.assertEqual(len(calls), 1)
                self.assertEqual(getattr(raised.exception, "code", None), expected)
                self.assertNotIn(KEY, str(raised.exception))
                self.assertNotIn(BODY_MARKER, str(raised.exception))

    def test_only_explicit_response_format_rejection_allows_compatibility_retry(self):
        with provider([(400, error_body("unsupported_parameter", "response_format"), {}),
                       (200, SUCCESS, {})]) as (url, calls):
            self.assertEqual(self.call(url)["summary"], "recovered")
            self.assertEqual(len(calls), 2)
            self.assertIn("response_format", calls[0])
            self.assertNotIn("response_format", calls[1])

    def test_other_parameter_error_does_not_trigger_format_fallback(self):
        for param in ("top_p", None):
            body = {"error": {"param": param, "code": "unsupported_parameter",
                              "message": "temperature is not supported; response_format is supported"}}
            with self.subTest(param=param), provider([(400, body, {})]) as (url, calls):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(url)
                self.assertEqual(raised.exception.code, "LLM_REQUEST_INVALID")
                self.assertEqual(len(calls), 1)
        with provider([(400, {"error": {"message": "'response_format' is not supported"}}, {}),
                       (200, SUCCESS, {})]) as (url, calls):
            self.assertEqual(self.call(url)["summary"], "recovered")
            self.assertEqual(len(calls), 2)

    def test_only_structured_temperature_rejection_drops_that_field_once(self):
        with provider([(400, error_body("unsupported_parameter", "temperature"), {}),
                       (200, SUCCESS, {})]) as (url, calls):
            self.assertEqual(self.call(url)["summary"], "recovered")
            self.assertEqual(len(calls), 2)
            self.assertIn("temperature", calls[0])
            self.assertNotIn("temperature", calls[1])
            # Only the rejected field is dropped; the rest of the payload stands.
            self.assertIn("response_format", calls[1])
            self.assertEqual({k: v for k, v in calls[0].items() if k != "temperature"}, calls[1])

    def test_unstructured_or_unrelated_temperature_errors_fail_closed(self):
        bodies = [
            # Free text alone never establishes which field the provider rejected.
            {"error": {"message": "temperature is not supported"}},
            {"error": {"code": "unsupported_parameter",
                       "message": "temperature is not supported"}},
            # A structured rejection naming another field must not drop temperature.
            {"error": {"code": "unsupported_parameter", "param": "top_p",
                       "message": f"{KEY} {BODY_MARKER}"}},
            # Temperature named without an unsupported-parameter code stays ambiguous.
            {"error": {"code": "invalid_request_error", "param": "temperature",
                       "message": f"{KEY} {BODY_MARKER}"}},
            {"error": {}},
        ]
        for body in bodies:
            with self.subTest(body=json.dumps(body)), provider([(400, body, {})]) as (url, calls):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(url)
                self.assertEqual(raised.exception.code, "LLM_REQUEST_INVALID")
                self.assertEqual(len(calls), 1)
                self.assertNotIn(KEY, str(raised.exception))
                self.assertNotIn(BODY_MARKER, str(raised.exception))

    def test_request_invalid_surfaces_only_sanitized_code_and_param(self):
        with provider([(400, error_body("unsupported_parameter", "top_p"), {})]) as (url, _):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            message = str(raised.exception)
            self.assertIn("unsupported_parameter", message)
            self.assertIn("top_p", message)
            self.assertNotIn(KEY, message)
            self.assertNotIn(BODY_MARKER, message)

    def test_unsafe_code_and_param_are_omitted_rather_than_reflected(self):
        unsafe = [f"sk-leak {KEY}", BODY_MARKER + " with spaces", "x" * 80,
                  "值不安全", "<script>", 12345, {"nested": "object"}]
        for value in unsafe:
            body = {"error": {"code": value, "param": value, "message": f"{KEY} {BODY_MARKER}"}}
            with self.subTest(value=repr(value)), provider([(400, body, {})]) as (url, calls):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(url)
                message = str(raised.exception)
                self.assertEqual(raised.exception.code, "LLM_REQUEST_INVALID")
                self.assertEqual(len(calls), 1)
                self.assertNotIn(KEY, message)
                self.assertNotIn(BODY_MARKER, message)
                self.assertNotIn("script", message)
                self.assertNotIn("不安全", message)

    def test_missing_code_and_param_leave_the_message_unadorned(self):
        with provider([(400, {"error": {"message": f"{KEY} {BODY_MARKER}"}}, {})]) as (url, _):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            message = str(raised.exception)
            self.assertNotIn("code=", message)
            self.assertNotIn("param=", message)
            self.assertNotIn(KEY, message)

    def test_both_compatibility_drops_share_the_single_request_budget(self):
        with provider([(400, error_body("unsupported_parameter", "response_format"), {}),
                       (400, error_body("unsupported_parameter", "temperature"), {}),
                       (200, SUCCESS, {})]) as (url, calls):
            self.assertEqual(self.call(url)["summary"], "recovered")
            self.assertEqual(len(calls), 3)
            self.assertNotIn("response_format", calls[2])
            self.assertNotIn("temperature", calls[2])
        with provider([(503, error_body(), {"Retry-After": "0"}),
                       (400, error_body("unsupported_parameter", "temperature"), {}),
                       (503, error_body(), {"Retry-After": "0"})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(len(calls), 3)
            self.assertEqual(raised.exception.code, "LLM_UNAVAILABLE")

    def test_repeated_temperature_rejection_is_not_replayed_without_progress(self):
        # The field is gone after the first drop, so a second identical rejection
        # must end the attempt instead of looping on an unchanged payload.
        with provider([(400, error_body("unsupported_parameter", "temperature"), {})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(len(calls), 2)
            self.assertEqual(raised.exception.code, "LLM_REQUEST_INVALID")
            self.assertNotIn("temperature", calls[1])

    def test_transient_response_recovers_with_bounded_retries(self):
        for status in (429, 500, 502, 503, 504):
            with self.subTest(status=status), provider([(status, error_body(), {"Retry-After": "0"}),
                                                       (200, SUCCESS, {})]) as (url, calls):
                self.assertEqual(self.call(url)["summary"], "recovered")
                self.assertEqual(len(calls), 2)
                self.assertEqual(calls[0], calls[1])

    def test_retry_budget_is_shared_with_format_fallback(self):
        with provider([(503, error_body(), {"Retry-After": "0"}),
                       (400, error_body("unsupported_parameter", "response_format"), {}),
                       (503, error_body(), {"Retry-After": "0"})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(len(calls), 3)
            self.assertEqual(getattr(raised.exception, "code", None), "LLM_UNAVAILABLE")

    def test_long_retry_after_does_not_trigger_an_early_request(self):
        with provider([(429, error_body(), {"Retry-After": "120"})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(len(calls), 1)
            self.assertEqual(getattr(raised.exception, "code", None), "LLM_RATE_LIMIT")

    def test_retry_after_http_date_and_budget_exhaustion(self):
        future = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=2), usegmt=True)
        with provider([(503, {}, {"Retry-After": future})]) as (url, calls):
            with self.assertRaises(AnalysisError):
                self.call(url)
            self.assertEqual(len(calls), 1)
        with provider([(503, {}, {"Retry-After": "0"})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(raised.exception.code, "LLM_UNAVAILABLE")
            self.assertEqual(len(calls), 3)

    def test_provider_redirect_is_not_followed(self):
        with provider([(302, {}, {"Location": "/capture-secret"})]) as (url, calls):
            with self.assertRaises(AnalysisError) as raised:
                self.call(url)
            self.assertEqual(raised.exception.code, "LLM_ENDPOINT")
            self.assertEqual(len(calls), 1)

    def test_response_and_content_parse_errors_have_safe_classification(self):
        bodies = [b"bad-json " + KEY.encode(), {}, {"choices": []},
                  {"choices": [{"message": {"content": '{bad:"' + KEY + '"}'}}]}]
        for body in bodies:
            with self.subTest(body=type(body).__name__), provider([(200, body, {})]) as (url, calls):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(url)
                self.assertEqual(getattr(raised.exception, "code", None), "LLM_RESPONSE_INVALID")
                self.assertNotIn(KEY, str(raised.exception))
                self.assertEqual(len(calls), 1)

    def test_transport_failures_are_distinct_and_ambiguous_sends_are_not_replayed(self):
        cases = [(requests.exceptions.SSLError, "LLM_TLS", 1),
                 (requests.exceptions.ConnectTimeout, "LLM_TIMEOUT", 3),
                 (requests.exceptions.ReadTimeout, "LLM_TIMEOUT", 1),
                 (requests.exceptions.ConnectionError, "LLM_NETWORK", 1)]
        for error, code, count in cases:
            with self.subTest(error=error.__name__), patch("requests.Session.post", side_effect=error(KEY)) as post:
                with self.assertRaises(AnalysisError) as raised:
                    self.call("https://example.invalid/v1")
                self.assertEqual(getattr(raised.exception, "code", None), code)
                self.assertEqual(post.call_count, count)
                self.assertNotIn(KEY, str(raised.exception))

    def test_real_response_body_timeout_is_classified_without_replay(self):
        release = threading.Event()
        calls = []

        class SlowBody(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers["Content-Length"]))
                calls.append(1)
                self.send_response(200)
                self.send_header("Content-Length", "100")
                self.end_headers()
                self.wfile.flush()
                release.wait(3)

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowBody)
        worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
        worker.start()
        real_post = requests.Session.post

        def quick_post(session, *args, **kwargs):
            kwargs["timeout"] = 0.1
            return real_post(session, *args, **kwargs)

        try:
            with patch.object(requests.Session, "post", quick_post):
                with self.assertRaises(AnalysisError) as raised:
                    self.call(f"http://127.0.0.1:{server.server_port}/v1")
                self.assertEqual(raised.exception.code, "LLM_TIMEOUT")
                self.assertEqual(len(calls), 1)
        finally:
            release.set()
            server.shutdown()
            server.server_close()
            worker.join(2)

    def test_cancel_during_retry_wait_prevents_followup_request(self):
        cancel = threading.Event()
        response = requests.Response()
        response.status_code = 429
        response._content = b'{}'
        response._content_consumed = True
        response.headers["Retry-After"] = "1"
        sent = threading.Event()

        def post(*args, **kwargs):
            sent.set()
            return response

        errors = []
        def work():
            try:
                self.call("https://example.invalid/v1", cancel)
            except Exception as exc:
                errors.append(exc)

        with patch("requests.Session.post", side_effect=post) as mocked:
            thread = threading.Thread(target=work)
            thread.start()
            self.assertTrue(sent.wait(2))
            cancel.set()
            thread.join(0.5)
            self.assertFalse(thread.is_alive())
            self.assertIsInstance(errors[0], AnalysisCancelled)
            self.assertEqual(mocked.call_count, 1)

    def test_late_retryable_response_after_cancel_never_sends_again(self):
        cancel, sent, release, finished = (threading.Event() for _ in range(4))
        calls, errors = [], []
        returned = threading.Event()

        class Session:
            def post(self, *args, **kwargs):
                calls.append(1)
                sent.set()
                release.wait(3)
                response = requests.Response()
                response.status_code = 503
                response._content, response._content_consumed = b'{}', True
                response.headers["Retry-After"] = "0"
                returned.set()
                return response

            def close(self):
                if returned.is_set():
                    finished.set()

        def work():
            try:
                self.call("https://example.invalid/v1", cancel)
            except Exception as exc:
                errors.append(exc)

        with patch("requests.Session", return_value=Session()):
            thread = threading.Thread(target=work)
            thread.start()
            try:
                self.assertTrue(sent.wait(2))
                cancel.set()
                thread.join(0.5)
                self.assertFalse(thread.is_alive())
                self.assertIsInstance(errors[0], AnalysisCancelled)
            finally:
                release.set()
                thread.join(3)
                self.assertTrue(finished.wait(2))
            self.assertEqual(len(calls), 1)

    def test_summary_failure_preserves_paid_batches_with_persistent_warning(self):
        class Crawler:
            def crawl_comments(self, *args, **kwargs):
                return [{"comment_id": i, "content": f"评论{i}", "username": "测试"} for i in range(21)]

        with tempfile.TemporaryDirectory() as directory, provider([
            (200, SUCCESS, {}), (200, SUCCESS, {}), (401, error_body(), {}),
        ]) as (url, calls):
            store = RunStore(Path(directory))
            service = AgentService(store=store, api=object(), crawler_factory=lambda progress: Crawler(),
                                   credentials_resolver=lambda: LLMCredentials(KEY, url, "test-model"))
            task = service.start_crawl_and_analyze("BV1xx411c7mD", batch_size=20)
            result = service.wait(task.task_id, 10)
            self.assertEqual(result.status, "completed", result.error)
            self.assertEqual(len(calls), 3)
            self.assertEqual(result.counts["analyzed"], 21)
            self.assertIn("LLM_AUTH", " ".join(result.warnings))
            self.assertEqual(store.load_analysis(task.run_id)["warnings"], result.warnings)
            self.assertEqual(store.read_manifest(task.run_id)["current_analysis"]["warnings"], result.warnings)

    def test_real_cli_error_and_recovery_keep_run_and_never_echo_error_body(self):
        with tempfile.TemporaryDirectory() as directory, provider([
            (401, error_body(), {}), (200, SUCCESS, {}),
        ]) as (url, calls):
            store = RunStore(Path(directory))
            run_id = new_run_id()
            store.create_run(run_id, "crawl", {})
            artifacts = store.save_comments(run_id, [{"comment_id": 1, "content": "中文评论"}])
            store.update_manifest(run_id, status="completed", artifacts=artifacts)
            comments = Path(artifacts["comments_json"]).read_bytes()
            env = {**os.environ, "BILIBILI_AGENT_RUNS_DIR": str(store.root), "BILIBILI_LLM_API_KEY": KEY,
                   "BILIBILI_LLM_BASE_URL": url, "BILIBILI_LLM_MODEL": "test-model"}
            command = [sys.executable, "-X", "utf8", "-m", "backend.agent", "analyze-run", run_id]
            failed = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                    capture_output=True, timeout=15)
            self.assertEqual(failed.returncode, 1, failed.stderr)
            payload = json.loads(failed.stdout)
            self.assertEqual(payload["error_code"], "LLM_AUTH")
            self.assertIn(f"analyze-run {run_id}", payload["next_step"])
            self.assertEqual(payload["run_id"], run_id)
            success = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                     capture_output=True, timeout=15)
            self.assertEqual(success.returncode, 0, success.stderr)
            self.assertEqual(len(calls), 2)
            self.assertEqual(Path(artifacts["comments_json"]).read_bytes(), comments)
            for data in (failed.stdout, failed.stderr, success.stdout, success.stderr):
                self.assertNotIn(KEY.encode(), data)
                self.assertNotIn(BODY_MARKER.encode(), data)

    def test_failed_provider_then_fixed_config_reuses_comments_and_scrubs_all_run_files(self):
        class Crawler:
            def crawl_comments(self, *args, **kwargs):
                return [{"comment_id": 1, "content": "评论", "username": "测试"}]

        with tempfile.TemporaryDirectory() as directory, provider([
            (401, error_body(), {}), (200, SUCCESS, {}),
        ]) as (url, calls):
            store = RunStore(Path(directory))
            service = AgentService(store=store, api=object(), crawler_factory=lambda progress: Crawler(),
                                   credentials_resolver=lambda: LLMCredentials(KEY, url, "test-model"))
            first = service.start_crawl_and_analyze("BV1xx411c7mD")
            failed = service.wait(first.task_id, 10)
            self.assertEqual(failed.error_code, "LLM_AUTH")
            comment_file = Path(failed.artifacts["comments_json"])
            digest = hashlib.sha256(comment_file.read_bytes()).hexdigest()
            retry = service.start_analyze(first.run_id)
            completed = service.wait(retry.task_id, 10)
            self.assertEqual(completed.status, "completed", completed.error)
            self.assertEqual(len(calls), 2)
            self.assertEqual(hashlib.sha256(comment_file.read_bytes()).hexdigest(), digest)
            manifest = store.read_manifest(first.run_id)
            self.assertEqual(manifest["analysis_attempts"][0]["error_code"], "LLM_AUTH")
            for path in store.root.rglob("*"):
                if path.is_file():
                    self.assertNotIn(KEY.encode(), path.read_bytes())
                    self.assertNotIn(BODY_MARKER.encode(), path.read_bytes())
