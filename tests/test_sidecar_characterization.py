"""
Behaviour baseline for the v3.3.0 sidecar migration (docs/SIDECAR_MIGRATION.md).

These tests do not describe behaviour anyone designed on purpose -- they pin
down what backend/sidecar.py does *today*, so that moving the orchestration onto
AgentService cannot change it by accident. Several of the pinned behaviours
differ from AgentService's own semantics, which is exactly why they are written
before the migration rather than after:

- an empty crawl result is a success here (finished(count=0)), not a failure;
- stopping a comment crawl still emits finished with whatever was fetched,
  because _run_comments performs no cancellation check at all;
- cancelling analysis emits cancelled and never finished;
- the crawl request's own max_pages is forwarded, with no ceiling of 50.

If a change makes one of these fail, that is a behaviour change and belongs in
its own PR with its own justification -- not in the migration.
"""
import threading
import unittest

from backend.sidecar import Sidecar, SidecarServices
from src.processor.analysis_processor import AnalysisCancelled


class RecordingSidecar(Sidecar):
    """Captures every protocol frame instead of writing it to stdout."""

    def __init__(self, services: SidecarServices | None = None) -> None:
        super().__init__(services=services)
        self.frames: list[dict] = []

    def _send(self, payload: dict) -> None:
        self.frames.append(payload)

    # -- helpers ---------------------------------------------------------
    def events(self, mode: str | None = None) -> list[str]:
        return [
            frame["event"]
            for frame in self.frames
            if frame.get("kind") == "event" and (mode is None or frame.get("mode") == mode)
        ]

    def event(self, name: str, mode: str | None = None) -> dict:
        matches = [
            frame
            for frame in self.frames
            if frame.get("kind") == "event"
            and frame.get("event") == name
            and (mode is None or frame.get("mode") == mode)
        ]
        if not matches:
            raise AssertionError(f"no {name!r} event (mode={mode!r}) in {self.events()}")
        return matches[-1]

    def has(self, name: str, mode: str | None = None) -> bool:
        return any(
            frame.get("kind") == "event"
            and frame.get("event") == name
            and (mode is None or frame.get("mode") == mode)
            for frame in self.frames
        )


COMMENT_A = {
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
}

COMMENT_B = {
    **COMMENT_A,
    "comment_id": 2,
    "root_id": 1,
    "is_reply": True,
    "username": "用户B",
    "content": "第二条评论",
    "like_count": 0,
    "reply_count": 0,
    "ip_location": "",
}


class StubCrawler:
    """Same signature as CommentCrawler.crawl_comments, and it records the call.

    stop() deliberately does *not* release the gate: the caller releases it, so
    that the frames emitted by the task.stop handler are ordered against the
    worker thread by the test rather than by the scheduler.
    """

    def __init__(self, progress, comments=None, error=None, gate=None):
        self.progress = progress
        self.comments = [] if comments is None else comments
        self.error = error
        self.gate = gate
        self.entered = threading.Event()
        self.stopped = False
        self.calls: list[dict] = []

    def stop(self):
        self.stopped = True

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append({
            "url_or_id": url_or_id,
            "include_replies": include_replies,
            "max_pages": max_pages,
            "mode": mode,
        })
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.error is not None:
            raise self.error
        return list(self.comments)


class StubAnalysisProcessor:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.calls: list[tuple] = []

    def analyze(self, comments, dynamics, params, progress=None, cancel_event=None):
        self.calls.append((list(comments), list(dynamics), dict(params)))
        if progress:
            progress("正在调用 LLM", 50)
        if self.error is not None:
            raise self.error
        return dict(self.result or {})


# analyzed_records is deliberately different from the number of comments held in
# _last_comments, so an assertion on finished.count pins where that number comes
# from. overview carries the keys the desktop stat tiles read for analysis mode.
ANALYSIS_RESULT = {
    "summary": "总体偏正面",
    "overview": {
        "total_records": 9,
        "analyzed_records": 7,
        "risk_count": 1,
        "ip_locations": 5,
        "missing_ip_locations": 4,
    },
    "report_markdown": "# 报告",
    "meta": {"analyzed_records": 7, "total_records": 9},
}


def make(comments=None, error=None, gate=None, processor=None):
    holder: dict = {}

    def factory(progress):
        holder["crawler"] = StubCrawler(progress, comments=comments, error=error, gate=gate)
        return holder["crawler"]

    services = SidecarServices(
        api=object(),
        comment_crawler_factory=factory,
        analysis_processor=processor or StubAnalysisProcessor(result=ANALYSIS_RESULT),
    )
    return RecordingSidecar(services), holder


def drain(sidecar: RecordingSidecar, timeout: float = 5.0) -> None:
    thread = sidecar._active_thread
    if thread is not None:
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise AssertionError("sidecar task thread did not finish")


