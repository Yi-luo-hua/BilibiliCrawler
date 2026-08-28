import io
import json
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from src.processor.analysis_processor import LLMAnalysisProcessor
from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.models import (
    DESKTOP_POLICY,
    MAX_PAGES_CEILING,
    ErrorCode,
    RunStatus,
    ServiceError,
    TaskKind,
)
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
        # What the real crawler learns resolving the target.
        self.target_info = {
            "bvid": "BV1xx411c7mD",
            "aid": 12345,
            "title": "测试视频",
            "owner": "测试UP主",
            "pubdate": 1735660800,
        }

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

    # The service re-renders the on-disk report with run context through this
    # method, so the fake borrows the real renderer to exercise that path.
    _build_markdown_report = LLMAnalysisProcessor._build_markdown_report

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
            # Enough of the real result's data layers for the borrowed
            # _build_markdown_report to render every enriched section.
            "sentiment_counts": [
                {"name": "正向", "value": 2},
                {"name": "中性", "value": 1},
                {"name": "负向", "value": 0},
            ],
            "time_series": [{"name": "01-01", "count": 2, "likes": 3}],
            "notable_quotes": ["原样引用的评论", "第一条评论"],
            "report_markdown": "# 报告\n\n正文",
            "meta": {"analyzed_records": len(comments), "total_records": len(comments)},
        }


class CancelOnReturnProcessor(FakeAnalysisProcessor):
    """Simulates a stop landing after the analysis returned but before export.

    The full LLM cost is already paid at that point, so the result must be
    persisted and settled as cancelled -- exactly like the crawl half keeps
    partial data on the same race.
    """

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        result = super().analyze(comments, dynamics, params, progress=progress, cancel_event=cancel_event)
        if cancel_event is not None:
            cancel_event.set()
        return result


class BadWordCloudProcessor(FakeAnalysisProcessor):
    """Returns a word cloud data URL whose payload is not valid base64."""

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        result = super().analyze(comments, dynamics, params, progress=progress, cancel_event=cancel_event)
        result["word_cloud_image"] = "data:image/png;base64,!!!!"
        return result


# A 1x1 transparent PNG: the smallest payload that decodes and writes cleanly.
_TINY_PNG_DATA_URL = (
    "data:image/png;base64,"
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="
)


class WordCloudProcessor(FakeAnalysisProcessor):
    """Returns a valid word-cloud data URL, as the real renderer would."""

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        result = super().analyze(comments, dynamics, params, progress=progress, cancel_event=cancel_event)
        result["word_cloud_image"] = _TINY_PNG_DATA_URL
        return result


