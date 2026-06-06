import json
import logging
import io
import base64
import tempfile
import unittest
from pathlib import Path
from contextlib import redirect_stdout

from backend.sidecar import Sidecar
from src.api.bilibili_api import BilibiliAPI
from src.crawler.comment_crawler import CommentCrawler
from src.crawler.dynamic_crawler import DynamicCrawler
from src.processor.analysis_processor import AnalysisCancelled, LLMAnalysisProcessor


FIXTURE_DIR = Path(__file__).parent / "fixtures"


class CaptureSidecar(Sidecar):
    def __init__(self) -> None:
        super().__init__()
        self.messages: list[dict] = []

    def _send(self, payload: dict) -> None:
        self.messages.append(payload)


def wait_for_active_thread(sidecar: CaptureSidecar) -> None:
    thread = sidecar._active_thread
    if thread is not None:
        thread.join(timeout=2)
        if thread.is_alive():
            raise AssertionError("sidecar task thread did not finish")


def repeated_comment_fixture(count: int) -> list[dict]:
    base = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    for index in range(count):
        item = dict(base[index % len(base)])
        item["comment_id"] = 10000 + index
        item["content"] = f"{item.get('content', '')} batch-marker-{index}"
        rows.append(item)
    return rows


class SidecarAnalysisTests(unittest.TestCase):
    def test_wbi_sign_adds_required_comment_params(self) -> None:
        signed = BilibiliAPI._sign_wbi_params({"oid": 80433022, "type": 1, "mode": 3}, "a" * 32)

        self.assertIn("wts", signed)
        self.assertIn("w_rid", signed)
        self.assertEqual(len(signed["w_rid"]), 32)

    def test_comment_ip_location_is_normalized_from_reply_control(self) -> None:
        comment = CommentCrawler()._process_comment(
            {
                "rpid": 1,
                "parent": 0,
                "member": {"mid": 2, "uname": "user", "level_info": {"current_level": 4}},
                "content": {"message": "测试评论"},
                "reply_control": {"location": "IP属地：广东"},
            },
            oid=100,
        )

        self.assertEqual(comment["ip_location"], "广东")

    def test_comment_task_reuses_logged_in_api_session(self) -> None:
        original_crawl = CommentCrawler.crawl_comments
        captured_api = None

        def fake_crawl(self, *args, **kwargs):
            nonlocal captured_api
            captured_api = self.api
            return [
                {
                    "comment_id": 1,
                    "content": "测试评论",
                    "is_reply": False,
                    "like_count": 0,
                    "reply_count": 0,
                    "ip_location": "上海",
                }
            ]

        try:
            CommentCrawler.crawl_comments = fake_crawl
            sidecar = CaptureSidecar()
            sidecar._run_comments({"input": "BV1xx", "max_pages": 1})
        finally:
            CommentCrawler.crawl_comments = original_crawl

        self.assertIs(captured_api, sidecar._api)
        self.assertEqual(sidecar._last_comments[0]["ip_location"], "上海")

    def test_stop_crawler_task_does_not_set_analysis_cancel_flag(self) -> None:
        sidecar = CaptureSidecar()
        crawler = DynamicCrawler()
        sidecar._active_crawler = crawler
        sidecar._analysis_cancel.clear()

        sidecar._stop_task()

        self.assertTrue(crawler._stop_flag)
        self.assertFalse(sidecar._analysis_cancel.is_set())

    def test_dynamic_string_pub_ts_is_processed_as_timestamp(self) -> None:
        crawler = DynamicCrawler()
        dynamic = crawler._process_dynamic(
            {
                "id_str": "dynamic-1",
                "type": "DYNAMIC_TYPE_WORD",
                "modules": {
                    "module_author": {"pub_ts": "1780560000", "name": "author"},
                    "module_dynamic": {"desc": {"text": "一条动态"}},
                    "module_stat": {"like": {"count": 3}, "comment": {"count": 2}, "forward": {"count": 1}},
                },
            }
        )

        self.assertIsNotNone(dynamic)
        self.assertEqual(dynamic["timestamp"], 1780560000)
        self.assertTrue(dynamic["publish_time"])

    def test_dynamic_time_filter_accepts_string_timestamps(self) -> None:
        crawler = DynamicCrawler()
        dynamics = [
            {"dynamic_id": "old", "content": "旧动态", "timestamp": "1780550000"},
            {"dynamic_id": "new", "content": "新动态", "timestamp": "1780560000"},
        ]

        filtered = crawler._enrich_and_filter(dynamics, start_time="1780555000")

        self.assertEqual([item["dynamic_id"] for item in filtered], ["new"])

    def test_dynamic_enrich_logs_no_text_when_no_opus_content_found(self) -> None:
        logs: list[str] = []
        crawler = DynamicCrawler(progress_callback=logs.append)

        class FakeResponse:
            status_code = 200
            text = "<html></html>"

        class FakeSession:
            def get(self, *args, **kwargs):
                return FakeResponse()

        crawler.api.session = FakeSession()

        result = crawler._enrich_from_opus(["dynamic-1"])

        self.assertEqual(result, {})
        self.assertTrue(logs)
        self.assertIn("未补齐到新的动态文字", logs[-1])
        self.assertNotIn("成功补齐 0", logs[-1])

    def test_protocol_output_is_ascii_safe_for_utf8_rust_reader(self) -> None:
        sidecar = Sidecar()
        buffer = io.StringIO()

        with redirect_stdout(buffer):
            sidecar.emit("finished", mode="analysis", message="分析完成", result={"summary": "中文总结"})

        raw = buffer.getvalue()
        raw.encode("ascii")
        decoded = json.loads(raw)

        self.assertEqual(decoded["message"], "分析完成")
        self.assertEqual(decoded["result"]["summary"], "中文总结")

    def test_analysis_start_fast_failure_does_not_leave_late_running_state(self) -> None:
        sidecar = CaptureSidecar()

        logger = logging.getLogger("sidecar")
        previous_disabled = logger.disabled
        logger.disabled = True
        try:
            sidecar.handle(
                {
                    "id": "analysis-1",
                    "method": "analysis.start",
                    "params": {"llm_config": {"api_key": "test-key", "model": "test-model"}},
                }
            )
            wait_for_active_thread(sidecar)
        finally:
            logger.disabled = previous_disabled

        events = [item for item in sidecar.messages if item.get("kind") == "event"]
        running_indexes = [
            index
            for index, item in enumerate(events)
            if item.get("event") == "progress" and item.get("status") == "running" and item.get("mode") == "analysis"
        ]
        error_indexes = [index for index, item in enumerate(events) if item.get("event") == "error" and item.get("mode") == "analysis"]
        idle_indexes = [
            index
            for index, item in enumerate(events)
            if item.get("event") == "progress" and item.get("status") == "idle" and item.get("mode") == "analysis"
        ]

        self.assertTrue(running_indexes, events)
        self.assertTrue(error_indexes, events)
        self.assertTrue(idle_indexes, events)
        self.assertLess(running_indexes[0], error_indexes[-1], events)
        self.assertLess(running_indexes[0], idle_indexes[-1], events)
        self.assertEqual(events[-1].get("status"), "idle")
        self.assertFalse(sidecar._is_task_running())

    def test_run_analysis_success_emits_finished_then_idle_with_compact_result(self) -> None:
        original_analyze = LLMAnalysisProcessor.analyze

        def fake_analyze(comments, dynamics, params, progress=None, cancel_event=None):
            if progress:
                progress("正在调用 LLM 分析第 1/1 批", 80)
            return {
                "summary": "摘要" * 1200,
                "overview": {"total_records": 3, "analyzed_records": 3, "risk_count": 1},
                "sentiment_counts": [{"name": "正向", "value": 2}, {"name": "负向", "value": 1}],
                "topic_counts": [{"name": "标题误解" * 50, "value": 1}],
                "risk_points": ["标题表达可能引发误解" * 40],
                "insights": ["用户认可内容质量" * 40],
                "notable_quotes": ["这个视频讲得很清楚" * 40],
                "time_series": [],
                "region_counts": [],
                "user_level_counts": [],
                "content_type_counts": [],
                "engagement_items": [],
                "report_markdown": "# full report\n" + ("正文" * 5000),
                "meta": {"analyzed_records": 3, "batch_count": 1},
            }

        try:
            LLMAnalysisProcessor.analyze = staticmethod(fake_analyze)
            sidecar = CaptureSidecar()
            sidecar._last_comments = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))

            sidecar._run_analysis({"llm_config": {"api_key": "test-key", "model": "test-model"}})
        finally:
            LLMAnalysisProcessor.analyze = original_analyze

        events = [item for item in sidecar.messages if item.get("kind") == "event"]
        finished = [item for item in events if item.get("event") == "finished"]
        running_100 = [
            item for item in events if item.get("event") == "progress" and item.get("status") == "running" and item.get("percent") == 100
        ]

        self.assertEqual([item.get("event") for item in events], ["analysis.progress", "finished", "progress"])
        self.assertFalse(running_100)
        self.assertEqual(events[-1].get("status"), "idle")
        self.assertTrue(finished[0].get("result"))
        result = finished[0]["result"]
        self.assertLessEqual(len(result["summary"]), 2001)
        self.assertEqual(result["report_markdown"], "")
        self.assertLessEqual(len(result["topic_counts"][0]["name"]), 81)

    def test_run_analysis_cancel_uses_explicit_cancel_event(self) -> None:
        original_analyze = LLMAnalysisProcessor.analyze

        def fake_analyze(comments, dynamics, params, progress=None, cancel_event=None):
            raise AnalysisCancelled("分析已被取消")

        try:
            LLMAnalysisProcessor.analyze = staticmethod(fake_analyze)
            sidecar = CaptureSidecar()
            sidecar._run_analysis({"llm_config": {"api_key": "test-key", "model": "test-model"}})
        finally:
            LLMAnalysisProcessor.analyze = original_analyze

        events = [item for item in sidecar.messages if item.get("kind") == "event"]
        self.assertTrue(any(item.get("event") == "error" and item.get("message") == "分析已被取消" for item in events))
        self.assertTrue(any(item.get("event") == "log" and item.get("message") == "分析任务已取消" for item in events))

    def test_run_analysis_cancel_after_result_does_not_emit_finished(self) -> None:
        original_analyze = LLMAnalysisProcessor.analyze

        def fake_analyze(comments, dynamics, params, progress=None, cancel_event=None):
            if cancel_event:
                cancel_event.set()
            return {
                "summary": "取消竞态结果",
                "overview": {"total_records": 1, "analyzed_records": 1},
                "sentiment_counts": [],
                "topic_counts": [],
                "word_counts": [],
                "risk_points": [],
                "insights": [],
                "notable_quotes": [],
                "time_series": [],
                "region_counts": [],
                "overseas_region_counts": [],
                "user_level_counts": [],
                "content_type_counts": [],
                "engagement_items": [],
                "deep_analysis": {"sociology": "", "psychology": "", "philosophy": ""},
                "report_markdown": "",
                "meta": {"analyzed_records": 1, "batch_count": 1},
            }

        try:
            LLMAnalysisProcessor.analyze = staticmethod(fake_analyze)
            sidecar = CaptureSidecar()
            sidecar._run_analysis({"llm_config": {"api_key": "test-key", "model": "test-model"}})
        finally:
            LLMAnalysisProcessor.analyze = original_analyze

        events = [item for item in sidecar.messages if item.get("kind") == "event"]
        self.assertFalse(any(item.get("event") == "finished" for item in events), events)
        self.assertTrue(any(item.get("event") == "error" and item.get("message") == "分析已被取消" for item in events))
        self.assertIsNone(sidecar._last_analysis)

    def test_run_analysis_generic_error_containing_cancel_text_is_not_cancelled(self) -> None:
        original_analyze = LLMAnalysisProcessor.analyze

        def fake_analyze(comments, dynamics, params, progress=None, cancel_event=None):
            raise RuntimeError("上游请求被取消但不是用户停止")

        try:
            LLMAnalysisProcessor.analyze = staticmethod(fake_analyze)
            sidecar = CaptureSidecar()
            with self.assertLogs("sidecar", level="ERROR"):
                sidecar._run_analysis({"llm_config": {"api_key": "test-key", "model": "test-model"}})
        finally:
            LLMAnalysisProcessor.analyze = original_analyze

        events = [item for item in sidecar.messages if item.get("kind") == "event"]
        self.assertTrue(any(item.get("event") == "error" and "上游请求被取消" in item.get("message", "") for item in events))
        self.assertFalse(any(item.get("event") == "log" and item.get("message") == "分析任务已取消" for item in events))

    def test_display_analysis_result_writes_word_cloud_image_to_file(self) -> None:
        raw = b"\x89PNG\r\n\x1a\nword-cloud-test"
        result = {
            "summary": "ok",
            "overview": {},
            "word_counts": [{"name": "test", "value": 3}],
            "word_cloud_image": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
        }

        original_root = Sidecar._analysis_asset_root
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                Sidecar._analysis_asset_root = staticmethod(lambda: Path(temp_dir))
                display = Sidecar._display_analysis_result(result)
                self.assertNotIn("word_cloud_image", display)
                image_path = display.get("word_cloud_image_path")
                self.assertTrue(image_path)
                self.assertEqual(Path(image_path).read_bytes(), raw)
            finally:
                Sidecar._analysis_asset_root = original_root

    def test_word_cloud_asset_dir_uses_source_label_timestamp_and_bvid(self) -> None:
        raw = b"\x89PNG\r\n\x1a\nword-cloud-test"
        result = {
            "summary": "ok",
            "overview": {},
            "word_counts": [{"name": "test", "value": 3}],
            "word_cloud_image": "data:image/png;base64," + base64.b64encode(raw).decode("ascii"),
            "_asset_context": {
                "timestamp": "20260606-134500",
                "label": "视频评论",
                "bvid": "BV1abcdefghij",
            },
        }

        original_root = Sidecar._analysis_asset_root
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                Sidecar._analysis_asset_root = staticmethod(lambda: Path(temp_dir))
                display = Sidecar._display_analysis_result(result)
                image_path = Path(display["word_cloud_image_path"])
                self.assertEqual(image_path.parent.name, "20260606-134500-视频评论-BV1abcdefghij")
                self.assertTrue(image_path.name.startswith("word_cloud_image-"))
            finally:
                Sidecar._analysis_asset_root = original_root

    def test_chart_assets_accept_png_file_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            image_path = Path(temp_dir) / "word-cloud.png"
            image_path.write_bytes(b"\x89PNG\r\n\x1a\nfile-path-test")

            assets = Sidecar._chart_assets(
                [
                    {
                        "key": "word_cloud",
                        "title": "word cloud",
                        "filename": "word-cloud.png",
                        "file_path": str(image_path),
                    }
                ]
            )

        self.assertEqual(len(assets), 1)
        self.assertEqual(assets[0]["filename"], "word-cloud.png")
        self.assertEqual(assets[0]["data"], b"\x89PNG\r\n\x1a\nfile-path-test")

    def test_analysis_processor_builds_layers_from_comment_fixture_without_real_llm(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            return {
                "summary": "整体反馈偏正向，但存在标题误解和更新频率担忧。",
                "sentiment_counts": [{"name": "正向", "value": 2}, {"name": "负向", "value": 1}],
                "topic_counts": [{"name": "内容质量", "value": 2}, {"name": "标题误解", "value": 1}],
                "word_counts": [{"name": "内容质量", "value": 3}],
                "risk_points": ["标题容易让人误解"],
                "insights": ["用户认可内容清晰度", "需要补充后续更新计划"],
                "notable_quotes": ["这个视频讲得很清楚"],
                "deep_analysis": {"sociology": "群体关注更新承诺。", "psychology": "标题误解带来不确定感。", "philosophy": "解释责任影响信任。"},
            }

        comments = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))
        progress_events: list[tuple[str, int]] = []
        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            result = LLMAnalysisProcessor.analyze(
                comments,
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "sample_size": 20,
                    "batch_size": 20,
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
                progress=lambda message, percent: progress_events.append((message, percent)),
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm

        self.assertEqual(result["overview"]["total_records"], 3)
        self.assertEqual(result["overview"]["analyzed_records"], 3)
        self.assertEqual(result["meta"]["batch_count"], 1)
        self.assertEqual(result["sentiment_counts"][0]["name"], "正向")
        self.assertTrue(result["time_series"])
        self.assertTrue(result["region_counts"])
        self.assertEqual(result["region_counts"][0]["name"], "上海")
        self.assertIn("chart_keys", result["meta"])
        self.assertIn("report_markdown", result)
        self.assertTrue(result["summary_points"])
        self.assertLess(max(percent for _, percent in progress_events), 100)

    def test_user_level_distribution_ignores_invalid_zero_level_values(self) -> None:
        comments = [
            {
                "comment_id": index,
                "content": f"等级测试 {index}",
                "is_reply": False,
                "like_count": 0,
                "reply_count": 0,
                "ctime": 1780560000,
                "ip_location": "上海",
                "user_level": level,
            }
            for index, level in enumerate([0, "0", "", None, "5", 3.0, 2.5, 7, -1, True], start=1)
        ]
        records = LLMAnalysisProcessor._build_records(comments, [], "comments")

        layers = LLMAnalysisProcessor._build_local_layers(records, records, ["level_distribution"])
        counts = {item["name"]: item["value"] for item in layers["user_level_counts"]}

        self.assertEqual(list(counts), ["Lv1", "Lv2", "Lv3", "Lv4", "Lv5", "Lv6"])
        self.assertNotIn("Lv0", counts)
        self.assertEqual(counts["Lv3"], 1)
        self.assertEqual(counts["Lv5"], 1)
        self.assertEqual(counts["Lv1"], 0)

    def test_multi_batch_analysis_integrates_summary_points_with_second_llm_call(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm
        original_call_summary_llm = LLMAnalysisProcessor._call_summary_llm
        batch_sizes: list[int] = []
        summary_inputs: list[int] = []

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            batch_sizes.append(len(records))
            index = len(batch_sizes)
            return {
                "summary": f"batch {index} summary",
                "risk_points": [f"batch {index} risk"],
                "insights": [f"batch {index} insight"],
                "notable_quotes": [f"batch {index} quote"],
            }

        def fake_call_summary_llm(cls, base_url, api_key, model, batch_results, merged, strategy, total_records, analyzed):
            summary_inputs.append(len(batch_results))
            return {
                "summary": "integrated summary",
                "summary_points": ["point one", "point two", "point three", "point four"],
            }

        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            LLMAnalysisProcessor._call_summary_llm = classmethod(fake_call_summary_llm)
            result = LLMAnalysisProcessor.analyze(
                repeated_comment_fixture(45),
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "sample_size": 45,
                    "batch_size": 20,
                    "chart_keys": ["topic_ranking"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm
            LLMAnalysisProcessor._call_summary_llm = original_call_summary_llm

        self.assertEqual(batch_sizes, [20, 20, 5])
        self.assertEqual(summary_inputs, [3])
        self.assertEqual(result["meta"]["batch_count"], 3)
        self.assertEqual(result["summary"], "integrated summary")
        self.assertEqual(result["summary_points"], ["point one", "point two", "point three", "point four"])

    def test_multi_batch_summary_integration_falls_back_when_second_llm_fails(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm
        original_call_summary_llm = LLMAnalysisProcessor._call_summary_llm

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            index = 2 if any("batch-marker-20" in str(item.get("content", "")) for item in records) else 1
            return {
                "summary": f"local summary {index}",
                "risk_points": [f"local risk {index}"],
                "insights": [f"local insight {index}"],
                "notable_quotes": [],
            }

        def fake_call_summary_llm(cls, base_url, api_key, model, batch_results, merged, strategy, total_records, analyzed):
            raise RuntimeError("summary service down")

        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            LLMAnalysisProcessor._call_summary_llm = classmethod(fake_call_summary_llm)
            result = LLMAnalysisProcessor.analyze(
                repeated_comment_fixture(25),
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "sample_size": 25,
                    "batch_size": 20,
                    "chart_keys": ["topic_ranking"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm
            LLMAnalysisProcessor._call_summary_llm = original_call_summary_llm

        self.assertEqual(result["meta"]["batch_count"], 2)
        self.assertTrue(result["summary"])
        self.assertIn("local summary 1", result["summary_points"])
        self.assertIn("local insight 1", result["summary_points"])

    def test_chart_keys_control_prompt_and_result_fields(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm
        captured_prompt = ""

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            nonlocal captured_prompt
            captured_prompt = cls._build_prompt(records, source, strategy, chart_keys)
            return {
                "summary": "只分析词云。",
                "word_counts": [{"name": "更新计划", "value": 2}],
                "risk_points": [],
                "insights": ["需要说明更新计划"],
                "notable_quotes": [],
            }

        comments = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))
        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            result = LLMAnalysisProcessor.analyze(
                comments,
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "sample_size": 20,
                    "batch_size": 20,
                    "chart_keys": ["word_cloud"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm

        self.assertIn("word_counts", captured_prompt)
        self.assertNotIn("sentiment_counts", captured_prompt)
        self.assertNotIn("topic_counts", captured_prompt)
        self.assertEqual(result["meta"]["chart_keys"], ["word_cloud"])
        self.assertEqual(result["sentiment_counts"], [])
        self.assertEqual(result["topic_counts"], [])
        self.assertTrue(result["word_counts"])
        self.assertEqual(result["time_series"], [])

    def test_dynamic_source_filters_comment_only_chart_modules(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm
        captured_chart_keys: list[str] = []
        captured_prompt = ""

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            nonlocal captured_chart_keys, captured_prompt
            captured_chart_keys = list(chart_keys)
            captured_prompt = cls._build_prompt(records, source, strategy, chart_keys)
            return {
                "summary": "动态舆情测试。",
                "word_counts": [{"name": "动态", "value": 2}],
                "risk_points": [],
                "insights": ["动态反馈集中"],
                "notable_quotes": [],
                "deep_analysis": {"sociology": "不应出现"},
            }

        dynamics = [{"dynamic_id": 1, "content": "动态内容", "publish_time": "2026-06-04 12:00:00", "timestamp": 1780560000}]
        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            result = LLMAnalysisProcessor.analyze(
                [],
                dynamics,
                {
                    "strategy": "sample",
                    "sample_size": 20,
                    "batch_size": 20,
                    "chart_keys": ["time_trend", "level_distribution", "region_map", "deep_analysis", "word_cloud"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm

        self.assertEqual(result["meta"]["source"], "dynamics")
        self.assertEqual(result["meta"]["chart_keys"], ["word_cloud"])
        self.assertEqual(captured_chart_keys, ["word_cloud"])
        self.assertNotIn("deep_analysis", captured_prompt)
        self.assertEqual(result["time_series"], [])
        self.assertEqual(result["user_level_counts"], [])
        self.assertEqual(result["region_counts"], [])
        self.assertEqual(result["deep_analysis"], {"sociology": "", "psychology": "", "philosophy": ""})

    def test_region_counts_split_domestic_and_overseas(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            return {
                "summary": "地域测试。",
                "risk_points": [],
                "insights": [],
                "notable_quotes": [],
            }

        comments = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))
        comments.append({**comments[0], "comment_id": 104, "content": "海外用户反馈", "ip_location": "美国"})
        comments.append({**comments[0], "comment_id": 105, "content": "未知地区反馈", "ip_location": ""})
        comments.append({**comments[0], "comment_id": 106, "content": "台湾用户反馈", "ip_location": "台湾"})
        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            result = LLMAnalysisProcessor.analyze(
                comments,
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "sample_size": 20,
                    "batch_size": 20,
                    "chart_keys": ["region_map"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm

        domestic = {item["name"]: item["value"] for item in result["region_counts"]}
        overseas = {item["name"]: item["value"] for item in result["overseas_region_counts"]}
        self.assertEqual(domestic["上海"], 2)
        self.assertEqual(domestic["广东"], 1)
        self.assertEqual(domestic["台湾"], 1)
        self.assertEqual(overseas["美国"], 1)
        self.assertEqual(overseas["未知"], 1)
        self.assertNotIn("台湾", overseas)
        self.assertEqual(result["overview"]["ip_locations"], 5)
        self.assertEqual(result["overview"]["missing_ip_locations"], 1)

    def test_region_map_does_not_count_dynamics_as_unknown_ip(self) -> None:
        original_call_llm = LLMAnalysisProcessor._call_llm

        def fake_call_llm(cls, base_url, api_key, model, records, source, strategy, chart_keys):
            return {"summary": "混合数据测试。", "risk_points": [], "insights": [], "notable_quotes": []}

        comments = json.loads((FIXTURE_DIR / "analysis_comments.json").read_text(encoding="utf-8"))
        dynamics = [{"dynamic_id": 1, "content": "动态内容", "publish_time": "2026-06-04 12:00:00", "timestamp": 1780560000}]
        try:
            LLMAnalysisProcessor._call_llm = classmethod(fake_call_llm)
            result = LLMAnalysisProcessor.analyze(
                comments,
                dynamics,
                {
                    "source": "all",
                    "strategy": "sample",
                    "sample_size": 20,
                    "batch_size": 20,
                    "chart_keys": ["region_map"],
                    "llm_config": {"api_key": "test-key", "model": "test-model", "base_url": "https://example.test/v1"},
                },
            )
        finally:
            LLMAnalysisProcessor._call_llm = original_call_llm

        overseas = {item["name"]: item["value"] for item in result["overseas_region_counts"]}
        self.assertNotIn("未知", overseas)
        self.assertEqual(result["overview"]["ip_locations"], 3)

    def test_markdown_export_writes_chart_assets_and_references_selected_modules(self) -> None:
        sidecar = CaptureSidecar()
        sidecar._last_analysis = {
            "summary": "导出测试",
            "summary_points": ["export point one", "export point two"],
            "overview": {"total_records": 3, "analyzed_records": 3},
            "sentiment_counts": [{"name": "正向", "value": 2}],
            "topic_counts": [],
            "word_counts": [],
            "risk_points": [],
            "insights": ["洞察"],
            "notable_quotes": [],
            "time_series": [],
            "region_counts": [],
            "overseas_region_counts": [],
            "user_level_counts": [],
            "content_type_counts": [],
            "engagement_items": [],
            "deep_analysis": {"sociology": "", "psychology": "", "philosophy": ""},
            "meta": {
                "source": "comments",
                "strategy": "sample",
                "model": "test-model",
                "total_records": 3,
                "analyzed_records": 3,
                "batch_count": 1,
                "generated_at": "2026-06-04 12:00:00",
                "chart_keys": ["sentiment_distribution"],
            },
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "bilibili_analysis_report.md"
            sidecar._export_analysis(
                "export-1",
                {
                    "format": "markdown",
                    "path": str(target),
                    "chart_assets": [
                        {
                            "key": "sentiment_distribution",
                            "title": "情绪分布",
                            "filename": "sentiment-distribution.svg",
                            "svg": "<svg xmlns=\"http://www.w3.org/2000/svg\"></svg>",
                        }
                    ],
                },
            )

            markdown = target.read_text(encoding="utf-8")
            asset = target.with_name("bilibili_analysis_report_assets") / "sentiment-distribution.svg"
            self.assertIn("![情绪分布](bilibili_analysis_report_assets/sentiment-distribution.svg)", markdown)
            self.assertNotIn("## 主题排行", markdown)
            self.assertIn("- export point one", markdown)
            self.assertTrue(asset.exists())



if __name__ == "__main__":
    unittest.main()
