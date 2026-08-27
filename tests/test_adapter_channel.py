"""
Stage 3 of docs/SIDECAR_MIGRATION.md: the adapter-only outcome / event channel.

Conflicts 6 and 7 in that document are structural, not wiring details.
AgentService has no way to hand anyone the analysis result the processor
actually returned -- RunStore.save_analysis lifts the report out into its own
file and rewrites the word cloud into a path -- and it folds the processor's
0-100 progress into a 70-95 band that cannot be inverted. Until both are fixed,
the desktop's `analysis.latest`, its word cloud and its `analysis.export`
cannot survive stage 5.

So this pins two things: that the channel carries what those three depend on,
and that it is invisible to everyone who does not ask for it. TaskSnapshot
stays compact, the progress queue is byte-identical, and a service built
without the new arguments retains nothing.

No wiring yet -- backend/sidecar.py is untouched at this stage.
"""
import base64
import copy
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

from src.processor.analysis_processor import AnalysisCancelled
from src.processor.data_processor import DataProcessor
from src.service.agent_service import AgentService
from src.service.credentials import LLMCredentials
from src.service.models import EventKind, RunStatus, TaskEvent
from src.service.run_store import RunStore

SECRET_KEY = "sk-CHANNEL-CANARY-abcdef"

# Plain ASCII rather than real PNG bytes: the store only checks the data URL
# prefix and that the payload decodes, and a binary literal in a test file is
# one bad round-trip away from being silently corrupted.
WORD_CLOUD_BYTES = b"stage-three-word-cloud-bytes"
WORD_CLOUD_DATA_URL = "data:image/png;base64," + base64.b64encode(WORD_CLOUD_BYTES).decode("ascii")

# Long enough that nobody can mistake it for the summary field.
REPORT_MARKDOWN = "# 分析报告\n\n" + ("这是报告正文，会被 RunStore 拆到单独文件里。\n" * 60)

COMMENT = {
    "comment_id": 1,
    "is_reply": False,
    "username": "用户A",
    "user_level": 5,
    "content": "一条主评论",
    "like_count": 3,
    "reply_count": 1,
    "ctime": 1735660800,
    "ctime_text": "2025-01-01 00:00:00",
    "ip_location": "广东",
}

REPLY = {
    "comment_id": 2,
    "is_reply": True,
    "username": "用户B",
    "user_level": 2,
    "content": "一条回复",
    "like_count": 0,
    "reply_count": 0,
    "ctime": 1735660900,
    "ctime_text": "2025-01-01 00:01:40",
    "ip_location": "",
}


class TalkativeCrawler:
    """A crawler that speaks, because the desktop reads what it says.

    The sidecar's progress callback parses its own page number out of these
    lines, so they have to arrive as written rather than as a percentage.
    """

    LINES = ("开始爬取评论", "正在爬取第 3 页", "爬取完成")

    def __init__(self, progress):
        self.progress = progress
        self.calls: list[dict] = []

    def stop(self):
        # CommentCrawler.stop() logs "正在停止爬取..." and that line reaches the
        # service's progress callback like any other. A stub that only flipped a
        # boolean would let a dropped frame pass unnoticed.
        self.progress("正在停止爬取...")

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append({"max_pages": max_pages, "mode": mode})
        for line in self.LINES:
            self.progress(line)
        return [dict(COMMENT), dict(REPLY)]


class BlockingCrawler(TalkativeCrawler):
    """Holds the crawl open until it is stopped, then returns its partial page."""

    def __init__(self, progress):
        super().__init__(progress)
        self.reached = threading.Event()
        self.stopped = threading.Event()

    def stop(self):
        super().stop()
        self.stopped.set()

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append({"max_pages": max_pages, "mode": mode})
        self.progress("正在爬取第 1 页")
        self.reached.set()
        self.stopped.wait(timeout=5)
        # A stopped crawler still returns the pages it managed to fetch.
        return [dict(COMMENT)]


class ExplodingCrawler(TalkativeCrawler):
    """Dies before producing anything, so its task records no outcome at all."""

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        raise RuntimeError("网络断了")


