import io
import json
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.models import MAX_PAGES_CEILING, ErrorCode, RunStatus, ServiceError, TaskKind
from src.service.run_store import RunStore

SAMPLE_COMMENTS = [
    {
        "comment_id": 1,
        "root_id": 0,
        "is_reply": False,
        "username": "用户A",
        "user_level": 5,
        "content": "第一条评论",
        "like_count": 3,
        "reply_count": 1,
        "ctime": 1735660800,
        "ctime_text": "2025-01-01 00:00:00",
        "ip_location": "广东",
    },
    {
        "comment_id": 2,
        "root_id": 1,
        "is_reply": True,
        "username": "用户B",
        "user_level": 2,
        "content": "第二条评论",
        "like_count": 0,
        "reply_count": 0,
        "ctime": 1735660900,
        "ctime_text": "2025-01-01 00:01:40",
        "ip_location": "北京",
    },
]

SECRET_KEY = "sk-DO-NOT-LEAK-abcdef123456"


class FakeCrawler:
    """Stands in for CommentCrawler; records the arguments it was handed."""

    def __init__(self, progress, comments=None, release=None):
        self.progress = progress
        self.comments = SAMPLE_COMMENTS if comments is None else comments
        self.release = release
        self.started = threading.Event()
        self.stopped = False
        self.calls: list[dict] = []

    def stop(self) -> None:
        self.stopped = True
        if self.release is not None:
            self.release.set()

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append(
            {"url": url_or_id, "include_replies": include_replies, "max_pages": max_pages, "mode": mode}
        )
        self.started.set()
        self.progress("正在爬取第 1 页")
        if self.release is not None:
            self.release.wait(timeout=5)
        # A stopped CommentCrawler still returns the pages it already fetched,
        # so returning [] here would make the fake more forgiving than reality
        # and hide the loss of partial results.
        return list(self.comments)


class FakeAnalysisProcessor:
    """Stands in for LLMAnalysisProcessor; captures the params it received."""

    def __init__(self, summary="整体情绪偏正面。", fail=None):
        self.summary = summary
        self.fail = fail
        self.params: list[dict] = []

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.params.append(params)
        if progress:
            progress("正在调用 LLM", 50)
        if self.fail is not None:
            raise self.fail
        return {
            "summary": self.summary,
            "notable_quotes": ["原样引用的评论"],
            "report_markdown": "# 报告\n\n正文",
            "meta": {"analyzed_records": len(comments), "total_records": len(comments)},
        }


def fake_credentials() -> LLMCredentials:
    return LLMCredentials(api_key=SECRET_KEY, base_url="https://example.invalid/v1", model="test-model")


def _api_reply(index: int) -> dict:
    return {
        "rpid": index,
        "member": {"uname": f"u{index}", "mid": index, "level_info": {"current_level": 1}},
        "content": {"message": f"comment {index}"},
        "like": 0,
        "rcount": 0,
        "ctime": 1735660800,
        "reply_control": {"location": "IP属地：广东"},
    }


class CountingAPI:
    """Minimal BilibiliAPI stand-in that records EVERY outbound request.

    Counting only comment pages once let a test assert "must not reach the
    network" while target resolution still fired a metadata request, so every
    method the crawler can call is tallied here.
    """

    def __init__(self) -> None:
        self.video_info_calls = 0
        self.comment_calls = 0
        self.reply_calls = 0
        self.dynamic_calls = 0

    @property
    def total_calls(self) -> int:
        return self.video_info_calls + self.comment_calls + self.reply_calls + self.dynamic_calls

    def get_video_info(self, bvid):
        self.video_info_calls += 1
        return {"data": {"aid": 12345}}

    def get_comments(self, *args, **kwargs):
        self.comment_calls += 1
        return {"data": {"replies": [], "cursor": {"is_end": True}}}

    def get_replies(self, *args, **kwargs):
        self.reply_calls += 1
        return {"data": {"replies": []}}

    def get_dynamic_detail(self, *args, **kwargs):
        self.dynamic_calls += 1
        return {}