class StopAfterAnalysisProcessor(FakeAnalysisProcessor):
    """Issues service.stop() after analyze() returned, before the export.

    The stop therefore provably lands between the analysis result and the
    update(status=EXPORTING) that follows it -- the exact race the CANCELLING
    guard in _Task.update exists for.
    """

    def __init__(self):
        super().__init__()
        self._armed = threading.Event()
        self._service: AgentService | None = None
        self._task_id = ""

    def arm(self, service: AgentService, task_id: str) -> None:
        self._service = service
        self._task_id = task_id
        self._armed.set()

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        result = super().analyze(comments, dynamics, params, progress=progress, cancel_event=cancel_event)
        # Wait for the test to hand us the task id: the worker may reach here
        # before start_analyze() has returned to the main thread.
        self._armed.wait(timeout=5)
        assert self._service is not None
        self._service.stop(self._task_id)
        return result


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

    def make_service(self, comments=None, release=None, processor=None, policy=None, retain_outcome=False) -> AgentService:
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
            policy=policy,
            retain_outcome=retain_outcome,
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

    def seed_run(self) -> str:
        """A finished crawl whose run directory is ready for analysis."""
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        return snapshot.run_id


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

    def test_manifest_artifacts_are_portable_but_snapshots_stay_absolute(self) -> None:
        # Copying a run directory to another machine breaks absolute paths;
        # the manifest stores run-relative ones and consumers resolve them
        # against run_dir() at read time.
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        manifest = self.store.read_manifest(snapshot.run_id)
        self.assertEqual(manifest["artifacts"]["comments_json"], "comments.json")
        self.assertEqual(manifest["artifacts"]["comments_csv"], "comments.csv")
        self.assertEqual(
            Path(snapshot.artifacts["comments_json"]).name, "comments.json"
        )
        self.assertTrue(Path(snapshot.artifacts["comments_json"]).is_absolute())
        self.assertTrue(Path(snapshot.artifacts["comments_json"]).is_file())

    def test_crawl_manifest_records_the_video_metadata_the_crawler_learned(self) -> None:
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        manifest = self.store.read_manifest(snapshot.run_id)
        self.assertEqual(manifest["target"]["title"], "测试视频")
        self.assertEqual(manifest["target"]["owner"], "测试UP主")
        self.assertEqual(manifest["target"]["bvid"], "BV1xx411c7mD")

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

    def test_desktop_policy_empty_crawl_is_success_without_a_csv_warning(self) -> None:
        # No data is not an export failure: the desktop policy finishes an
        # empty crawl as success, and warning about the missing CSV would
        # record a failure that never happened.
        service = self.make_service(comments=[], policy=DESKTOP_POLICY)
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        self.assertEqual(snapshot.counts["comments"], 0)
        self.assertIn("comments_json", snapshot.artifacts)
        self.assertNotIn("comments_csv", snapshot.artifacts)
        self.assertEqual(snapshot.warnings, [], "no data must not be reported as a CSV export failure")

    def test_blank_url_is_rejected_before_a_run_is_created(self) -> None:
        service = self.make_service()
        with self.assertRaises(ServiceError) as ctx:
            service.start_crawl("   ")
        self.assertEqual(ctx.exception.code, ErrorCode.INVALID_INPUT)
        self.assertEqual(self.store.list_runs(), [])