class RichProcessor:
    """Returns everything the desktop renders, not just what the agent keeps.

    A stub returning only `summary` would let the outcome channel look correct
    while carrying nothing the store would have taken away.
    """

    STEPS = (("准备分析", 0), ("正在调用模型", 50), ("分析完成", 100))

    def __init__(self):
        self.params: list[dict] = []
        # A pristine record of what was handed back, so a test can compare
        # against it even after something downstream has edited the original.
        self.returned: list[dict] = []

    def build_result(self, comments):
        return {
            "summary": "总体正面",
            "report_markdown": REPORT_MARKDOWN,
            "word_cloud_image": WORD_CLOUD_DATA_URL,
            # Nested on purpose: a shallow copy would leave these shared with
            # whoever gets the result next.
            "overview": {"total": len(comments), "keep_me": "处理器写的值"},
            "topic_counts": [{"name": "话题一", "value": 7}],
            "meta": {"analyzed_records": len(comments), "total_records": len(comments)},
        }

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.params.append(dict(params))
        for message, percent in self.STEPS:
            if progress is not None:
                progress(message, percent)
        result = self.build_result(comments)
        self.returned.append(copy.deepcopy(result))
        return result


class PausingProcessor(RichProcessor):
    """Holds the analysis open so a test can act between the two halves."""

    def __init__(self):
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.entered.set()
        self.release.wait(timeout=5)
        return super().analyze(comments, dynamics, params, progress, cancel_event)


class EchoingProcessor(RichProcessor):
    """Puts its own configuration into the result, the way some processors do."""

    def build_result(self, comments):
        result = super().build_result(comments)
        result["meta"]["config"] = dict(self.params[-1])
        return result


class BlockingProcessor:
    """Waits to be cancelled, the way a processor stuck on an LLM call would."""

    def __init__(self):
        self.entered = threading.Event()

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.entered.set()
        if cancel_event is not None:
            cancel_event.wait(timeout=5)
        raise AnalysisCancelled("分析已被取消")


class SentinelDataProcessor:
    """Real key names, values no real run would produce."""

    SENTINEL_STATS = {
        "total": 2,
        "main_comments": 41,
        "replies": 42,
        "total_likes": 4300,
        "avg_likes": 44.5,
        "total_replies": 46,
        "ip_locations": 47,
        "missing_ip_locations": 48,
        "ip_location_coverage": 0.49,
    }

    @staticmethod
    def clean_comments(comments):
        return DataProcessor.clean_comments(comments)

    @classmethod
    def get_statistics(cls, comments):
        return dict(cls.SENTINEL_STATS)


class StrictDataProcessor:
    """Rejects an empty list, the way a stricter processor reasonably might."""

    @staticmethod
    def clean_comments(comments):
        return DataProcessor.clean_comments(comments)

    @staticmethod
    def get_statistics(comments):
        if not comments:
            raise ValueError("没有评论可统计")
        return DataProcessor.get_statistics(comments)


class CountingDataProcessor:
    """Counts how often each half is called."""

    def __init__(self):
        self.calls: list[str] = []

    def clean_comments(self, comments):
        self.calls.append("clean_comments")
        return DataProcessor.clean_comments(comments)

    def get_statistics(self, comments):
        self.calls.append("get_statistics")
        return DataProcessor.get_statistics(comments)


class EmptyBlockingCrawler(TalkativeCrawler):
    """Stopped before its first page, so it has nothing at all to return."""

    def __init__(self, progress):
        super().__init__(progress)
        self.reached = threading.Event()
        self.stopped = threading.Event()

    def stop(self):
        super().stop()
        self.stopped.set()

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.reached.set()
        self.stopped.wait(timeout=5)
        return []


