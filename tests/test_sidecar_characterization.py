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
import base64
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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

    Two details are deliberately no kinder than the real crawler:

    - stop() does not release the gate. The caller releases it, so the frames
      emitted by the task.stop handler are ordered against the worker thread by
      the test rather than by the scheduler.
    - a stopped crawl returns only the page it had already fetched, the way
      CommentCrawler returns what it accumulated once _stop_flag is set. A stub
      that handed back the full list would make "finished carries the partial
      data" an assertion about nothing.
    """

    def __init__(self, progress, comments=None, error=None, gate=None):
        self.progress = progress
        self.comments = [] if comments is None else comments
        self.error = error
        self.gate = gate
        self.entered = threading.Event()
        self.stop_called = threading.Event()
        self.stopped = False
        self.calls: list[dict] = []
        self.fetched: list[dict] = []

    def stop(self):
        self.stopped = True
        self.stop_called.set()
        # CommentCrawler.stop() calls _log("正在停止爬取..."), which reaches the
        # sidecar's progress callback and becomes a log frame. A silent stub
        # would let the migration drop that frame unnoticed, so the stub is as
        # loud as the real thing.
        self.progress("正在停止爬取...")

    def crawl_comments(self, url_or_id, include_replies=True, max_pages=100, mode=3):
        self.calls.append({
            "url_or_id": url_or_id,
            "include_replies": include_replies,
            "max_pages": max_pages,
            "mode": mode,
        })
        self.fetched = list(self.comments[:1])  # first page, before anyone can stop us
        self.entered.set()
        if self.gate is not None:
            self.gate.wait(timeout=5)
        if self.error is not None:
            raise self.error
        if not self.stopped:
            self.fetched = list(self.comments)
        return list(self.fetched)


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


# DataProcessor.get_statistics output for the fixtures above, recorded rather
# than hand-written: an assertion on a stats dict someone guessed is worthless.
FULL_STATS = {
    "total": 2, "main_comments": 1, "replies": 1, "total_likes": 3, "avg_likes": 1.5,
    "total_replies": 1, "ip_locations": 1, "missing_ip_locations": 1,
    "ip_location_coverage": 0.5,
}

EMPTY_STATS = {
    "total": 0, "main_comments": 0, "replies": 0, "total_likes": 0, "avg_likes": 0,
    "total_replies": 0, "ip_locations": 0, "missing_ip_locations": 0,
    "ip_location_coverage": 0,
}

# Only COMMENT_A survives a stop after the first page.
PARTIAL_STATS = {
    "total": 1, "main_comments": 1, "replies": 0, "total_likes": 3, "avg_likes": 3.0,
    "total_replies": 1, "ip_locations": 1, "missing_ip_locations": 0,
    "ip_location_coverage": 1.0,
}

WORD_CLOUD_BYTES = b"characterization-word-cloud-bytes"
WORD_CLOUD_DATA_URL = "data:image/png;base64,Y2hhcmFjdGVyaXphdGlvbi13b3JkLWNsb3VkLWJ5dGVz"


def make(comments=None, error=None, gate=None, processor=None, factory_gate=None):
    holder: dict = {"created": threading.Event(), "factory_entered": threading.Event()}

    def factory(progress):
        holder["factory_entered"].set()
        if factory_gate is not None and not factory_gate.wait(timeout=5):
            raise TimeoutError("crawler factory was never released")
        # DataProcessor.clean_comments fills defaults in place, so the crawler
        # hands over copies: the fixtures above stay as written no matter which
        # tests ran first.
        holder["crawler"] = StubCrawler(
            progress,
            comments=[dict(comment) for comment in comments or []],
            error=error,
            gate=gate,
        )
        holder["created"].set()
        return holder["crawler"]

    services = SidecarServices(
        api=object(),
        comment_crawler_factory=factory,
        analysis_processor=processor or StubAnalysisProcessor(result=ANALYSIS_RESULT),
    )
    return RecordingSidecar(services), holder


def crawler_of(holder: dict, timeout: float = 5.0) -> StubCrawler:
    """Wait for the worker thread to build the crawler, then return it.

    comments.start returns as soon as the thread is spawned; the factory runs
    inside that thread. Reading holder["crawler"] straight after handle() is a
    race that raises KeyError whenever the scheduler is slow.
    """
    if not holder["created"].wait(timeout=timeout):
        raise AssertionError("crawler was never created")
    crawler = holder["crawler"]
    if not crawler.entered.wait(timeout=timeout):
        raise AssertionError("crawler never entered crawl_comments")
    return crawler


def sequence(sidecar: RecordingSidecar) -> list[tuple]:
    """Every event frame as (event, mode), logs included, in emission order."""
    return [
        (frame["event"], frame.get("mode"))
        for frame in sidecar.frames
        if frame.get("kind") == "event"
    ]


def drain(sidecar: RecordingSidecar, timeout: float = 5.0) -> None:
    thread = sidecar._active_thread
    if thread is not None:
        thread.join(timeout=timeout)
        if thread.is_alive():
            raise AssertionError("sidecar task thread did not finish")


class CommentCrawlBaseline(unittest.TestCase):
    def test_success_persists_a_run_for_followup_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as run_root, patch.dict(
            os.environ, {"BILIBILI_AGENT_RUNS_DIR": run_root}
        ):
            sidecar, _ = make(comments=[COMMENT_A, COMMENT_B])
            sidecar.handle({"id": "req-1", "method": "comments.start",
                            "params": {"input": "BV1xx411c7mD", "max_pages": 1}})
            drain(sidecar)

            run_dirs = [path for path in Path(run_root).iterdir() if path.is_dir()]
            self.assertEqual(len(run_dirs), 1)
            run_dir = run_dirs[0]
            self.assertEqual(sidecar._last_comment_run_id, run_dir.name)
            self.assertEqual(
                json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))["status"],
                "completed",
            )
            persisted = json.loads((run_dir / "comments.json").read_text(encoding="utf-8"))
            self.assertEqual([row["comment_id"] for row in persisted], [1, 2])

    def test_success_emits_stats_then_finished_then_idle(self) -> None:
        sidecar, _ = make(comments=[COMMENT_A, COMMENT_B])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        self.assertEqual(
            [event for event in sidecar.events("comments") if event != "log"],
            ["stats", "finished", "progress"],
        )

        finished = sidecar.event("finished", "comments")
        self.assertEqual(finished["count"], 2)
        # Today both frames carry the same dict; the assertion is here for the
        # migration, where the two could be recomputed independently.
        self.assertEqual(finished["stats"], sidecar.event("stats", "comments")["stats"])

        idle = sidecar.event("progress", "comments")
        self.assertEqual(idle["status"], "idle")
        self.assertEqual(idle["percent"], 100)

    def test_start_acknowledges_the_request_before_announcing_the_task(self) -> None:
        # The frames _start_task emits before the worker runs are part of the
        # contract too: the response lands first, then running(percent=0), then
        # the startup log. taskState.ts drives the button state off that order.
        sidecar, _ = make(comments=[COMMENT_A])
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 1}})
        drain(sidecar)

        self.assertEqual(sidecar.frames[0], {"kind": "response", "id": "req-1", "ok": True})
        self.assertEqual(
            [frame["event"] for frame in sidecar.frames[1:]],
            ["progress", "log", "stats", "finished", "progress"],
        )
        running = sidecar.frames[1]
        self.assertEqual(running["status"], "running")
        self.assertEqual(running["mode"], "comments")
        self.assertEqual(running["percent"], 0)
        self.assertEqual(sidecar.frames[2]["message"], "评论任务已启动")

    def test_stats_payload_carries_every_data_processor_field(self) -> None:
        # A migration that recomputes stats differently must not drop fields the
        # UI reads; assert each one rather than just `total`.
        sidecar, _ = make(comments=[COMMENT_A, COMMENT_B])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        stats = sidecar.event("stats", "comments")["stats"]
        self.assertEqual(stats, FULL_STATS)
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["main_comments"], 1)
        self.assertEqual(stats["replies"], 1)
        self.assertEqual(stats["total_likes"], 3)
        self.assertEqual(stats["avg_likes"], 1.5)
        self.assertEqual(stats["total_replies"], 1)  # counted over main comments only
        self.assertEqual(stats["ip_locations"], 1)
        self.assertEqual(stats["missing_ip_locations"], 1)
        self.assertEqual(stats["ip_location_coverage"], 0.5)

    def test_empty_result_is_a_success_not_an_error(self) -> None:
        # AgentService raises CRAWL_FAILED here. The desktop path does not.
        sidecar, _ = make(comments=[])
        sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})

        # Exact sequence: an extra frame or a reordering is a contract change.
        self.assertEqual(sequence(sidecar),
                         [("stats", "comments"), ("finished", "comments"), ("progress", "comments")])
        finished = sidecar.event("finished", "comments")
        self.assertEqual(finished["count"], 0)
        self.assertEqual(finished["stats"], EMPTY_STATS)
        self.assertEqual(sidecar.event("stats", "comments")["stats"], EMPTY_STATS)
        idle = sidecar.event("progress", "comments")
        self.assertEqual((idle["status"], idle["percent"]), ("idle", 100))

    def test_failure_emits_error_without_finished_but_still_goes_idle(self) -> None:
        sidecar, _ = make(error=RuntimeError("接口返回 412"))
        # The traceback goes to the sidecar logger, i.e. to stderr, never into
        # the protocol stream on stdout. Capturing it pins that and keeps the
        # test output clean.
        with self.assertLogs("sidecar", level="ERROR") as captured:
            sidecar._run_comments({"input": "BV1xx411c7mD", "max_pages": 1})
        self.assertIn("comments task failed", "\n".join(captured.output))

        # No stats frame on this path, and no finished -- just error then idle.
        self.assertEqual(sequence(sidecar),
                         [("error", "comments"), ("progress", "comments")])
        self.assertEqual(
            sidecar.event("error", "comments"),
            {"kind": "event", "event": "error", "mode": "comments", "message": "接口返回 412"},
        )
        idle = sidecar.event("progress", "comments")
        self.assertEqual((idle["status"], idle["percent"]), ("idle", 100))

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
    def test_stop_before_the_worker_builds_a_crawler_finishes_empty(self) -> None:
        run_root = tempfile.TemporaryDirectory()
        self.addCleanup(run_root.cleanup)
        env_patch = patch.dict(os.environ, {"BILIBILI_AGENT_RUNS_DIR": run_root.name})
        env_patch.start()
        self.addCleanup(env_patch.stop)
        worker_started = threading.Event()
        release_worker = threading.Event()
        sidecar, _ = make(comments=[COMMENT_A])
        self.addCleanup(drain, sidecar)
        self.addCleanup(release_worker.set)
        original_persist = sidecar._agent_service._persist
        first_persist = True

        def blocking_first_persist(task):
            nonlocal first_persist
            if first_persist:
                first_persist = False
                worker_started.set()
                if not release_worker.wait(timeout=5):
                    raise TimeoutError("comment worker was never released")
            return original_persist(task)

        sidecar._agent_service._persist = blocking_first_persist
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        self.assertTrue(worker_started.wait(timeout=5))

        deadline = time.monotonic() + 5
        while not sidecar._active_agent_task_id and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        self.assertTrue(sidecar._active_agent_task_id)

        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        release_worker.set()
        drain(sidecar)

        self.assertFalse(sidecar.has("error", "comments"))
        self.assertEqual(sidecar.event("finished", "comments")["count"], 0)
        self.assertEqual(sidecar.event("stats", "comments")["stats"], EMPTY_STATS)

    def test_stop_before_the_sidecar_receives_the_task_id_is_forwarded(self) -> None:
        crawl_gate = threading.Event()
        return_gate = threading.Event()
        start_returned = threading.Event()
        sidecar, holder = make(comments=[COMMENT_A, COMMENT_B], gate=crawl_gate)
        self.addCleanup(drain, sidecar)
        self.addCleanup(crawl_gate.set)
        self.addCleanup(return_gate.set)
        original_start = sidecar._agent_service.start_crawl

        def delayed_start(*args, **kwargs):
            started = original_start(*args, **kwargs)
            start_returned.set()
            if not return_gate.wait(timeout=5):
                raise TimeoutError("AgentService.start_crawl was never released")
            return started

        sidecar._agent_service.start_crawl = delayed_start
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        self.assertTrue(start_returned.wait(timeout=5))
        crawler = crawler_of(holder)

        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        return_gate.set()
        self.assertTrue(crawler.stop_called.wait(timeout=1), "pending stop was never forwarded")
        crawl_gate.set()
        drain(sidecar)

        self.assertFalse(sidecar.has("error", "comments"))
        self.assertEqual(sidecar.event("finished", "comments")["count"], 1)

    def test_stop_after_task_id_but_before_crawler_attachment_finishes_empty(self) -> None:
        factory_gate = threading.Event()
        sidecar, holder = make(comments=[COMMENT_A], factory_gate=factory_gate)
        self.addCleanup(drain, sidecar)
        self.addCleanup(factory_gate.set)
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        self.assertTrue(holder["factory_entered"].wait(timeout=5))

        deadline = time.monotonic() + 5
        while not sidecar._active_agent_task_id and time.monotonic() < deadline:
            threading.Event().wait(0.01)
        self.assertTrue(sidecar._active_agent_task_id)

        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        factory_gate.set()
        drain(sidecar)

        self.assertFalse(sidecar.has("error", "comments"))
        self.assertEqual(sidecar.event("finished", "comments")["count"], 0)
        self.assertEqual(sidecar.event("stats", "comments")["stats"], EMPTY_STATS)

    def test_idle_waits_until_agent_service_is_ready_for_the_next_task(self) -> None:
        terminal_persist_started = threading.Event()
        release_terminal_persist = threading.Event()
        sidecar, _ = make(comments=[COMMENT_A])
        self.addCleanup(drain, sidecar)
        self.addCleanup(release_terminal_persist.set)
        original_persist = sidecar._agent_service._persist

        def blocking_persist(task):
            if task.snapshot().done:
                terminal_persist_started.set()
                if not release_terminal_persist.wait(timeout=5):
                    raise TimeoutError("terminal persist was never released")
            return original_persist(task)

        sidecar._agent_service._persist = blocking_persist
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 1}})
        self.assertTrue(terminal_persist_started.wait(timeout=5))

        sidecar._active_thread.join(timeout=0.3)
        self.assertTrue(sidecar._active_thread.is_alive(), "sidecar announced idle too early")
        self.assertFalse(sidecar.has("progress", "comments") and any(
            frame.get("status") == "idle" for frame in sidecar.frames
        ))

        release_terminal_persist.set()
        drain(sidecar)

    def test_stopping_a_crawl_still_finishes_with_the_partial_data(self) -> None:
        # _run_comments has no cancellation check: crawler.stop() only makes the
        # crawler return early, and the handler carries on to finished(). This
        # finished frame is legitimate, not a stale one -- see conflict 9 in
        # docs/SIDECAR_MIGRATION.md.
        gate = threading.Event()
        # Two comments are on offer but the crawler is stopped after the first
        # page, so finished carries one of them: partial, and still finished.
        sidecar, holder = make(comments=[COMMENT_A, COMMENT_B], gate=gate)

        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        crawler = crawler_of(holder)

        # task.stop emits its frames on the calling thread, so the crawler is
        # released only afterwards: "stopping" then precedes "idle" because the
        # test ordered them, not because it won a race against the worker.
        sidecar.handle({"id": "req-2", "method": "task.stop", "params": {}})
        self.assertTrue(crawler.stopped)
        # Stopping a crawl must not arm the analysis cancel flag (v3.1.1).
        self.assertFalse(sidecar._analysis_cancel.is_set())
        gate.set()
        drain(sidecar)

        self.assertTrue(sidecar.has("finished", "comments"),
                        "stopping a comment crawl still emits finished today")
        finished = sidecar.event("finished", "comments")
        self.assertEqual(finished["count"], 1)
        self.assertEqual(finished["stats"], PARTIAL_STATS)
        self.assertEqual(sidecar.event("stats", "comments")["stats"], PARTIAL_STATS)
        self.assertEqual([row["comment_id"] for row in sidecar._last_comments], [1])

        # Full sequence, both threads: start frames, the stop frames emitted on
        # the calling thread, then the worker finishing normally.
        self.assertEqual(sequence(sidecar), [
            ("progress", "comments"),   # running, 0
            ("log", None),              # 评论任务已启动
            ("log", None),              # 正在停止爬取...      (from crawler.stop)
            ("log", None),              # 正在停止爬取任务...  (from the task.stop handler)
            ("progress", "comments"),   # stopping, 0
            ("stats", "comments"),
            ("finished", "comments"),
            ("progress", "comments"),   # idle, 100
        ])
        self.assertEqual(
            [frame["message"] for frame in sidecar.frames if frame.get("event") == "log"],
            ["评论任务已启动", "正在停止爬取...", "正在停止爬取任务..."],
        )
        progress_frames = [frame for frame in sidecar.frames
                           if frame.get("event") == "progress" and frame.get("mode") == "comments"]
        self.assertEqual(
            [(frame["status"], frame["percent"]) for frame in progress_frames],
            [("running", 0), ("stopping", 0), ("idle", 100)],
        )

    def test_stop_reports_the_crawler_wording_not_the_analysis_wording(self) -> None:
        gate = threading.Event()
        sidecar, holder = make(comments=[COMMENT_A], gate=gate)
        sidecar.handle({"id": "req-1", "method": "comments.start",
                        "params": {"input": "BV1xx411c7mD", "max_pages": 5}})
        crawler_of(holder)

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

        # cancelled -> log -> idle, in that order, and nothing else after.
        self.assertEqual(sequence(sidecar), [
            ("analysis.progress", None),
            ("cancelled", "analysis"),
            ("log", None),
            ("progress", "analysis"),
        ])
        self.assertEqual(
            sidecar.event("analysis.progress"),
            {"kind": "event", "event": "analysis.progress", "message": "正在调用 LLM", "percent": 50},
        )
        self.assertEqual(
            sidecar.event("cancelled", "analysis"),
            {"kind": "event", "event": "cancelled", "mode": "analysis", "message": "分析已被取消"},
        )
        self.assertEqual(sidecar.event("log")["message"], "分析任务已取消")
        idle = sidecar.event("progress", "analysis")
        self.assertEqual((idle["status"], idle["percent"]), ("idle", 100))

    def test_every_source_reaches_the_processor_with_both_datasets(self) -> None:
        # Source routing lives inside the processor, so the sidecar contract is
        # simply that it hands over both datasets plus the params untouched.
        # The migration must keep dynamics and all on this path.
        # "auto", a missing key and an unknown value must reach the processor
        # untouched too: _normalize_source resolves them from the data, and the
        # migration must not route on that inferred value.
        for source in ("comments", "dynamics", "all", "auto", "not-a-source", None):
            with self.subTest(source=source):
                processor = StubAnalysisProcessor(result=ANALYSIS_RESULT)
                sidecar, _ = make(processor=processor)
                sidecar._last_comments = [COMMENT_A]
                sidecar._last_dynamics = [{"dynamic_id": "d1", "content": "一条动态"}]

                request = {"llm_config": {"api_key": "k"}}
                if source is not None:
                    request["source"] = source
                sidecar._run_analysis(request)

                comments, dynamics, params = processor.calls[0]
                self.assertEqual(len(comments), 1)
                self.assertEqual(len(dynamics), 1)
                if source is None:
                    self.assertNotIn("source", params)
                else:
                    self.assertEqual(params["source"], source)
                # Whatever the source, the sidecar never resolves it itself.
                self.assertTrue(sidecar.has("finished", "analysis"))

    def test_analysis_latest_returns_the_compact_display_shape(self) -> None:
        # The RPC never returns the raw result: _display_analysis_result
        # truncates every field and blanks report_markdown, while the raw result
        # stays in memory for analysis.export. Both halves are pinned here.
        raw_png = WORD_CLOUD_BYTES
        processor = StubAnalysisProcessor(result={
            **ANALYSIS_RESULT,
            "word_counts": [{"name": "关键词", "value": 3}],
            "notable_quotes": ["一条代表性评论"],
            "word_cloud_image": "data:image/png;base64," + base64.b64encode(raw_png).decode("ascii"),
        })
        sidecar, _ = make(processor=processor)
        sidecar._last_comments = [COMMENT_A]

        original_root = Sidecar._analysis_asset_root
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                Sidecar._analysis_asset_root = staticmethod(lambda: Path(temp_dir))
                sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "k"}})
                sidecar.handle({"id": "latest-1", "method": "analysis.latest", "params": {}})

                responses = [frame for frame in sidecar.frames
                             if frame.get("kind") == "response" and frame.get("id") == "latest-1"]
                self.assertEqual(len(responses), 1)
                self.assertTrue(responses[0]["ok"])
                payload = responses[0]["result"]

                # The whole payload, value by value. Only the asset path is
                # dynamic, so it is popped and checked separately.
                image_path = Path(payload.pop("word_cloud_image_path"))
                self.assertEqual(payload, {
                    "summary": "总体偏正面",
                    "summary_points": [],
                    "overview": {
                        "total_records": 9, "analyzed_records": 7, "risk_count": 1,
                        "ip_locations": 5, "missing_ip_locations": 4,
                    },
                    "sentiment_counts": [],
                    "topic_counts": [],
                    "word_counts": [{"name": "关键词", "value": 3}],
                    "risk_points": [],
                    "insights": [],
                    "notable_quotes": ["一条代表性评论"],
                    "time_series": [],
                    "region_counts": [],
                    "overseas_region_counts": [],
                    "user_level_counts": [],
                    "content_type_counts": [],
                    "engagement_items": [],
                    "deep_analysis": {"sociology": "", "psychology": "", "philosophy": ""},
                    "report_markdown": "",
                    "meta": {"analyzed_records": 7, "total_records": 9},
                    "word_cloud_image": WORD_CLOUD_DATA_URL,
                })
                self.assertTrue(image_path.is_file())
                self.assertEqual(image_path.read_bytes(), raw_png)
            finally:
                Sidecar._analysis_asset_root = original_root

        # The RPC payload is a projection; the raw result keeps everything the
        # display shape dropped or rewrote.
        raw = sidecar._last_analysis
        self.assertEqual(raw["report_markdown"], "# 报告")
        self.assertEqual(raw["summary"], "总体偏正面")
        self.assertEqual(raw["word_counts"], [{"name": "关键词", "value": 3}])
        self.assertEqual(raw["notable_quotes"], ["一条代表性评论"])
        self.assertEqual(raw["meta"], {"analyzed_records": 7, "total_records": 9})
        self.assertTrue(raw["word_cloud_image"].startswith("data:image/png;base64,"))

    def test_analysis_latest_without_a_result_answers_not_ok(self) -> None:
        sidecar, _ = make()
        sidecar.handle({"id": "latest-2", "method": "analysis.latest", "params": {}})

        responses = [frame for frame in sidecar.frames
                     if frame.get("kind") == "response" and frame.get("id") == "latest-2"]
        self.assertEqual(len(responses), 1)
        self.assertFalse(responses[0]["ok"])
        self.assertIn("暂无分析结果", responses[0]["error"])

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