class AnalysisTests(AgentServiceTestCase):

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
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("# 舆论分析报告：测试视频", report)
        self.assertIn("整体情绪偏正面", report)
        # Run context the processor cannot know: provenance for a report that
        # travels outside its run directory.
        self.assertIn(f"- Run ID：{run_id}", report)
        self.assertIn("- 数据来源：BV1xx411c7mD（测试视频）", report)
        self.assertIn("- UP 主：测试UP主", report)
        self.assertIn("- 发布时间：2025-01-01", report)
        # The enriched sections render from the result's own data layers.
        self.assertIn("- 正向：2（66.7%）", report)
        self.assertIn("| 01-01 | 2 | 3 |", report)
        # "第一条评论" is SAMPLE_COMMENTS[0] verbatim, so it gets attributed
        # to the user who wrote it and the likes it drew.
        self.assertIn("「第一条评论」—— 用户A，点赞 3", report)

    def test_a_stop_landing_after_the_analysis_keeps_the_completed_result(self) -> None:
        run_id = self.seed_run()
        service = self.make_service(processor=CancelOnReturnProcessor())
        snapshot = self.run_to_completion(service, service.start_analyze(run_id))

        self.assertEqual(snapshot.status, RunStatus.CANCELLED)
        run_dir = self.store.run_dir(run_id)
        self.assertTrue((run_dir / "analysis.json").is_file(), "paid-for analysis was discarded")
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("整体情绪偏正面", report)
        self.assertIn(f"- Run ID：{run_id}", report)
        manifest = self.store.read_manifest(run_id)
        self.assertEqual(manifest["status"], RunStatus.CANCELLED)
        self.assertIn("report_markdown", manifest["artifacts"])

    def test_an_unparseable_word_cloud_warns_instead_of_vanishing(self) -> None:
        run_id = self.seed_run()
        service = self.make_service(processor=BadWordCloudProcessor())
        snapshot = self.run_to_completion(service, service.start_analyze(run_id))

        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        self.assertNotIn("word_cloud_image", snapshot.artifacts)
        self.assertTrue(any("词云" in w for w in snapshot.warnings), snapshot.warnings)
        run_dir = self.store.run_dir(run_id)
        self.assertFalse((run_dir / "assets" / "word_cloud.png").exists())

    def test_the_run_report_embeds_the_word_cloud_written_next_to_it(self) -> None:
        run_id = self.seed_run()
        service = self.make_service(processor=WordCloudProcessor())
        snapshot = self.run_to_completion(service, service.start_analyze(run_id))

        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        run_dir = self.store.run_dir(run_id)
        self.assertTrue((run_dir / "assets" / "word_cloud.png").is_file())
        # The PNG used to sit next to the report unnamed; the report's word
        # cloud section was a plain word-frequency list that never linked it.
        report = (run_dir / "report.md").read_text(encoding="utf-8")
        self.assertIn("![词云图](assets/word_cloud.png)", report)

    def test_reanalysis_archives_the_previous_result_and_drops_stale_artifacts(self) -> None:
        run_id = self.seed_run()
        first_service = self.make_service(processor=WordCloudProcessor())
        first = self.run_to_completion(first_service, first_service.start_analyze(run_id))
        self.assertIn("word_cloud_image", first.artifacts)

        # A second analysis without a word cloud: the old files move to
        # archive/, and neither the snapshot nor the manifest may keep
        # announcing the archived word cloud as the current artifact.
        second_service = self.make_service()
        second = self.run_to_completion(second_service, second_service.start_analyze(run_id))

        self.assertEqual(second.status, RunStatus.COMPLETED)
        self.assertNotIn("word_cloud_image", second.artifacts)
        self.assertIn("analysis_json", second.artifacts)
        manifest = self.store.read_manifest(run_id)
        self.assertNotIn("word_cloud_image", manifest["artifacts"])

        run_dir = self.store.run_dir(run_id)
        self.assertFalse((run_dir / "assets" / "word_cloud.png").exists())
        archives = list((run_dir / "archive").iterdir())
        self.assertEqual(len(archives), 1, "both analyses share one archive entry")
        archived = {p.name for p in archives[0].iterdir()}
        self.assertIn("analysis.json", archived)
        self.assertIn("report.md", archived)
        # The archived report references assets/word_cloud.png, so the image
        # is archived under the same sub-path to keep the copy self-contained.
        self.assertIn("assets", archived)
        self.assertIn("word_cloud.png", {p.name for p in (archives[0] / "assets").iterdir()})
        # The fresh result keeps the canonical names.
        self.assertTrue((run_dir / "analysis.json").is_file())
        self.assertTrue((run_dir / "report.md").is_file())

    def test_failed_reanalysis_keeps_the_previous_canonical_result(self) -> None:
        run_id = self.seed_run()
        self.store.save_analysis(
            run_id,
            {"summary": "old", "report_markdown": "# old"},
        )
        run_dir = self.store.run_dir(run_id)
        old_json = (run_dir / "analysis.json").read_bytes()
        old_report = (run_dir / "report.md").read_bytes()

        cyclic = {"summary": "new", "report_markdown": "# new"}
        cyclic["cycle"] = cyclic
        with self.assertRaises((RecursionError, ValueError)):
            self.store.save_analysis(run_id, cyclic)

        self.assertEqual((run_dir / "analysis.json").read_bytes(), old_json)
        self.assertEqual((run_dir / "report.md").read_bytes(), old_report)
        self.assertFalse((run_dir / "archive").exists())

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

    def test_api_key_echoed_in_analysis_result_is_scrubbed_from_json(self) -> None:
        class EchoingAnalysisProcessor(FakeAnalysisProcessor):
            def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
                result = super().analyze(comments, dynamics, params, progress, cancel_event)
                result["meta"]["config"] = dict(params)
                return result

        service = self.make_service(processor=EchoingAnalysisProcessor())
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        analysed = self.run_to_completion(service, service.start_analyze(crawled.run_id))

        self.assertEqual(analysed.status, RunStatus.COMPLETED)
        run_dir = self.store.run_dir(crawled.run_id)
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_KEY.encode("utf-8"), path.read_bytes(), f"key leaked into {path.name}")

        analysis_path = run_dir / "analysis.json"
        raw = analysis_path.read_text(encoding="utf-8")
        self.assertEqual(json.loads(raw)["meta"]["config"]["llm_config"]["api_key"], "***")

    def test_api_key_echoed_in_analysis_report_is_scrubbed_from_markdown(self) -> None:
        class EchoingReportProcessor(FakeAnalysisProcessor):
            # Custom processors without a renderer persist their returned
            # report verbatim, which exercises RunStore's report scrub boundary.
            _build_markdown_report = None

            def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
                result = super().analyze(comments, dynamics, params, progress, cancel_event)
                result["report_markdown"] = f"# 报告\n\nkey: {params['llm_config']['api_key']}"
                return result

        service = self.make_service(processor=EchoingReportProcessor())
        crawled = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))
        analysed = self.run_to_completion(service, service.start_analyze(crawled.run_id))

        self.assertEqual(analysed.status, RunStatus.COMPLETED)
        run_dir = self.store.run_dir(crawled.run_id)
        for path in run_dir.rglob("*"):
            if path.is_file():
                self.assertNotIn(SECRET_KEY.encode("utf-8"), path.read_bytes(), f"key leaked into {path.name}")

        report_path = run_dir / "report.md"
        raw = report_path.read_text(encoding="utf-8")
        self.assertIn("key: ***", raw)

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