class RewritingStore(RunStore):
    """A store that edits the result in place instead of copying it first.

    RunStore.save_analysis happens to shallow-copy today, which means recording
    the outcome afterwards would look just as correct. That is luck, not a
    contract -- dropping the copy is an obvious way to save a dict allocation on
    a large result -- so the ordering gets a store that does exactly that.
    """

    def save_analysis(self, run_id, result):
        result.pop("report_markdown", None)
        result["word_cloud_image"] = "already/rewritten/word_cloud.png"
        # Nested, where a shallow copy offers no protection at all.
        if isinstance(result.get("overview"), dict):
            result["overview"]["keep_me"] = "store 改掉的值"
        if isinstance(result.get("topic_counts"), list):
            result["topic_counts"].clear()
        return super().save_analysis(run_id, result)

    def save_comments(self, run_id, comments):
        # Same question for the crawl half: the outcome holds comment dicts that
        # the store is handed straight afterwards.
        for comment in comments:
            comment["content"] = "store 改掉的正文"
        return super().save_comments(run_id, comments)


class BlockingTerminalStore(RunStore):
    """Hold the worker after its snapshot becomes terminal."""

    def __init__(self, root):
        super().__init__(root)
        self.terminal_persist_started = threading.Event()
        self.release_terminal_persist = threading.Event()

    def update_manifest(self, run_id, **changes):
        if changes.get("status") in RunStatus.TERMINAL:
            self.terminal_persist_started.set()
            if not self.release_terminal_persist.wait(timeout=5):
                raise TimeoutError("terminal manifest write was never released")
        return super().update_manifest(run_id, **changes)


class ChannelTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.store = RunStore(Path(self._tmp.name))
        self.crawlers: list[TalkativeCrawler] = []
        # The crawler is built inside the worker thread, so a test that wants to
        # stop it mid-run has to wait for it to exist rather than race it.
        self.crawler_built = threading.Event()
        self.services: list[AgentService] = []
        self.events: list[TaskEvent] = []
        self.addCleanup(self._drain)

    def _drain(self) -> None:
        # Ask first, then join, then insist: a thread still running when the
        # TemporaryDirectory is destroyed races the next test through a
        # directory that no longer exists.
        stragglers = []
        for service in self.services:
            for task in list(service._tasks.values()):
                if task.thread is None or not task.thread.is_alive():
                    continue
                try:
                    service.stop(task.task_id)
                except Exception:  # noqa: BLE001 - cleanup must not mask failures
                    pass
                task.thread.join(timeout=5)
                if task.thread.is_alive():
                    stragglers.append(task.task_id)
        assert not stragglers, f'tasks still running at teardown: {stragglers}'

    def make(
        self,
        processor=None,
        crawler_class=TalkativeCrawler,
        data_processor=None,
        listen=False,
        retain_outcome=True,
        events=None,
        store=None,
    ) -> AgentService:
        self.crawler_class = crawler_class

        def factory(progress):
            crawler = self.crawler_class(progress)
            self.crawlers.append(crawler)
            self.crawler_built.set()
            return crawler

        if events is None and listen:
            events = self.events.append

        kwargs = dict(
            store=store if store is not None else self.store,
            api=object(),
            crawler_factory=factory,
            analysis_processor=processor if processor is not None else RichProcessor(),
            credentials_resolver=lambda: LLMCredentials(api_key=SECRET_KEY),
            events=events,
            retain_outcome=retain_outcome,
        )
        if data_processor is not None:
            kwargs["data_processor"] = data_processor
        service = AgentService(**kwargs)
        self.services.append(service)
        return service

    def finish(self, service, snapshot):
        final = service.wait(snapshot.task_id, 5)
        self.assertTrue(final.done, f"{final.status}: {final.error}")
        return final

    def crawl_then_analyze(self, service):
        """Two separate tasks, so the analysis events arrive on their own."""
        crawl = self.finish(service, service.start_crawl("BV1xx411c7mD"))
        service.take_outcome(crawl.task_id)
        self.events.clear()
        return self.finish(service, service.start_analyze(crawl.run_id))