class CommentCrawlBaseline(unittest.TestCase):
    def test_success_emits_stats_then_finished_then_idle(self) -> None:
        sidecar, _ = make(comments=[COMMENT_A, COMMENT_B])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        self.assertEqual(
            [event for event in sidecar.events("comments") if event != "log"],
            ["stats", "finished", "progress"],
        )

        finished = sidecar.event("finished", "comments")
        self.assertEqual(finished["count"], 2)
        self.assertEqual(finished["stats"], sidecar.event("stats", "comments")["stats"])

        idle = sidecar.event("progress", "comments")
        self.assertEqual(idle["status"], "idle")
        self.assertEqual(idle["percent"], 100)

    def test_stats_payload_carries_every_data_processor_field(self) -> None:
        # A migration that recomputes stats differently must not drop fields the
        # UI reads; assert each one rather than just `total`.
        sidecar, _ = make(comments=[COMMENT_A, COMMENT_B])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        stats = sidecar.event("stats", "comments")["stats"]
        self.assertEqual(
            sorted(stats),
            sorted([
                "total", "main_comments", "replies", "total_likes", "avg_likes",
                "total_replies", "ip_locations", "missing_ip_locations",
                "ip_location_coverage",
            ]),
        )
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["main_comments"], 1)
        self.assertEqual(stats["replies"], 1)
        self.assertEqual(stats["ip_locations"], 1)
        self.assertEqual(stats["missing_ip_locations"], 1)

    def test_empty_result_is_a_success_not_an_error(self) -> None:
        # AgentService raises CRAWL_FAILED here. The desktop path does not.
        sidecar, _ = make(comments=[])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        self.assertFalse(sidecar.has("error", "comments"))
        finished = sidecar.event("finished", "comments")
        self.assertEqual(finished["count"], 0)
        self.assertEqual(finished["stats"]["total"], 0)
        self.assertEqual(sidecar.event("progress", "comments")["status"], "idle")

    def test_failure_emits_error_without_finished_but_still_goes_idle(self) -> None:
        sidecar, _ = make(error=RuntimeError("接口返回 412"))
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        self.assertFalse(sidecar.has("finished", "comments"))
        error = sidecar.event("error", "comments")
        self.assertEqual(error["mode"], "comments")
        self.assertIn("412", error["message"])
        self.assertEqual(sidecar.event("progress", "comments")["status"], "idle")

    def test_comment_context_is_recorded_for_asset_naming(self) -> None:
        sidecar, _ = make(comments=[COMMENT_A])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        self.assertEqual(sidecar._last_comment_context.get("label"), "视频评论")
        self.assertEqual(sidecar._last_comment_context.get("bvid"), "BV1xx411c7mD")

    def test_request_params_reach_the_crawler_verbatim(self) -> None:
        # Conflicts 1 and 2: AgentService clamps max_pages to its own ceiling of
        # 50 and decides the rest itself. The desktop path forwards whatever the
        # UI sent, and renames sort_mode to the crawler's mode.
        sidecar, holder = make(comments=[COMMENT_A])
        sidecar._run_comments({
            "input": "BV1xx411c7mD",
            "max_pages": 80,
            "include_replies": False,
            "sort_mode": 2,
        })

        self.assertEqual(holder["crawler"].calls, [{
            "url_or_id": "BV1xx411c7mD",
            "include_replies": False,
            "max_pages": 80,
            "mode": 2,
        }])

    def test_absent_params_fall_back_to_the_desktop_defaults(self) -> None:
        # 100 pages, not AgentService's MAX_PAGES_CEILING.
        sidecar, holder = make(comments=[COMMENT_A])
        sidecar._run_comments({"input": "BV1xx411c7mD"})

        self.assertEqual(holder["crawler"].calls, [{
            "url_or_id": "BV1xx411c7mD",
            "include_replies": True,
            "max_pages": 100,
            "mode": 3,
        }])


class CommentStopBaseline(unittest.TestCase):
    def test_stopping_a_crawl_still_finishes_with_the_partial_data(self) -> None:
        # _run_comments has no cancellation check: crawler.stop() only makes the
        # crawler return early, and the handler carries on to finished(). This
        # finished frame is legitimate, not a stale one -- see conflict 9 in
        # docs/SIDECAR_MIGRATION.md.
        gate = threading.Event()
        sidecar, holder = make(comments=[COMMENT_A], gate=gate)

        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        self.assertTrue(holder["crawler"].entered.wait(timeout=5))

        # task.stop emits its frames on the calling thread, so the crawler is
        # released only afterwards: "stopping" then precedes "idle" because the
        # test ordered them, not because it won a race against the worker.
        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        self.assertTrue(holder["crawler"].stopped)
        gate.set()
        drain(sidecar)

        self.assertTrue(sidecar.has("finished", "comments"),
                        "stopping a comment crawl still emits finished today")
        self.assertEqual(sidecar.event("finished", "comments")["count"], 1)

        statuses = [frame["status"] for frame in sidecar.frames
                    if frame.get("event") == "progress" and frame.get("mode") == "comments"]
        self.assertIn("stopping", statuses)
        self.assertEqual(statuses[-1], "idle")

    def test_stop_reports_the_crawler_wording_not_the_analysis_wording(self) -> None:
        gate = threading.Event()
        sidecar, holder = make(comments=[COMMENT_A], gate=gate)
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        self.assertTrue(holder["crawler"].entered.wait(timeout=5))

        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        gate.set()
        drain(sidecar)

        logs = [frame["message"] for frame in sidecar.frames if frame.get("event") == "log"]
        self.assertIn("正在停止爬取任务...", logs)
        self.assertNotIn("正在停止分析任务...", logs)


