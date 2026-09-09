"""Exercise real pagers through persistence and desktop export, without network."""
import copy
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from bilibili_crawler.processor.analysis_processor import LLMAnalysisProcessor
from bilibili_crawler.service.agent_service import AgentService
from bilibili_crawler.service.credentials import LLMCredentials
from bilibili_crawler.service.models import DESKTOP_POLICY
from bilibili_crawler.service.run_store import RunStore
from bilibili_crawler.sidecar import Sidecar, SidecarServices


def reply(rpid, replies=0):
    return {"rpid": rpid, "rcount": replies, "content": {"message": f"comment {rpid}"}, "member": {"uname": f"author {rpid}"}}


def page(ids, end=False):
    return {"data": {"replies": [reply(i) for i in ids], "cursor": {"is_end": end, "next": 2}}}


class PagedAPI:
    def __init__(self, pages):
        self.pages = iter(pages)
        self.reply_calls = []

    def get_video_info(self, *args, **kwargs):
        return {"data": {"aid": kwargs.get("aid", 1), "title": "Original video", "owner": {"name": "Original owner"}, "pubdate": 1}}

    def get_comments(self, *args, **kwargs):
        return next(self.pages)

    def get_replies(self, oid, root, **kwargs):
        self.reply_calls.append(root)
        return {"data": {"replies": [reply(root * 10)], "cursor": {"is_end": True}}}


class RecordingSidecar(Sidecar):
    def _send(self, frame):
        self.frames.append(frame)

    def __init__(self, api):
        self.frames = []
        super().__init__(SidecarServices(api=api))


class CrawlIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        env = patch.dict(os.environ, {"BILIBILI_AGENT_RUNS_DIR": self.temp.name})
        env.start()
        self.addCleanup(env.stop)

    def test_overlapping_pages_deduplicate_before_fetching_replies(self):
        pages = [page([1, 1, 2]), page([2, 3], True)]
        for entry in pages:
            for item in entry["data"]["replies"]:
                item["rcount"] = 1
        api = PagedAPI(pages)
        service = AgentService(store=RunStore(Path(self.temp.name)), api=api)
        started = service.start_crawl("av1", include_replies=True)
        self.assertTrue(service.wait_until_finished(started.task_id, 5))
        rows = service.store.load_comments(started.run_id)
        self.assertCountEqual([row["comment_id"] for row in rows], [1, 2, 3, 10, 20, 30])
        self.assertCountEqual(api.reply_calls, [1, 2, 3])
        self.assertEqual(service.get_status(task_id=started.task_id).counts["comments"], 6)

    def test_second_page_failure_is_failed_and_partial_files_survive_restart(self):
        service = AgentService(store=RunStore(Path(self.temp.name)), api=PagedAPI([page([1, 2]), None]))
        started = service.start_crawl("av1", include_replies=False)
        self.assertTrue(service.wait_until_finished(started.task_id, 5))
        restarted = AgentService(store=RunStore(Path(self.temp.name)))
        snapshot = restarted.get_status(run_id=started.run_id)
        self.assertEqual(snapshot.status, "failed")
        self.assertEqual(snapshot.error_code, "CRAWL_FAILED")
        self.assertEqual(snapshot.counts["comments"], 2)
        self.assertEqual(len(restarted.store.load_comments(started.run_id)), 2)
        self.assertTrue(Path(snapshot.artifacts["comments_csv"]).is_file())

    def test_empty_success_is_distinct_from_first_page_failure_on_desktop(self):
        for response, expected in [(page([], True), "completed"), (None, "failed")]:
            with self.subTest(expected=expected):
                service = AgentService(store=RunStore(Path(self.temp.name)), api=PagedAPI([response]), policy=DESKTOP_POLICY)
                started = service.start_crawl("av1", include_replies=False)
                self.assertTrue(service.wait_until_finished(started.task_id, 5))
                self.assertEqual(service.get_status(task_id=started.task_id).status, expected)

    def test_cancel_during_partial_save_wins_over_crawl_failure(self):
        writing = threading.Event()
        release = threading.Event()

        class BlockingStore(RunStore):
            def save_comments(inner, run_id, comments):
                artifacts = super().save_comments(run_id, comments)
                writing.set()
                if not release.wait(5):
                    raise TimeoutError("test did not release the save")
                return artifacts

        store = BlockingStore(Path(self.temp.name))
        service = AgentService(store=store, api=PagedAPI([page([1]), None]))
        started = service.start_crawl("av1", include_replies=False)
        try:
            self.assertTrue(writing.wait(5))
            self.assertEqual(service.stop(started.task_id).status, "cancelling")
        finally:
            release.set()
            service.wait_until_finished(started.task_id, 5)
        snapshot = service.get_status(task_id=started.task_id)
        self.assertEqual(snapshot.status, "cancelled")
        self.assertEqual(snapshot.error_code, "CANCELLED")
        self.assertIsNone(snapshot.error)
        self.assertEqual(snapshot.counts["comments"], 1)
        self.assertTrue(Path(snapshot.artifacts["comments_csv"]).is_file())
        restarted = AgentService(store=RunStore(Path(self.temp.name)))
        self.assertEqual(restarted.get_status(run_id=started.run_id).status, "cancelled")

    def test_incomplete_crawl_does_not_automatically_call_llm(self):
        service = AgentService(store=RunStore(Path(self.temp.name)), api=PagedAPI([page([1]), None]))
        credentials = LLMCredentials.from_config({"api_key": "test-key", "model": "test"}, source="test")
        with patch.object(LLMAnalysisProcessor, "analyze") as analyze:
            started = service.start_crawl_and_analyze("av1", include_replies=False, credentials=credentials)
            self.assertTrue(service.wait_until_finished(started.task_id, 5))
            self.assertEqual(service.get_status(task_id=started.task_id).status, "failed")
            analyze.assert_not_called()

    def test_reply_failure_keeps_main_comments_and_reports_incomplete(self):
        response = page([1], True)
        response["data"]["replies"][0]["rcount"] = 2
        api = PagedAPI([response])
        api.get_replies = lambda *args, **kwargs: None
        sidecar = RecordingSidecar(api)
        sidecar._run_comments({"input": "av1"})
        self.assertEqual([c["comment_id"] for c in sidecar._last_comments], [1])
        self.assertEqual([f["event"] for f in sidecar.frames if f["event"] in {"partial", "error", "finished"}], ["partial", "error"])

    def test_desktop_partial_comments_remain_exportable(self):
        sidecar = RecordingSidecar(PagedAPI([page([1, 2]), None]))
        sidecar._run_comments({"input": "av1", "include_replies": False})
        path = Path(self.temp.name) / "partial.csv"
        sidecar._export_csv("export", {"kind": "comments", "path": str(path)})
        self.assertIn("comment 1", path.read_text(encoding="utf-8-sig"))
        self.assertTrue(any(f.get("event") == "partial" and f["count"] == 2 for f in sidecar.frames))
        self.assertFalse(any(f.get("event") == "finished" for f in sidecar.frames))

    def test_dynamic_partial_failure_applies_filters_and_allows_export(self):
        def item(i, timestamp, content):
            return {"id_str": i, "type": "DYNAMIC_TYPE_WORD", "modules": {
                "module_author": {"pub_ts": timestamp}, "module_dynamic": {"desc": {"text": content}}}}
        responses = iter([{"data": {"items": [item("a", 200, "keep this"), item("b", 200, "discard"), item("c", 1, "keep old")], "has_more": True, "offset": "next"}}, None])
        api = PagedAPI([])
        api.get_user_dynamics = lambda *args, **kwargs: next(responses)
        sidecar = RecordingSidecar(api)
        sidecar._run_dynamics({"uid": 1, "keyword": "keep", "start_ts": 100})
        self.assertEqual([r["dynamic_id"] for r in sidecar._last_dynamics], ["a"])
        path = Path(self.temp.name) / "dynamics.csv"
        sidecar._export_csv("export", {"kind": "dynamics", "path": str(path)})
        self.assertIn("keep this", path.read_text(encoding="utf-8-sig"))
        self.assertFalse(any(f.get("event") == "finished" for f in sidecar.frames))

    def test_desktop_report_keeps_analysis_provenance_after_a_new_crawl(self):
        api = PagedAPI([page([1], True), page([2], True)])
        sidecar = RecordingSidecar(api)
        sidecar._run_comments({"input": "av1", "include_replies": False})
        run_id = sidecar._last_comment_run_id
        result = {"summary": "summary", "meta": {"source": "comments", "chart_keys": ["topic_ranking"], "analyzed_records": 1}, "notable_quotes": ["comment 1"]}
        with patch.object(LLMAnalysisProcessor, "analyze", return_value=copy.deepcopy(result)):
            sidecar._run_analysis({"source": "comments", "llm_config": {"api_key": "test-key", "model": "test"}})
        self.assertTrue(any(f.get("event") == "finished" and f.get("mode") == "analysis" for f in sidecar.frames))
        sidecar._run_comments({"input": "av2", "include_replies": False})
        path = Path(self.temp.name) / "report.md"
        sidecar._export_analysis("export", {"path": str(path), "chart_assets": [{"key": "topic_ranking", "filename": "topic.svg", "svg": '<svg xmlns="http://www.w3.org/2000/svg"/>'}]})
        report = path.read_text(encoding="utf-8")
        self.assertIn(run_id, report)
        self.assertIn("av1", report)
        self.assertNotIn(sidecar._last_comment_run_id, report)
        self.assertIn("Original video", report)
        self.assertIn("Original owner", report)
        self.assertIn("author 1", report)
        self.assertIn("report_assets/topic.svg", report)
        self.assertTrue((Path(self.temp.name) / "report_assets/topic.svg").is_file())


if __name__ == "__main__":
    unittest.main()
