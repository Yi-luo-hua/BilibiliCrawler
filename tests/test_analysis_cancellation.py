import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wordcloud import WordCloud

from src.processor.analysis_processor import AnalysisCancelled, LLMAnalysisProcessor


class AnalysisCancellationTests(unittest.TestCase):
    def test_analyze_stops_promptly_while_llm_request_is_blocked(self) -> None:
        request_started = threading.Event()
        release_response = threading.Event()

        class SlowHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                request_started.set()
                release_response.wait(timeout=3)
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "summary": "ok",
                                            "risk_points": [],
                                            "insights": [],
                                            "notable_quotes": [],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                try:
                    self.wfile.write(body)
                except OSError:
                    pass

            def log_message(self, *args) -> None:
                return None

        server = ThreadingHTTPServer(("127.0.0.1", 0), SlowHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        cancel_event = threading.Event()
        errors: list[BaseException] = []

        def run_analysis() -> None:
            try:
                LLMAnalysisProcessor.analyze(
                    [{"comment_id": 1, "content": "测试评论"}],
                    [],
                    {
                        "source": "comments",
                        "strategy": "sample",
                        "sample_size": 20,
                        "batch_size": 20,
                        "chart_keys": ["topic_ranking"],
                        "llm_config": {
                            "api_key": "test-key",
                            "model": "test-model",
                            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                        },
                    },
                    cancel_event=cancel_event,
                )
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=run_analysis)
        worker.start()
        self.assertTrue(request_started.wait(timeout=2))

        cancel_event.set()
        worker.join(timeout=0.5)
        stopped_promptly = not worker.is_alive()

        release_response.set()
        worker.join(timeout=3)
        server.shutdown()
        server.server_close()

        self.assertTrue(stopped_promptly, "analyze() should return promptly after cancellation")
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], AnalysisCancelled)

    def test_analyze_stops_promptly_while_word_cloud_is_blocked(self) -> None:
        word_cloud_started = threading.Event()
        release_word_cloud = threading.Event()

        class ImmediateHandler(BaseHTTPRequestHandler):
            def do_POST(self) -> None:
                body = json.dumps(
                    {
                        "choices": [
                            {
                                "message": {
                                    "content": json.dumps(
                                        {
                                            "summary": "ok",
                                            "word_counts": [
                                                {"name": "测试词语", "value": 2}
                                            ],
                                            "risk_points": [],
                                            "insights": [],
                                            "notable_quotes": [],
                                        }
                                    )
                                }
                            }
                        ]
                    }
                ).encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args) -> None:
                return None

        original_generate = WordCloud.generate_from_frequencies

        def blocking_generate(instance, frequencies, max_font_size=None):
            word_cloud_started.set()
            release_word_cloud.wait(timeout=3)
            return instance

        server = ThreadingHTTPServer(("127.0.0.1", 0), ImmediateHandler)
        server_thread = threading.Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        cancel_event = threading.Event()
        errors: list[BaseException] = []

        def run_analysis() -> None:
            try:
                LLMAnalysisProcessor.analyze(
                    [{"comment_id": 1, "content": "测试评论"}],
                    [],
                    {
                        "source": "comments",
                        "strategy": "sample",
                        "sample_size": 20,
                        "batch_size": 20,
                        "chart_keys": ["word_cloud"],
                        "llm_config": {
                            "api_key": "test-key",
                            "model": "test-model",
                            "base_url": f"http://127.0.0.1:{server.server_port}/v1",
                        },
                    },
                    cancel_event=cancel_event,
                )
            except BaseException as exc:
                errors.append(exc)

        try:
            WordCloud.generate_from_frequencies = blocking_generate
            worker = threading.Thread(target=run_analysis)
            worker.start()
            self.assertTrue(word_cloud_started.wait(timeout=2))

            cancel_event.set()
            worker.join(timeout=0.5)
            stopped_promptly = not worker.is_alive()

            release_word_cloud.set()
            worker.join(timeout=3)
        finally:
            WordCloud.generate_from_frequencies = original_generate
            release_word_cloud.set()
            server.shutdown()
            server.server_close()

        self.assertTrue(stopped_promptly, "analyze() should stop during word-cloud generation")
        self.assertTrue(errors)
        self.assertIsInstance(errors[0], AnalysisCancelled)


if __name__ == "__main__":
    unittest.main()