class AnalysisBaseline(unittest.TestCase):
    def test_success_emits_finished_with_the_display_payload(self) -> None:
        processor = StubAnalysisProcessor(result=ANALYSIS_RESULT)
        sidecar, _ = make(processor=processor)
        sidecar._last_comments = [COMMENT_A, COMMENT_B]

        sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "k"}})

        finished = sidecar.event("finished", "analysis")
        # count is meta.analyzed_records, not how many comments were held: the
        # two differ here so that a migration cannot swap one for the other.
        self.assertEqual(len(sidecar._last_comments), 2)
        self.assertEqual(finished["count"], 7)
        # The RPC payload is the compact display shape, not the raw result.
        self.assertEqual(finished["result"]["report_markdown"], "")
        self.assertEqual(finished["result"]["summary"], "总体偏正面")
        # ...while the raw result stays in memory for analysis.export.
        self.assertEqual(sidecar._last_analysis["report_markdown"], "# 报告")
        self.assertEqual(sidecar.event("progress", "analysis")["status"], "idle")

    def test_finished_stats_carry_the_overview_fields_the_ui_reads(self) -> None:
        # The analysis stat tiles read total_records / analyzed_records /
        # risk_count / ip_locations / missing_ip_locations off statsByMode
        # (desktop/src/App.tsx), fed by both finished.stats and
        # finished.result.overview. Conflict 6 -- RunStore.save_analysis
        # reshapes the stored result -- is exactly how these could drift.
        expected = {
            "total_records": 9,
            "analyzed_records": 7,
            "risk_count": 1,
            "ip_locations": 5,
            "missing_ip_locations": 4,
        }
        sidecar, _ = make(processor=StubAnalysisProcessor(result=ANALYSIS_RESULT))
        sidecar._last_comments = [COMMENT_A, COMMENT_B]

        sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "k"}})

        finished = sidecar.event("finished", "analysis")
        self.assertEqual(finished["stats"], expected)
        self.assertEqual(finished["result"]["overview"], expected)
        self.assertEqual(finished["result"]["meta"], {"analyzed_records": 7, "total_records": 9})

    def test_progress_percentages_are_forwarded_unscaled(self) -> None:
        # AgentService rescales analysis progress into 70-95; the desktop
        # contract is the processor's own 0-100.
        sidecar, _ = make()
        sidecar._last_comments = [COMMENT_A]
        sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "k"}})

        percents = [frame["percent"] for frame in sidecar.frames
                    if frame.get("event") == "analysis.progress"]
        self.assertEqual(percents, [50])

    def test_cancel_emits_cancelled_and_never_finished(self) -> None:
        processor = StubAnalysisProcessor(error=AnalysisCancelled("分析已被取消"))
        sidecar, _ = make(processor=processor)
        sidecar._last_comments = [COMMENT_A]

        sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "k"}})

        self.assertFalse(sidecar.has("finished", "analysis"))
        self.assertFalse(sidecar.has("error", "analysis"))
        self.assertEqual(sidecar.event("cancelled", "analysis")["mode"], "analysis")
        logs = [frame["message"] for frame in sidecar.frames if frame.get("event") == "log"]
        self.assertIn("分析任务已取消", logs)
        self.assertEqual(sidecar.event("progress", "analysis")["status"], "idle")

    def test_every_source_reaches_the_processor_with_both_datasets(self) -> None:
        # Source routing lives inside the processor, so the sidecar contract is
        # simply that it hands over both datasets plus the params untouched.
        # The migration must keep dynamics and all on this path.
        for source in ("comments", "dynamics", "all"):
            with self.subTest(source=source):
                processor = StubAnalysisProcessor(result=ANALYSIS_RESULT)
                sidecar, _ = make(processor=processor)
                sidecar._last_comments = [COMMENT_A]
                sidecar._last_dynamics = [{"dynamic_id": "d1", "content": "一条动态"}]

                sidecar._run_analysis({"source": source, "llm_config": {"api_key": "k"}})

                comments, dynamics, params = processor.calls[0]
                self.assertEqual(len(comments), 1)
                self.assertEqual(len(dynamics), 1)
                self.assertEqual(params["source"], source)

    def test_analysis_params_are_passed_through_verbatim(self) -> None:
        processor = StubAnalysisProcessor(result=ANALYSIS_RESULT)
        sidecar, _ = make(processor=processor)
        sidecar._last_comments = [COMMENT_A]

        sent = {
            "source": "comments",
            "sample_size": 123,
            "batch_size": 45,
            "chart_keys": ["word_cloud", "topic_ranking"],
            "llm_config": {"api_key": "k", "base_url": "https://x/v1", "model": "m"},
        }
        sidecar._run_analysis(dict(sent))

        _, _, params = processor.calls[0]
        for key, value in sent.items():
            self.assertEqual(params[key], value, f"{key} was not passed through")


if __name__ == "__main__":
    unittest.main()
