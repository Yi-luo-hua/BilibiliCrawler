"""Waiting changes the status text, not the amount of completed work."""
import json
import hashlib
import tempfile
import threading
import unittest
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import requests

from src.processor.analysis_processor import AnalysisCancelled, LLMAnalysisProcessor
from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.run_store import RunStore
from test_provider_recovery import KEY, SUCCESS, error_body, provider


@contextmanager
def slow_provider():
    entered, release, sent = (threading.Event() for _ in range(3))

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            entered.set()
            release.wait(5)
            body = json.dumps(SUCCESS).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            try:
                self.wfile.write(body)
            except OSError:
                pass
            finally:
                sent.set()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.01), daemon=True)
    worker.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", entered, release, sent
    finally:
        release.set()
        server.shutdown()
        server.server_close()
        worker.join(2)


class AnalysisProgressTests(unittest.TestCase):
    def analyze(self, url, progress, cancel=None, count=1):
        return LLMAnalysisProcessor.analyze(
            [{"comment_id": i, "content": f"评论{i}"} for i in range(count)], [],
            {"source": "comments", "batch_size": 20, "chart_keys": ["topic_ranking"],
             "llm_config": {"api_key": KEY, "model": "test-model", "base_url": url}},
            progress=progress, cancel_event=cancel,
        )

    def test_slow_http_refreshes_elapsed_time_without_inventing_progress(self):
        events, result, errors, callback_threads = [], [], [], []
        heartbeat = threading.Event()

        def progress(message, percent):
            events.append((message, percent))
            callback_threads.append(threading.get_ident())
            if "等待 LLM" in message and "已用时 1s" in message:
                heartbeat.set()

        with slow_provider() as (url, entered, release, sent):
            def run():
                try:
                    result.append(self.analyze(url, progress))
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(entered.wait(2))
                self.assertTrue(heartbeat.wait(3))
                waiting = [(message, percent) for message, percent in events if "等待 LLM" in message]
                self.assertGreaterEqual(len(waiting), 2)
                self.assertEqual({percent for _, percent in waiting}, {80})
                self.assertTrue(all("第 1/1 批" in message and "90/90s" in message for message, _ in waiting))
                self.assertEqual(set(callback_threads), {worker.ident})
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertFalse(errors, errors)
            self.assertEqual(result[0]["summary"], "recovered")

    def test_retries_and_summary_use_fixed_stage_percentages(self):
        events = []
        with provider([(503, error_body(), {"Retry-After": "0"}), (200, SUCCESS, {}),
                       (200, SUCCESS, {}), (200, SUCCESS, {})]) as (url, calls):
            self.analyze(url, lambda message, percent: events.append((message, percent)), count=21)
        self.assertEqual(len(calls), 4)
        self.assertTrue(any("LLM_UNAVAILABLE" in message and "重试 1" in message for message, _ in events))
        first = [(message, percent) for message, percent in events if "第 1/2 批 ·" in message]
        self.assertEqual({percent for _, percent in first}, {45})
        summary = [(message, percent) for message, percent in events if "总结整合 ·" in message]
        self.assertTrue(summary)
        self.assertEqual({percent for _, percent in summary}, {84})
        self.assertNotIn(KEY, str(events))

    def test_cancelled_wait_emits_no_late_progress(self):
        events, errors = [], []
        cancel, waiting = threading.Event(), threading.Event()

        def progress(message, percent):
            events.append((message, percent))
            if "等待 LLM" in message:
                waiting.set()

        with slow_provider() as (url, entered, release, sent):
            def run():
                try:
                    self.analyze(url, progress, cancel)
                except BaseException as exc:
                    errors.append(exc)

            worker = threading.Thread(target=run)
            worker.start()
            try:
                self.assertTrue(waiting.wait(2))
                cancel.set()
                worker.join(0.5)
                self.assertFalse(worker.is_alive())
                self.assertIsInstance(errors[0], AnalysisCancelled)
                captured = list(events)
            finally:
                release.set()
                worker.join(5)
            self.assertTrue(sent.wait(2))
            self.assertEqual(events, captured)

    def test_observer_failure_stops_retry_worker(self):
        response = requests.Response()
        response.status_code = 503
        response._content, response._content_consumed = b'{}', True
        response.headers["Retry-After"] = "1"
        stopped = threading.Event()
        real_close = requests.Session.close

        def close(session):
            if threading.current_thread() is not threading.main_thread():
                stopped.set()
            return real_close(session)

        def broken(message):
            raise RuntimeError("observer failed")

        with patch.object(requests.Session, "post", return_value=response) as post, \
                patch.object(requests.Session, "close", close):
            with self.assertRaisesRegex(RuntimeError, "observer failed"):
                LLMAnalysisProcessor._post_chat_completion(
                    "https://example.invalid/v1/chat/completions", {}, {}, None,
                    request_error="failed", invalid_json_error="invalid", request_progress=broken,
                )
            self.assertTrue(stopped.wait(2))
            self.assertEqual(post.call_count, 1)
            self.assertEqual(post.call_args.kwargs["timeout"], (90, 90))

    def test_timeout_then_retry_reuses_original_comments(self):
        class Crawler:
            def crawl_comments(self, *args, **kwargs):
                return [{"comment_id": 1, "content": "评论"}]

        real_post = requests.Session.post
        def quick_post(session, *args, **kwargs):
            kwargs["timeout"] = (0.1, 0.1)
            return real_post(session, *args, **kwargs)

        with tempfile.TemporaryDirectory() as directory, slow_provider() as (url, entered, release, sent):
            store = RunStore(Path(directory))
            service = AgentService(store=store, api=object(), crawler_factory=lambda progress: Crawler(),
                                   credentials_resolver=lambda: LLMCredentials(KEY, url, "test-model"))
            with patch.object(requests.Session, "post", quick_post):
                started = service.start_crawl_and_analyze("BV1xx411c7mD")
                failed = service.wait(started.task_id, 5)
            self.assertEqual(failed.error_code, "LLM_TIMEOUT")
            comments = Path(failed.artifacts["comments_json"])
            digest = hashlib.sha256(comments.read_bytes()).hexdigest()
            release.set()
            self.assertTrue(sent.wait(2))
            retry = service.start_analyze(started.run_id)
            result = service.wait(retry.task_id, 5)
            self.assertEqual(result.status, "completed", result.error)
            self.assertEqual(result.run_id, started.run_id)
            self.assertEqual(hashlib.sha256(comments.read_bytes()).hexdigest(), digest)