class OutcomeCarriesWhatTheSnapshotDropsTests(ChannelTestCase):
    def test_the_analysis_outcome_is_the_processors_untouched_return(self) -> None:
        service = self.make()
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertIsNotNone(outcome)
        self.assertEqual(outcome.analysis["report_markdown"], REPORT_MARKDOWN)
        self.assertEqual(outcome.analysis["word_cloud_image"], WORD_CLOUD_DATA_URL)

        # And this is what the outcome exists for: on disk the store has already
        # taken both away, so anything reading analysis.json back gets neither.
        stored = json.loads(Path(final.artifacts["analysis_json"]).read_text(encoding="utf-8"))
        self.assertNotIn("report_markdown", stored)
        self.assertNotEqual(stored["word_cloud_image"], WORD_CLOUD_DATA_URL)
        self.assertTrue(stored["word_cloud_image"].endswith("word_cloud.png"))

    def test_the_outcome_survives_a_store_that_rewrites_in_place(self) -> None:
        service = self.make(store=RewritingStore(Path(self._tmp.name)))
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(outcome.analysis["report_markdown"], REPORT_MARKDOWN)
        self.assertEqual(outcome.analysis["word_cloud_image"], WORD_CLOUD_DATA_URL)
        # Nested values too: a shallow copy leaves these shared with the store.
        self.assertEqual(outcome.analysis["overview"]["keep_me"], "处理器写的值")
        self.assertEqual(outcome.analysis["topic_counts"], [{"name": "话题一", "value": 7}])
        # And the same for the comment dicts on the crawl half.
        self.assertEqual([c["content"] for c in outcome.comments], ["一条主评论", "一条回复"])

    def test_the_outcome_is_exactly_what_the_processor_returned(self) -> None:
        # Both directions of the hand-off in one assertion: the service merges
        # nothing of its own in (its params, which hold the key, are right
        # there) and takes nothing out.
        processor = EchoingProcessor()
        service = self.make(processor=processor)
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(outcome.analysis, processor.returned[0])

    def test_the_snapshot_still_carries_neither(self) -> None:
        # The MCP return value must not grow a megabyte of base64 or the whole
        # report just because the desktop needs them.
        service = self.make()
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        blob = json.dumps(final.to_dict(), ensure_ascii=False)
        self.assertNotIn(WORD_CLOUD_DATA_URL, blob)
        self.assertNotIn(REPORT_MARKDOWN, blob)
        self.assertEqual(final.summary, "总体正面")

    def test_the_outcome_carries_every_statistics_field_not_just_the_counted_three(self) -> None:
        service = self.make()
        final = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(outcome.stats, DataProcessor.get_statistics([dict(COMMENT), dict(REPLY)]))
        # TaskSnapshot.counts has room for three of those nine numbers.
        self.assertEqual(set(final.counts), {"comments", "main_comments", "replies"})

    def test_the_statistics_are_the_processors_own_not_a_recomputation(self) -> None:
        # Values no real run would produce for two comments, so a recompute
        # anywhere between here and the outcome shows up as a mismatch.
        service = self.make(data_processor=SentinelDataProcessor)
        final = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(outcome.stats, SentinelDataProcessor.SENTINEL_STATS)

    def test_the_outcome_carries_the_cleaned_comments(self) -> None:
        service = self.make()
        final = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual([c["content"] for c in outcome.comments], ["一条主评论", "一条回复"])
        # Cleaned, not raw: clean_comments backfills the fields the exporter needs.
        self.assertIn("root_id", outcome.comments[0])

    def test_a_combined_run_folds_both_stages_into_one_outcome(self) -> None:
        service = self.make()
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(len(outcome.comments), 2)
        self.assertEqual(outcome.stats["total"], 2)
        self.assertEqual(outcome.analysis["summary"], "总体正面")
        self.assertEqual(outcome.run_id, final.run_id)

    def test_a_stopped_crawl_still_yields_the_page_it_managed_to_fetch(self) -> None:
        service = self.make(crawler_class=BlockingCrawler)
        snapshot = service.start_crawl("BV1xx411c7mD")
        self.assertTrue(self.crawler_built.wait(timeout=5))
        self.assertTrue(self.crawlers[0].reached.wait(timeout=5))
        service.stop(snapshot.task_id)
        final = service.wait(snapshot.task_id, 5)
        self.assertTrue(final.done)

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(len(outcome.comments), 1)
        self.assertEqual(outcome.stats["total"], 1)

    def test_a_cancelled_analysis_leaves_the_crawl_half_and_no_analysis(self) -> None:
        processor = BlockingProcessor()
        service = self.make(processor=processor)
        snapshot = service.start_crawl_and_analyze("BV1xx411c7mD")
        self.assertTrue(processor.entered.wait(timeout=5))
        service.stop(snapshot.task_id)
        final = service.wait(snapshot.task_id, 5)
        self.assertTrue(final.done)

        outcome = service.take_outcome(final.task_id)
        self.assertEqual(len(outcome.comments), 2)
        self.assertIsNone(outcome.analysis)