class TwoPageAPI(CountingAPI):
    """Serves page 1 cleanly, then blocks on page 2 so a stop lands mid-crawl."""

    def __init__(self) -> None:
        super().__init__()
        self.second_page = threading.Event()
        self.release = threading.Event()

    def get_comments(self, oid, page=1, **kwargs):
        self.comment_calls += 1
        if self.comment_calls >= 2:
            self.second_page.set()
            self.release.wait(timeout=5)
        return {
            "data": {
                "replies": [_api_reply(self.comment_calls * 10 + n) for n in range(3)],
                "cursor": {"is_end": False, "next": self.comment_calls + 1},
            }
        }


class AgentServiceTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        # LIFO: registered first, so it runs last -- after the worker threads
        # below have been drained and released their file handles.
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.store = RunStore(self.root)
        self.crawlers: list[FakeCrawler] = []
        self.processor = FakeAnalysisProcessor()
        self.services: list[AgentService] = []
        self._releases: list[threading.Event] = []
        self.addCleanup(self._drain_workers)

    def _drain_workers(self) -> None:
        """Unblock and join every worker before the temp dir is removed.

        Windows refuses to unlink a file another thread still has open, so a
        task left running turns into a PermissionError during cleanup.
        """
        for release in self._releases:
            release.set()
        for service in self.services:
            for task in list(service._tasks.values()):
                if task.thread is not None:
                    task.thread.join(timeout=5)

    def make_service(self, comments=None, release=None, processor=None) -> AgentService:
        if release is not None:
            self._releases.append(release)

        def factory(progress):
            crawler = FakeCrawler(progress, comments=comments, release=release)
            self.crawlers.append(crawler)
            return crawler

        service = AgentService(
            store=self.store,
            api=object(),
            crawler_factory=factory,
            analysis_processor=processor or self.processor,
            credentials_resolver=fake_credentials,
        )
        self.services.append(service)
        return service

    def wait_for_crawler(self, index: int = 0, timeout: float = 5.0) -> FakeCrawler:
        """Wait for the worker thread to build its crawler and enter crawling.

        start_* returns as soon as the thread is spawned, so the crawler does
        not exist yet at that point.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if len(self.crawlers) > index and self.crawlers[index].started.wait(timeout=0.05):
                return self.crawlers[index]
            time.sleep(0.01)
        raise AssertionError(f"crawler #{index} never started")

    def run_to_completion(self, service: AgentService, snapshot, timeout: float = 5.0):
        final = service.wait(snapshot.task_id, timeout)
        self.assertTrue(final.done, f"task did not finish: {final.status} {final.error}")
        return final


class CrawlTests(AgentServiceTestCase):
    def test_crawl_writes_run_directory_with_manifest_and_artifacts(self) -> None:
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        self.assertEqual(snapshot.counts["comments"], 2)
        self.assertEqual(snapshot.counts["main_comments"], 1)
        self.assertEqual(snapshot.counts["replies"], 1)

        run_dir = self.store.run_dir(snapshot.run_id)
        self.assertTrue((run_dir / "manifest.json").is_file())
        self.assertTrue((run_dir / "comments.json").is_file())
        self.assertTrue((run_dir / "comments.csv").is_file())

        manifest = self.store.read_manifest(snapshot.run_id)
        self.assertEqual(manifest["status"], RunStatus.COMPLETED)
        self.assertEqual(manifest["kind"], TaskKind.CRAWL)

    def test_max_pages_ceiling_cannot_be_raised_by_caller(self) -> None:
        service = self.make_service()
        self.run_to_completion(service, service.start_crawl("BV1xx411c7mD", max_pages=99999))
        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], MAX_PAGES_CEILING)

    def test_empty_crawl_result_fails_with_actionable_message(self) -> None:
        service = self.make_service(comments=[])
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        self.assertEqual(snapshot.status, RunStatus.FAILED)
        self.assertEqual(snapshot.error_code, ErrorCode.CRAWL_FAILED)
        self.assertIn("没有爬到任何评论", snapshot.error or "")

    def test_blank_url_is_rejected_before_a_run_is_created(self) -> None:
        service = self.make_service()
        with self.assertRaises(ServiceError) as ctx:
            service.start_crawl("   ")
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_INPUT)
        self.assertEqual(self.store.list_runs(), [])


class AnalysisTests(AgentServiceTestCase):
    def seed_run(self) -> str:
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        return snapshot.run_id

    def test_analyze_run_recovers_a_run_started_by_another_process(self) -> None:
        run_id = self.seed_run()

        # A brand new service instance shares nothing but the run directory,
        # which is exactly what happens when the MCP host respawns the server.
        restarted = self.make_service()
        snapshot = self.run_to_completion(restarted, restarted.start_analyze(run_id))

        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        self.assertEqual(snapshot.run_id, run_id)
        self.assertEqual(snapshot.counts["analyzed"], 2)
        run_dir = self.store.run_dir(run_id)
        self.assertTrue((run_dir / "analysis.json").is_file())
        self.assertEqual((run_dir / "report.md").read_text(encoding="utf-8"), "# 报告\n\n正文")

    def test_status_for_a_foreign_run_id_is_rebuilt_from_the_manifest(self) -> None:
        run_id = self.seed_run()
        restarted = self.make_service()
        snapshot = restarted.get_status(run_id=run_id)
        self.assertEqual(snapshot.run_id, run_id)
        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        self.assertIn("comments_csv", snapshot.artifacts)

    def test_a_run_interrupted_by_a_dead_process_reports_as_failed(self) -> None:
        # A killed process leaves a non-terminal status on disk. Reporting that
        # verbatim would tell the caller to keep polling a task that no longer
        # exists, so it must surface as a terminal failure instead.
        run_id = self.seed_run()
        self.store.update_manifest(run_id, status=RunStatus.CRAWLING, stage="正在爬取评论")

        restarted = self.make_service()
        snapshot = restarted.get_status(run_id=run_id)

        self.assertEqual(snapshot.status, RunStatus.FAILED)
        self.assertTrue(snapshot.done)
        self.assertIn("中断", snapshot.stage)
        # The already-crawled data is still there and still usable.
        self.assertIn("comments_json", snapshot.artifacts)

    def test_default_chart_keys_are_explicit_and_exclude_word_cloud(self) -> None:
        # _normalize_chart_keys falls back to the FULL set (word cloud included)
        # when handed an empty list, so an explicit non-empty list is required.
        run_id = self.seed_run()
        service = self.make_service()
        self.run_to_completion(service, service.start_analyze(run_id))

        chart_keys = self.processor.params[0]["chart_keys"]
        self.assertTrue(chart_keys, "chart_keys must never be empty")
        self.assertNotIn("word_cloud", chart_keys)

    def test_analyze_rejects_unknown_and_traversal_run_ids(self) -> None:
        service = self.make_service()
        for bad_id, expected in [
            ("../../etc", ErrorCode.INVALID_INPUT),
            ("not-a-run-id", ErrorCode.INVALID_INPUT),
            ("20260101-000000-deadbeef", ErrorCode.NOT_FOUND),
        ]:
            with self.subTest(run_id=bad_id):
                with self.assertRaises(ServiceError) as ctx:
                    service.start_analyze(bad_id)
                self.assertEqual(ctx.exception.code, expected)

    def test_analyze_without_comments_reports_not_found(self) -> None:
        run_id = "20260101-000000-abcdef01"
        self.store.create_run(run_id, TaskKind.CRAWL, {"url": "BV1"})
        service = self.make_service()
        with self.assertRaises(ServiceError) as ctx:
            service.start_analyze(run_id)
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)

    def test_a_rejected_analyze_does_not_consume_the_task_slot(self) -> None:
        service = self.make_service()
        with self.assertRaises(ServiceError):
            service.start_analyze("not-a-run-id")
        # The single-task slot must still be free.
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        self.assertEqual(snapshot.status, RunStatus.COMPLETED)


class ConcurrencyAndCancellationTests(AgentServiceTestCase):
    def test_second_task_reports_busy_with_the_active_task_id(self) -> None:
        release = threading.Event()
        service = self.make_service(release=release)
        first = service.start_crawl("BV1xx411c7mD")
        self.wait_for_crawler()

        try:
            with self.assertRaises(ServiceError) as ctx:
                service.start_crawl("BV2yy411c7mD")
            self.assertEqual(ctx.exception.code, ErrorCode.BUSY)
            self.assertEqual(ctx.exception.context["task_id"], first.task_id)
        finally:
            release.set()
        self.run_to_completion(service, first)

    def test_stop_marks_the_run_cancelled_in_memory_and_on_disk(self) -> None:
        release = threading.Event()
        service = self.make_service(release=release)
        started = service.start_crawl("BV1xx411c7mD")
        crawler = self.wait_for_crawler()

        service.stop(started.task_id)
        snapshot = self.run_to_completion(service, started)

        self.assertEqual(snapshot.status, RunStatus.CANCELLED)
        self.assertEqual(snapshot.error_code, ErrorCode.CANCELLED)
        self.assertTrue(crawler.stopped)
        self.assertEqual(self.store.read_manifest(snapshot.run_id)["status"], RunStatus.CANCELLED)

    def test_the_task_slot_is_released_after_a_task_finishes(self) -> None:
        service = self.make_service()
        self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        second = self.run_to_completion(service, service.start_crawl("BV2yy411c7mD"))
        self.assertEqual(second.status, RunStatus.COMPLETED)

    def test_stop_with_an_unknown_task_id_reports_not_found(self) -> None:
        service = self.make_service()
        with self.assertRaises(ServiceError) as ctx:
            service.stop("task-does-not-exist")
        self.assertEqual(ctx.exception.code, ErrorCode.NOT_FOUND)


class SafetyTests(AgentServiceTestCase):
    def test_api_key_never_reaches_the_run_directory(self) -> None:
        service = self.make_service()
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        analysed = self.run_to_completion(service, service.start_analyze(crawled.run_id))

        self.assertEqual(analysed.status, RunStatus.COMPLETED)
        run_dir = self.store.run_dir(crawled.run_id)
        for path in run_dir.rglob("*"):
            if path.is_file():
                blob = path.read_bytes()
                self.assertNotIn(SECRET_KEY.encode("utf-8"), blob, f"key leaked into {path.name}")

        # ...and the credentials really were passed through to the processor,
        # so the assertion above is not vacuous.
        self.assertEqual(self.processor.params[0]["llm_config"]["api_key"], SECRET_KEY)

    def test_api_key_echoed_by_the_provider_is_scrubbed_everywhere(self) -> None:
        # A 401 body that quotes the key back at us is the realistic leak path:
        # the text flows into the snapshot, the manifest and the tool result.
        from src.processor.analysis_processor import AnalysisError

        service = self.make_service()
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        failing = FakeAnalysisProcessor(fail=AnalysisError(f"上游返回 401，使用的 key 是 {SECRET_KEY}"))
        broken = self.make_service(processor=failing)
        snapshot = self.run_to_completion(broken, broken.start_analyze(crawled.run_id))

        self.assertEqual(snapshot.status, RunStatus.FAILED)
        self.assertEqual(snapshot.error_code, ErrorCode.ANALYSIS_FAILED)
        self.assertNotIn(SECRET_KEY, snapshot.error or "")
        self.assertIn("***", snapshot.error or "")
        # And the surrounding message is preserved, so the user still sees why.
        self.assertIn("401", snapshot.error or "")

        manifest_text = (self.store.run_dir(crawled.run_id) / "manifest.json").read_text(
            encoding="utf-8"
        )
        self.assertNotIn(SECRET_KEY, manifest_text)

    def test_a_full_run_writes_nothing_to_stdout(self) -> None:
        # stdout carries the MCP JSON-RPC stream; a stray print corrupts it.
        buffer = io.StringIO()
        service = self.make_service()
        with redirect_stdout(buffer):
            crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
            self.run_to_completion(service, service.start_analyze(crawled.run_id))
        self.assertEqual(buffer.getvalue(), "")

    def test_manifest_is_valid_json_with_no_credential_shaped_keys(self) -> None:
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        raw = (self.store.run_dir(snapshot.run_id) / "manifest.json").read_text(encoding="utf-8")
        manifest = json.loads(raw)
        self.assertNotIn("llm_config", manifest["params"])
        self.assertNotIn("api_key", manifest["params"])


class ReviewRegressionTests(AgentServiceTestCase):
    """Regressions for issues found in review. Each one reproduced before the fix."""

    def test_cancel_landing_during_export_is_not_overwritten_by_completion(self) -> None:
        # Checking cancellation only before the export let the completion update
        # clobber `cancelling`, so a stopped task finished as `completed`.
        entered, release = threading.Event(), threading.Event()

        class BlockingStore(RunStore):
            def save_comments(inner, run_id, comments):  # noqa: N805
                entered.set()
                release.wait(timeout=5)
                return super().save_comments(run_id, comments)

        self.store = BlockingStore(self.root)
        self._releases.append(release)
        service = self.make_service()
        started = service.start_crawl("BV1xx411c7mD")

        self.assertTrue(entered.wait(timeout=5))
        stop_snapshot = service.stop(started.task_id)
        release.set()
        final = self.run_to_completion(service, started)

        self.assertEqual(stop_snapshot.status, RunStatus.CANCELLING)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(self.store.read_manifest(final.run_id)["status"], RunStatus.CANCELLED)
        # The data written before the stop is still recorded.
        self.assertEqual(final.counts["comments"], 2)

    def test_cancelling_before_the_crawl_starts_issues_no_requests(self) -> None:
        # Uses the REAL CommentCrawler on purpose. A fake one cannot catch this:
        # crawl_comments() sets self._stop_flag = False on entry, so a stop()
        # called beforehand is silently discarded and the crawl runs anyway.
        # An earlier version of this test used a fake and passed while the real
        # crawler still issued page requests.
        from src.crawler.comment_crawler import CommentCrawler

        api = CountingAPI()
        service = AgentService(
            store=self.store,
            api=api,
            crawler_factory=lambda progress: CommentCrawler(progress_callback=progress, api=api),
            analysis_processor=self.processor,
            credentials_resolver=fake_credentials,
        )
        self.services.append(service)

        started = service.start_crawl("BV1xx411c7mD", max_pages=3)
        service.stop(started.task_id)
        final = service.wait(started.task_id, 10)

        self.assertEqual(api.total_calls, 0, "a pre-cancelled crawl must not hit the network")
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertTrue(final.done)

    def test_stopping_a_running_real_crawler_does_not_recurse(self) -> None:
        # CommentCrawler.stop() writes a progress log, which re-enters the
        # service's progress callback, which asked to stop again -- the first
        # version of the early-cancel fix recursed until the stack blew and the
        # task ended as `failed`. Only the real crawler shows this; a fake's
        # stop() does not log.
        from src.crawler.comment_crawler import CommentCrawler

        api = TwoPageAPI()
        service = AgentService(
            store=self.store,
            api=api,
            crawler_factory=lambda progress: CommentCrawler(progress_callback=progress, api=api),
            analysis_processor=self.processor,
            credentials_resolver=fake_credentials,
        )
        self.services.append(service)
        self._releases.append(api.release)

        started = service.start_crawl("BV1xx411c7mD", max_pages=5)
        self.assertTrue(api.second_page.wait(timeout=5))
        stop_snapshot = service.stop(started.task_id)   # lands mid-crawl
        api.release.set()
        final = service.wait(started.task_id, 10)

        self.assertNotIn("recursion", (final.error or "").lower())
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertTrue(final.done)
        self.assertIn(stop_snapshot.status, {RunStatus.CANCELLING, *RunStatus.TERMINAL})
        # The completed first page survives; the in-flight page is dropped.
        self.assertEqual(final.counts.get("comments"), 3)
        self.assertTrue((self.store.run_dir(final.run_id) / "comments.json").is_file())

    def test_a_stop_between_the_cancel_check_and_crawler_publication_still_stops(self) -> None:
        # The window the early-cancel guard alone cannot cover: _do_crawl has
        # already passed its cancel check, and stop() arrives while the crawler
        # is still being constructed. Blocking inside the factory pins it.
        from src.crawler.comment_crawler import CommentCrawler

        api = CountingAPI()
        factory_entered = threading.Event()
        stop_issued = threading.Event()
        self._releases.append(stop_issued)

        def factory(progress):
            factory_entered.set()
            stop_issued.wait(timeout=5)
            return CommentCrawler(progress_callback=progress, api=api)

        service = AgentService(
            store=self.store,
            api=api,
            crawler_factory=factory,
            analysis_processor=self.processor,
            credentials_resolver=fake_credentials,
        )
        self.services.append(service)

        started = service.start_crawl("BV1xx411c7mD", max_pages=3)
        self.assertTrue(factory_entered.wait(timeout=5))
        service.stop(started.task_id)
        stop_issued.set()
        final = service.wait(started.task_id, 10)

        # Total, not just comment pages: crawl_comments() resolves the target
        # first, so an earlier version of this fix still fired one
        # get_video_info() while this assertion only counted get_comments().
        self.assertEqual(api.total_calls, 0, "a cancelled crawl must issue no requests at all")
        self.assertEqual(api.video_info_calls, 0)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertTrue(final.done)

    def test_credential_discovery_covers_the_real_installer_default(self) -> None:
        # tauri.conf.json pins productName BilibiliCrawler + installMode
        # currentUser, and Tauri 2.11.2's NSIS template installs that to
        # $LOCALAPPDATA\<PRODUCTNAME> -- there is no "Programs" segment, which
        # an earlier version of this probe wrongly assumed.
        import os

        from src.service.credentials import credential_file_candidates

        local_app_data = os.environ.get("LOCALAPPDATA")
        if not local_app_data:
            self.skipTest("LOCALAPPDATA is not set")

        expected = (
            Path(local_app_data) / "BilibiliCrawler" / "user-data" / "config" / "credentials.json"
        )
        self.assertIn(expected, credential_file_candidates())

    def test_a_stop_racing_the_terminal_commit_leaves_consistent_state(self) -> None:
        # stop() used to overwrite the just-committed terminal status with
        # `cancelling`, leaving done=False forever while the manifest said
        # completed -- an agent polling on `done` would wait indefinitely.
        entered, release = threading.Event(), threading.Event()

        class BarrierStore(RunStore):
            def update_manifest(inner, run_id, **changes):  # noqa: N805
                if changes.get("status") in (RunStatus.COMPLETED, RunStatus.CANCELLED):
                    if not entered.is_set():
                        entered.set()
                        release.wait(timeout=5)
                return super().update_manifest(run_id, **changes)

        self.store = BarrierStore(self.root)
        self._releases.append(release)
        service = self.make_service()
        started = service.start_crawl("BV1xx411c7mD")

        self.assertTrue(entered.wait(timeout=5))
        stop_snapshot = service.stop(started.task_id)   # lands inside the window
        release.set()
        final = self.run_to_completion(service, started)

        manifest_status = self.store.read_manifest(final.run_id)["status"]
        self.assertEqual(final.status, manifest_status, "memory and manifest disagree")
        self.assertTrue(final.done, "a settled task must report done")
        self.assertIn(final.status, RunStatus.TERMINAL)
        self.assertIn(stop_snapshot.status, {RunStatus.CANCELLING, *RunStatus.TERMINAL})

    def test_an_api_key_in_the_environment_is_scrubbed_from_logs(self) -> None:
        # logger.exception used to emit the raw message and traceback, so a key
        # echoed back by a provider reached stderr even though the snapshot and
        # manifest were clean.
        import logging

        from src.service.credentials import install_log_scrubbing, register_secret

        register_secret(SECRET_KEY)

        class Exploding:
            def __init__(self, progress):
                pass

            def stop(self):
                pass

            def crawl_comments(self, *args, **kwargs):
                raise RuntimeError(f"upstream said key={SECRET_KEY}")

        stream = io.StringIO()
        handler = logging.StreamHandler(stream)
        root = logging.getLogger()
        previous_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        install_log_scrubbing()
        try:
            service = AgentService(
                store=self.store,
                api=object(),
                crawler_factory=Exploding,
                credentials_resolver=fake_credentials,
            )
            self.services.append(service)
            snapshot = service.wait(service.start_crawl("BV1xx411c7mD").task_id, 5)
        finally:
            root.removeHandler(handler)
            root.setLevel(previous_level)

        logged = stream.getvalue()
        self.assertNotIn(SECRET_KEY, logged, "the key reached stderr")
        self.assertNotIn(SECRET_KEY, snapshot.error or "")
        self.assertIn("upstream said", snapshot.error or "", "the message must stay useful")

    def test_a_failed_csv_export_is_surfaced_as_a_warning(self) -> None:
        # The run used to report plain success with the CSV silently missing.
        import src.service.run_store as run_store_module

        original = run_store_module.CSVExporter.export
        run_store_module.CSVExporter.export = staticmethod(lambda *a, **k: False)
        try:
            service = self.make_service()
            snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        finally:
            run_store_module.CSVExporter.export = original

        self.assertEqual(snapshot.counts["comments"], 2)
        self.assertIn("comments_json", snapshot.artifacts)
        self.assertNotIn("comments_csv", snapshot.artifacts)
        self.assertTrue(snapshot.warnings, "a missing CSV must not be silent")
        self.assertIn("CSV", snapshot.warnings[0])
        # And no half-written CSV is left behind.
        run_dir = self.store.run_dir(snapshot.run_id)
        self.assertFalse((run_dir / "comments.csv").exists())
        self.assertEqual([p.name for p in run_dir.iterdir() if p.name.endswith(".tmp")], [])

    def test_cancelling_mid_crawl_keeps_the_comments_already_fetched(self) -> None:
        # The MCP stop_task hint promises partial data is kept; the cancel path
        # used to return before saving anything, making that promise false.
        release = threading.Event()
        service = self.make_service(release=release)
        started = service.start_crawl("BV1xx411c7mD")
        self.wait_for_crawler()
        service.stop(started.task_id)
        final = self.run_to_completion(service, started)

        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(final.counts.get("comments"), 2, "partial results were discarded")
        self.assertIn("comments_json", final.artifacts)
        self.assertTrue((self.store.run_dir(final.run_id) / "comments.json").is_file())

    def test_a_busy_rejection_leaves_no_orphan_run_directory(self) -> None:
        release = threading.Event()
        service = self.make_service(release=release)
        first = service.start_crawl("BV1xx411c7mD")
        self.wait_for_crawler()
        before = self.store.list_runs()

        with self.assertRaises(ServiceError) as ctx:
            service.start_crawl("BV2yy411c7mD")
        self.assertEqual(ctx.exception.code, ErrorCode.BUSY)

        self.assertEqual(self.store.list_runs(), before, "BUSY must not create a run directory")
        release.set()
        self.run_to_completion(service, first)

    def test_a_crawl_export_failure_is_not_labelled_an_analysis_failure(self) -> None:
        class FailingStore(RunStore):
            def save_comments(inner, run_id, comments):  # noqa: N805
                raise OSError("disk full")

        self.store = FailingStore(self.root)
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        self.assertEqual(snapshot.status, RunStatus.FAILED)
        self.assertEqual(snapshot.error_code, ErrorCode.CRAWL_FAILED)

    def test_analysis_preserves_the_crawl_counts_and_artifacts_in_the_manifest(self) -> None:
        # A re-analysis starts with empty counts/artifacts; overwriting the
        # manifest erased how many comments the run held and where the CSV was.
        service = self.make_service()
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        restarted = self.make_service()
        analysed = self.run_to_completion(restarted, restarted.start_analyze(crawled.run_id))

        manifest = self.store.read_manifest(crawled.run_id)
        self.assertEqual(manifest["counts"]["comments"], 2, "crawl count was lost")
        self.assertEqual(manifest["counts"]["analyzed"], 2)
        self.assertIn("comments_csv", manifest["artifacts"], "crawl artifact was lost")
        self.assertIn("report_markdown", manifest["artifacts"])
        # The live snapshot carries them too, not just the manifest.
        self.assertEqual(analysed.counts["comments"], 2)

    def test_sort_mode_is_restricted_to_the_documented_values(self) -> None:
        service = self.make_service()
        for given, expected in [(2, 2), (3, 3), (999, 3), (-1, 3), ("2", 2), (None, 3)]:
            with self.subTest(sort_mode=given):
                self.assertEqual(service._crawl_params("BV1", 5, True, given)["sort_mode"], expected)

    def test_a_failed_manifest_write_leaves_the_previous_one_intact(self) -> None:
        # Writes go through a temp file plus os.replace, so a crash mid-write
        # cannot leave truncated JSON that breaks restart recovery.
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        manifest_path = self.store.run_dir(snapshot.run_id) / "manifest.json"
        before = manifest_path.read_text(encoding="utf-8")

        import src.service.run_store as run_store_module

        original = run_store_module._atomic_write_bytes

        def exploding(path, payload):
            if path.name == "manifest.json":
                raise OSError("crash mid-write")
            return original(path, payload)

        run_store_module._atomic_write_bytes = exploding
        try:
            with self.assertRaises(OSError):
                self.store.update_manifest(snapshot.run_id, status="whatever")
        finally:
            run_store_module._atomic_write_bytes = original

        self.assertEqual(manifest_path.read_text(encoding="utf-8"), before)
        self.assertEqual(json.loads(before)["status"], RunStatus.COMPLETED)

    def test_no_temp_files_are_left_behind_in_a_run_directory(self) -> None:
        service = self.make_service()
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        self.run_to_completion(service, service.start_analyze(crawled.run_id))

        leftovers = [p.name for p in self.store.run_dir(crawled.run_id).iterdir()
                     if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_the_cli_marks_the_summary_as_untrusted_too(self) -> None:
        # The CLI is a supported way for an agent to drive this tool, so it must
        # not hand back a bare model-written summary the way it used to.
        from backend.agent import _snapshot_payload
        from src.service.models import UNTRUSTED_CLOSE, UNTRUSTED_OPEN

        service = self.make_service()
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        analysed = self.run_to_completion(service, service.start_analyze(crawled.run_id))

        payload = _snapshot_payload(analysed)
        self.assertTrue(payload["summary"].startswith(UNTRUSTED_OPEN))
        self.assertTrue(payload["summary"].endswith(UNTRUSTED_CLOSE))
        self.assertIn("整体情绪偏正面", payload["summary"])

    def test_the_writability_probe_does_not_delete_a_real_file(self) -> None:
        # The probe used a fixed ".write-test" name and unlinked it
        # unconditionally, which would destroy a same-named real file.
        from src.service.paths import _is_writable

        victim = self.root / ".write-test"
        victim.write_text("important", encoding="utf-8")

        self.assertTrue(_is_writable(self.root))
        self.assertTrue(victim.exists(), "the probe deleted an unrelated file")
        self.assertEqual(victim.read_text(encoding="utf-8"), "important")


class ProgressTests(AgentServiceTestCase):
    def test_progress_events_are_drainable_by_an_adapter(self) -> None:
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        events = service.drain_progress(snapshot.task_id)
        self.assertTrue(events)
        self.assertTrue(all(isinstance(percent, int) for percent, _ in events))
        self.assertIn("正在爬取第 1 页", [message for _, message in events])

    def test_draining_an_unknown_task_returns_no_events(self) -> None:
        service = self.make_service()
        self.assertEqual(service.drain_progress("task-nope"), [])


if __name__ == "__main__":
    unittest.main()