class ReviewHardeningTests(AgentServiceTestCase):
    """Guards for behaviours whose implementations had no test coverage.

    Each of these can be deleted alongside the code it protects and every
    other test keeps passing -- which is exactly why they exist.
    """

    def test_csv_formula_prefixes_survive_to_the_exported_file(self) -> None:
        # End-to-end through save_comments: the guard lives in _write_csv,
        # so a refactor of the writer (not the sanitizer) must not lose it.
        malicious = [
            "=HYPERLINK(\"http://evil\", \"click\")",
            "+cmd|' /C calc'!A0",
            "-前排围观",
            "@SUM(1+1)",
        ]
        comments = [
            {
                "comment_id": index + 1,
                "root_id": 0,
                "is_reply": False,
                "username": f"用户{index}",
                "user_level": 3,
                "content": body,
                "like_count": 0,
                "reply_count": 0,
                "ctime": 1735660800,
                "ctime_text": "2025-01-01 00:00:00",
                "ip_location": "广东",
            }
            for index, body in enumerate(malicious)
        ]
        service = self.make_service(comments=comments)
        snapshot = self.run_to_completion(service, service.start_crawl("BV1xx411c7mD"))

        import csv as csv_module

        csv_path = Path(snapshot.artifacts["comments_csv"])
        with csv_path.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv_module.reader(handle))
        content_idx = rows[0].index("评论内容")
        exported = [row[content_idx] for row in rows[1:]]
        self.assertEqual(exported, [f"'{body}" for body in malicious])
        # The JSON twin is the fidelity reference: no apostrophes there.
        on_disk = json.loads(
            (self.store.run_dir(snapshot.run_id) / "comments.json").read_text(encoding="utf-8")
        )
        self.assertEqual([item["content"] for item in on_disk], malicious)

    def test_a_phase_transition_cannot_roll_back_a_pending_cancel(self) -> None:
        observed: dict[str, str] = {}

        class ObservingStore(RunStore):
            # Records the task status at the moment the analysis export
            # starts writing: with the guard it reads CANCELLING, without it
            # the EXPORTING update would have overwritten the pending stop.
            def __init__(self, root):
                super().__init__(root)
                self.service = None

            def save_analysis(self, run_id, result, warnings=None):
                if self.service is not None:
                    observed["status"] = self.service.get_status(run_id=run_id).status
                return super().save_analysis(run_id, result, warnings=warnings)

        store = ObservingStore(self.root)
        self.store = store
        run_id = self.seed_run()

        processor = StopAfterAnalysisProcessor()
        service = self.make_service(processor=processor)
        store.service = service
        started = service.start_analyze(run_id)
        processor.arm(service, started.task_id)
        final = self.run_to_completion(service, started)

        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(observed.get("status"), RunStatus.CANCELLING,
                         "update(EXPORTING) rolled back a pending cancel")

    def test_desktop_pre_cancel_settles_with_empty_data_not_an_error(self) -> None:
        class FirstCrawlPersistGateStore(RunStore):
            # Blocks the worker's first manifest update (status=crawling) so
            # the test's stop() provably precedes the crawl's first
            # cancel-check window, with no thread race to rely on.
            def __init__(self, root):
                super().__init__(root)
                self.gate = threading.Event()
                self.in_persist = threading.Event()

            def write_manifest(self, run_id, manifest):
                if str(manifest.get("status")) == "crawling" and not self.in_persist.is_set():
                    self.in_persist.set()
                    self.gate.wait(timeout=10)
                return super().write_manifest(run_id, manifest)

        store = FirstCrawlPersistGateStore(self.root)
        self.store = store
        service = self.make_service(policy=DESKTOP_POLICY, retain_outcome=True)
        started = service.start_crawl("BV1xx411c7mD")

        self.assertTrue(store.in_persist.wait(timeout=5))
        service.stop(started.task_id)  # lands before the crawl started
        store.gate.set()

        final = self.run_to_completion(service, started)
        self.assertEqual(final.status, RunStatus.CANCELLED)
        self.assertEqual(final.counts.get("comments"), 0)
        # The desktop contract: an empty-but-successful crawl records the
        # outcome so the UI can finish(0) instead of "result unavailable".
        outcome = service.take_outcome(started.task_id)
        self.assertIsNotNone(outcome, "no outcome recorded for a pre-cancelled desktop crawl")
        self.assertEqual(outcome.comments, [])
        run_dir = self.store.run_dir(final.run_id)
        self.assertEqual(json.loads((run_dir / "comments.json").read_text(encoding="utf-8")), [])
        self.assertFalse(final.warnings, "an empty crawl is no data, not a CSV export failure")

    def test_a_manifest_write_failure_does_not_fail_a_settled_task(self) -> None:
        class FlakyManifestStore(RunStore):
            def __init__(self, root):
                super().__init__(root)
                self.failing = False

            def write_manifest(self, run_id, manifest):
                if self.failing:
                    raise OSError("antivirus lock")
                return super().write_manifest(run_id, manifest)

        store = FlakyManifestStore(self.root)
        self.store = store
        run_id = self.seed_run()

        store.failing = True
        service = self.make_service()
        snapshot = self.run_to_completion(service, service.start_analyze(run_id))

        # The terminal status was already committed in memory; losing the
        # manifest refresh must not rewrite it to FAILED.
        self.assertEqual(snapshot.status, RunStatus.COMPLETED)
        run_dir = self.store.run_dir(run_id)
        self.assertTrue((run_dir / "analysis.json").is_file(), "data files were not written")
        self.assertTrue((run_dir / "report.md").is_file())

    def test_quote_attribution_is_not_stolen_by_a_short_reply(self) -> None:
        # "支持" is a substring of the quoted comment, but a two-character
        # reply must not win the attribution race against the real author.
        records = [
            {"content": "支持", "username": "路人甲", "like_count": 3},
            {"content": "这个视频做得真好，支持UP主继续更新", "username": "楼主", "like_count": 500},
        ]
        line = LLMAnalysisProcessor._quote_line("这个视频做得真好，支持UP主继续更新", records)
        self.assertIn("楼主", line)
        self.assertNotIn("路人甲", line)
        # An unmatched-attribution match keeps searching instead of giving up
        # on the first bare hit.
        bare = [{"content": "这个视频做得真好，支持UP主继续更新", "username": "", "like_count": 0}] + records[1:]
        line = LLMAnalysisProcessor._quote_line("这个视频做得真好，支持UP主继续更新", bare)
        self.assertIn("楼主", line)

    def test_prune_runs_skips_runs_that_are_still_running(self) -> None:
        first = self.seed_run()
        second = self.seed_run()

        removed = self.store.prune_runs(1, skip_run_ids={first})

        self.assertEqual(removed, [second])
        self.assertTrue((self.root / first).exists())
        self.assertFalse((self.root / second).exists())


if __name__ == "__main__":
    unittest.main()