class OwnershipTests(ChannelTestCase):
    def test_the_outcome_is_handed_over_only_once(self) -> None:
        # The desktop annotates the result it gets back with its own asset
        # context. Handing the same dict to two owners is how that annotation
        # would end up in the service's copy as well.
        service = self.make()
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        taken = service.take_outcome(final.task_id)
        self.assertIsNotNone(taken)
        taken.analysis["_asset_context"] = {"label": "视频评论"}

        self.assertIsNone(service.take_outcome(final.task_id))
        self.assertIsNone(service._outcome)

    def test_the_outcome_cannot_be_taken_while_the_task_is_still_running(self) -> None:
        # A crawl-and-analyse task records its two halves at different moments.
        # An early take would hand over the crawl half and leave the analysis
        # half behind to be taken as a second outcome: one task consumed twice,
        # neither time whole.
        processor = PausingProcessor()
        service = self.make(processor=processor)
        snapshot = service.start_crawl_and_analyze("BV1xx411c7mD")
        self.assertTrue(processor.entered.wait(timeout=5))

        self.assertIsNone(service.take_outcome(snapshot.task_id))

        processor.release.set()
        final = self.finish(service, snapshot)

        # Nothing was consumed early, so what arrives now is whole.
        outcome = service.take_outcome(final.task_id)
        self.assertEqual(len(outcome.comments), 2)
        self.assertTrue(outcome.stats)
        self.assertIsNotNone(outcome.analysis)
        self.assertIsNone(service.take_outcome(final.task_id))

    def test_terminal_snapshot_makes_the_outcome_available_before_worker_exit(self) -> None:
        store = BlockingTerminalStore(Path(self._tmp.name))
        self.addCleanup(store.release_terminal_persist.set)
        service = self.make(store=store)
        started = service.start_crawl_and_analyze("BV1xx411c7mD")

        self.assertTrue(store.terminal_persist_started.wait(timeout=5))
        terminal = service.get_status(task_id=started.task_id)
        self.assertTrue(terminal.done)

        outcome = service.take_outcome(started.task_id)
        self.assertIsNotNone(outcome)
        self.assertIsNotNone(outcome.analysis)

        store.release_terminal_persist.set()
        self.finish(service, started)
        self.assertIsNone(service.take_outcome(started.task_id))

    def test_an_unknown_task_id_yields_nothing(self) -> None:
        service = self.make()
        self.finish(service, service.start_crawl("BV1xx411c7mD"))
        self.assertIsNone(service.take_outcome("task-never-existed"))

    def test_a_new_task_drops_the_previous_outcome(self) -> None:
        # _tasks never shrinks, so an outcome per task would grow with every run.
        service = self.make()
        first = self.finish(service, service.start_crawl("BV1xx411c7mD"))
        second = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        self.assertIsNone(service.take_outcome(first.task_id))
        self.assertIsNotNone(service.take_outcome(second.task_id))

    def test_a_task_that_dies_early_still_drops_the_previous_outcome(self) -> None:
        # The clear happens when a task starts, not when it records. A task that
        # dies before its first result records nothing, and without the clear the
        # previous run's comments would still be sitting there under the previous
        # task_id -- handed to an adapter that asked about this run.
        service = self.make()
        first = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        self.crawler_class = ExplodingCrawler
        second = service.start_crawl("BV1xx411c7mD")
        self.assertEqual(service.wait(second.task_id, 5).status, "failed")

        self.assertIsNone(service.take_outcome(first.task_id))
        self.assertIsNone(service.take_outcome(second.task_id))

    def test_without_retain_outcome_the_service_holds_nothing(self) -> None:
        service = self.make(retain_outcome=False)
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        self.assertIsNone(service.take_outcome(final.task_id))
        self.assertIsNone(service._outcome)

    def test_retention_is_off_by_default(self) -> None:
        # The MCP server and the CLI construct the service without either new
        # argument, and must keep paying nothing for a channel they never read.
        service = AgentService(
            store=self.store,
            api=object(),
            crawler_factory=lambda progress: TalkativeCrawler(progress),
            analysis_processor=RichProcessor(),
            credentials_resolver=lambda: LLMCredentials(api_key=SECRET_KEY),
        )
        self.services.append(service)
        final = self.finish(service, service.start_crawl("BV1xx411c7mD"))

        self.assertIsNone(service.take_outcome(final.task_id))

    def test_retention_off_does_not_deepcopy_results(self) -> None:
        service = self.make(retain_outcome=False)
        poisoned_copy = mock.Mock()
        poisoned_copy.deepcopy.side_effect = AssertionError("retention-off path copied an outcome")

        with mock.patch("src.service.agent_service.copy", poisoned_copy):
            final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        self.assertEqual(final.status, RunStatus.COMPLETED)

    def test_no_listener_does_not_construct_typed_events(self) -> None:
        service = self.make(events=None)

        with mock.patch(
            "src.service.agent_service.TaskEvent",
            side_effect=AssertionError("listener-free path constructed an event"),
        ):
            final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        self.assertEqual(final.status, RunStatus.COMPLETED)


class TheEmptyPathIsUnchangedTests(ChannelTestCase):
    def _stop_an_empty_crawl(self, service):
        snapshot = service.start_crawl("BV1xx411c7mD")
        self.assertTrue(self.crawler_built.wait(timeout=5))
        self.assertTrue(self.crawlers[0].reached.wait(timeout=5))
        service.stop(snapshot.task_id)
        return service.wait(snapshot.task_id, 5)

    def test_an_empty_stopped_crawl_is_still_cancelled_not_failed(self) -> None:
        # The data processor is an injection point. Asking it to describe an
        # empty list is a question it never used to be asked, and one that
        # raises turns a stopped crawl into a failed one.
        service = self.make(crawler_class=EmptyBlockingCrawler,
                            data_processor=StrictDataProcessor)
        final = self._stop_an_empty_crawl(service)

        self.assertEqual(final.status, "cancelled")
        self.assertIsNone(final.error)

    def test_the_data_processor_is_not_asked_about_an_empty_result(self) -> None:
        counting = CountingDataProcessor()
        service = self.make(crawler_class=EmptyBlockingCrawler, data_processor=counting)
        self._stop_an_empty_crawl(service)

        self.assertEqual(counting.calls, ["clean_comments"])

    def test_an_empty_stopped_crawl_hands_over_no_outcome(self) -> None:
        # Nothing was crawled, so there is nothing to hand over. Deciding what
        # an empty stats frame should look like belongs to the adapter.
        service = self.make(crawler_class=EmptyBlockingCrawler)
        final = self._stop_an_empty_crawl(service)

        self.assertIsNone(service.take_outcome(final.task_id))


class RawProgressTests(ChannelTestCase):
    def test_analysis_progress_reaches_the_listener_unremapped(self) -> None:
        service = self.make(listen=True)
        final = self.crawl_then_analyze(service)

        seen = [(e.message, e.percent) for e in self.events
                if e.kind == EventKind.ANALYSIS_PROGRESS]
        self.assertEqual(seen, [("准备分析", 0), ("正在调用模型", 50), ("分析完成", 100)])

        # The queue the MCP client polls keeps the squeezed numbers, which is
        # exactly why the raw ones needed a channel of their own.
        self.assertEqual(
            [(percent, message) for percent, message in service.drain_progress(final.task_id)],
            [(70, "准备分析"), (82, "正在调用模型"), (95, "分析完成")],
        )

    def test_crawl_lines_reach_the_listener_verbatim(self) -> None:
        service = self.make(listen=True)
        self.finish(service, service.start_crawl("BV1xx411c7mD"))

        self.assertEqual(
            [e.message for e in self.events if e.kind == EventKind.LOG],
            list(TalkativeCrawler.LINES),
        )

    def test_the_crawlers_own_stop_line_reaches_the_listener_too(self) -> None:
        # CommentCrawler.stop() logs, and that line is a frame the desktop shows.
        service = self.make(crawler_class=BlockingCrawler, listen=True)
        snapshot = service.start_crawl("BV1xx411c7mD")
        self.assertTrue(self.crawler_built.wait(timeout=5))
        self.assertTrue(self.crawlers[0].reached.wait(timeout=5))
        service.stop(snapshot.task_id)
        service.wait(snapshot.task_id, 5)

        self.assertEqual(
            [e.message for e in self.events if e.kind == EventKind.LOG],
            ["正在爬取第 1 页", "正在停止爬取..."],
        )

    def test_a_combined_run_keeps_the_two_kinds_apart(self) -> None:
        service = self.make(listen=True)
        self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        kinds = [e.kind for e in self.events]
        self.assertEqual(
            kinds,
            [EventKind.LOG] * 3 + [EventKind.ANALYSIS_PROGRESS] * 3,
        )
        # Only the analysis half carries a percentage; a log line's number is
        # the desktop's to derive from the text.
        self.assertTrue(all(e.percent is None for e in self.events if e.kind == EventKind.LOG))

    def test_every_event_names_its_task_and_run(self) -> None:
        service = self.make(listen=True)
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        self.assertTrue(self.events)
        self.assertEqual({e.task_id for e in self.events}, {final.task_id})
        self.assertEqual({e.run_id for e in self.events}, {final.run_id})

    def test_a_listener_that_raises_does_not_kill_the_task(self) -> None:
        # stdout can break mid-run. Losing a frame is bad; losing the crawl and
        # the analysis with it is worse.
        calls = []

        def hostile(event):
            calls.append(event)
            raise RuntimeError("listener exploded")

        service = self.make(events=hostile)
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        self.assertEqual(final.status, "completed")
        self.assertEqual(len(calls), 6)
        outcome = service.take_outcome(final.task_id)
        self.assertEqual(outcome.analysis["summary"], "总体正面")


class TheChannelIsInvisibleWithoutAListenerTests(ChannelTestCase):
    def _run(self, service):
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))
        return final, service.drain_progress(final.task_id)

    def test_attaching_a_listener_does_not_change_the_progress_queue(self) -> None:
        quiet, quiet_events = self._run(self.make(retain_outcome=False))
        loud, loud_events = self._run(self.make(listen=True))

        self.assertEqual(quiet_events, loud_events)
        self.assertTrue(self.events, "the listener under test never fired")

    def test_attaching_a_listener_does_not_change_the_snapshot(self) -> None:
        quiet, _ = self._run(self.make(retain_outcome=False))
        loud, _ = self._run(self.make(listen=True))

        volatile = {"task_id", "run_id"}
        self.assertEqual(
            {k: v for k, v in quiet.to_dict().items() if k not in volatile and k != "artifacts"},
            {k: v for k, v in loud.to_dict().items() if k not in volatile and k != "artifacts"},
        )
        self.assertEqual(sorted(quiet.artifacts), sorted(loud.artifacts))


class CredentialsStayOutOfTheChannelTests(ChannelTestCase):
    def test_no_event_carries_the_key(self) -> None:
        # Events are built from a message and a number, never from params.
        service = self.make(listen=True)
        self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        for event in self.events:
            self.assertNotIn(SECRET_KEY, json.dumps(event.__dict__, ensure_ascii=False, default=str))

    def test_the_service_puts_no_credentials_into_the_outcome(self) -> None:
        # Scoped to what the service itself controls. The outcome is a faithful
        # hand-off of the processor's result (see
        # test_the_outcome_is_exactly_what_the_processor_returned), so this
        # cannot promise anything about a processor that echoes its own config
        # back -- only that the service does not merge its params in on the way.
        service = self.make()
        final = self.finish(service, service.start_crawl_and_analyze("BV1xx411c7mD"))

        outcome = service.take_outcome(final.task_id)
        blob = json.dumps(
            {"comments": outcome.comments, "stats": outcome.stats, "analysis": outcome.analysis},
            ensure_ascii=False,
            default=str,
        )
        self.assertNotIn(SECRET_KEY, blob)


if __name__ == "__main__":
    unittest.main()
