"""The crawl and analysis limits that were removed, and the reply-paging bug.

Covers what an agent can now ask for -- any page count including all of them,
every reply of a thread, unbounded sample and batch sizes, its own chart set
and custom modules -- and that the analysis no longer truncates what it was
given. Request pacing and the LLM request timeouts/retries are untouched and
not exercised here.
"""
import json
import unittest
from unittest.mock import patch

try:
    from mcp import Client
except ImportError:  # pragma: no cover - exercised only without the SDK
    Client = None

from bilibili_crawler import agent
from bilibili_crawler.crawler.comment_crawler import CommentCrawler
from bilibili_crawler.processor.analysis_processor import LLMAnalysisProcessor as P
from bilibili_crawler.service.models import AGENT_CHART_KEYS, MAX_PAGES_UNLIMITED

from test_caller_policy import PolicyTestCase


class ServiceTestCase(PolicyTestCase):
    def seed(self, service):
        return self.finish(service, service.start_crawl("BV1xx411c7mD")).run_id


def reply(rpid, **extra):
    return {"rpid": rpid, "rcount": 0, "content": {"message": f"回复 {rpid}"},
            "member": {"uname": f"u{rpid}"}, **extra}


class RealShapedAPI:
    """Pages the way x/v2/reply/reply actually does.

    Observed live: `page: {num, size, count}`, no `cursor`, and the server
    serves 20 per page whatever `ps` asks for. A fake that sent `cursor` would
    have passed the old code, which is exactly how the bug went unnoticed.
    """

    PAGE = 20

    def __init__(self, replies_per_root, main_pages=1):
        self.replies_per_root = replies_per_root
        self.main_pages = main_pages
        self.reply_calls: list[tuple[int, int]] = []
        self.main_calls = 0

    def get_video_info(self, *args, **kwargs):
        return {"data": {"aid": 1, "title": "t", "owner": {"name": "o"}, "pubdate": 1}}

    def get_comments(self, oid, page=1, **kwargs):
        self.main_calls += 1
        is_end = page >= self.main_pages
        roots = [reply(page * 1000 + i, rcount=self.replies_per_root) for i in range(2)]
        return {"data": {"replies": roots, "cursor": {"is_end": is_end, "next": page + 1}}}

    def get_replies(self, oid, root, page=1, type_id=1):
        self.reply_calls.append((root, page))
        start = (page - 1) * self.PAGE
        ids = range(start, min(start + self.PAGE, self.replies_per_root))
        return {"data": {
            "replies": [reply(root * 100 + i) for i in ids],
            "page": {"num": page, "size": self.PAGE, "count": self.replies_per_root},
        }}


def crawl(api, **kwargs):
    crawler = CommentCrawler(progress_callback=lambda _m: None, api=api)
    return crawler.crawl_comments("BV1xx411c7mD", **kwargs)


class ReplyPagingTests(unittest.TestCase):
    def test_every_reply_of_a_long_thread_is_fetched(self):
        # 70 replies = 20 + 20 + 20 + 10, the thread measured on the real site.
        api = RealShapedAPI(replies_per_root=70)
        comments = crawl(api, max_pages=1, include_replies=True)

        replies = [c for c in comments if c["is_reply"]]
        self.assertEqual(len(replies), 2 * 70)
        self.assertEqual(len({c["comment_id"] for c in replies}), 2 * 70)
        root = comments[0]["comment_id"]
        self.assertEqual([p for r, p in api.reply_calls if r == root], [1, 2, 3, 4])

    def test_an_exact_multiple_of_the_page_size_stops_without_an_empty_request(self):
        api = RealShapedAPI(replies_per_root=40)
        crawl(api, max_pages=1, include_replies=True)
        root = 1000
        self.assertEqual([p for r, p in api.reply_calls if r == root], [1, 2])

    def test_a_response_with_a_cursor_is_still_honoured(self):
        data = {"replies": [reply(1)], "cursor": {"is_end": True}}
        self.assertTrue(CommentCrawler._reply_thread_finished(data, 1))
        data = {"replies": [reply(1)], "cursor": {"is_end": False}}
        self.assertFalse(CommentCrawler._reply_thread_finished(data, 1))

    def test_without_paging_fields_a_repeated_page_ends_the_thread(self):
        class Repeating(RealShapedAPI):
            def get_replies(self, oid, root, page=1, type_id=1):
                self.reply_calls.append((root, page))
                return {"data": {"replies": [reply(root * 100)]}}

        api = Repeating(replies_per_root=5)
        comments = crawl(api, max_pages=1, include_replies=True)
        self.assertEqual(sum(1 for c in comments if c["is_reply"]), 2)
        self.assertEqual([p for r, p in api.reply_calls if r == 1000], [1, 2])


class UnlimitedPagesTests(unittest.TestCase):
    def test_zero_pages_crawls_until_the_section_ends(self):
        api = RealShapedAPI(replies_per_root=0, main_pages=7)
        comments = crawl(api, max_pages=MAX_PAGES_UNLIMITED, include_replies=False)
        self.assertEqual(api.main_calls, 7)
        self.assertEqual(len(comments), 14)

    def test_a_positive_page_count_still_stops_there(self):
        api = RealShapedAPI(replies_per_root=0, main_pages=7)
        crawl(api, max_pages=3, include_replies=False)
        self.assertEqual(api.main_calls, 3)


def record(i, content, day=1):
    return {
        "comment_id": i, "is_reply": False, "username": f"u{i}", "user_level": 3,
        "content": content, "like_count": i, "reply_count": 0,
        "ctime": 1735660800 + day * 86400, "ctime_text": "", "ip_location": "",
    }


class NoTruncationTests(unittest.TestCase):
    def test_a_long_comment_reaches_the_prompt_whole(self):
        text = "长" * 2000
        prompt = P._build_prompt([P._comment_record(record(1, text))], "comments", "sample",
                                 list(AGENT_CHART_KEYS))
        self.assertIn(text, prompt)
        for cap in ("最多 5 条", "最多 8 项", "最多 80 项", "3-6 条"):
            self.assertNotIn(cap, prompt)

    def test_merged_lists_keep_every_item(self):
        results = [{
            "topic_counts": [{"name": f"主题{i}", "value": 1} for i in range(20)],
            "word_counts": [{"name": f"词{i}", "value": 1} for i in range(120)],
            "risk_points": [f"风险{i}" for i in range(12)],
            "insights": [f"洞察{i}" for i in range(12)],
            "notable_quotes": [f"引用{i}" for i in range(9)],
        }]
        merged = P._merge_llm_results(results, [], 1, 1, 0, "sample",
                                      ["topic_ranking", "word_cloud"], None)
        self.assertEqual(len(merged["topic_counts"]), 20)
        self.assertEqual(len(merged["word_counts"]), 120)
        self.assertEqual(len(merged["risk_points"]), 12)
        self.assertEqual(len(merged["insights"]), 12)
        self.assertEqual(len(merged["notable_quotes"]), 9)

    def test_deep_analysis_keeps_every_batch(self):
        results = [{"deep_analysis": {"sociology": f"第{i}段"}} for i in range(1, 9)]
        merged = P._merge_llm_results(results, [], 1, 1, 0, "all", ["deep_analysis"], None)
        text = merged["deep_analysis"]["sociology"]
        self.assertIn("（第 8 批）第8段", text)
        self.assertEqual(text.count("（第 "), 8)

    def test_the_time_trend_covers_every_day(self):
        records = [P._comment_record(record(i, "内容", day=i)) for i in range(30)]
        layers = P._build_local_layers(records, records, ["time_trend"])
        self.assertEqual(len(layers["time_series"]), 30)

    def test_summary_points_are_neither_capped_nor_shortened(self):
        long_point = "要" * 300
        points = P._fallback_summary_points(
            [{"summary": long_point}], {"insights": [f"洞察{i}" for i in range(15)], "risk_points": []},
        )
        self.assertEqual(points[0], long_point)
        self.assertEqual(len(points), 16)

    def test_every_counted_word_is_kept(self):
        texts = [f"token{i:03d}x" for i in range(150)]
        self.assertEqual(len(P._build_word_counts_by_regex(texts)), 150)

    def test_sample_and_batch_sizes_are_used_as_given(self):
        comments = [record(i, f"评论{i}") for i in range(30)]
        seen = []

        def fake_call(base_url, api_key, model, batch, *args, **kwargs):
            seen.append(len(batch))
            return {"summary": "s"}

        with patch.object(P, "_call_llm", side_effect=fake_call),                 patch.object(P, "_integrate_summary", lambda *a, **k: None):
            P.analyze(comments, [], {
                "source": "comments", "strategy": "sample", "sample_size": 7, "batch_size": 3,
                "chart_keys": ["topic_ranking"],
                "llm_config": {"api_key": "k", "model": "m", "base_url": "http://127.0.0.1:1/v1"},
            })
        # 7 sampled (below the old floor of 20), 3 per batch (below the old 20).
        self.assertEqual(seen, [3, 3, 1])


class CustomModuleTests(ServiceTestCase):
    def test_a_module_without_an_id_gets_a_stable_one_and_is_switched_on(self):
        service = self.make()
        run_id = self.seed(service)
        module = {"title": "传播路径", "prompt": "分析争议如何扩散"}
        self.finish(service, service.start_analyze(run_id, custom_modules=[module]))
        self.finish(service, service.start_analyze(run_id, custom_modules=[dict(module)]))

        first, second = self.processor.params
        [sent] = first["custom_modules"]
        self.assertRegex(sent["id"], r"^custom_[0-9a-f]{6}$")
        self.assertIn(sent["id"], first["chart_keys"])
        self.assertEqual(second["custom_modules"][0]["id"], sent["id"])
        # The default charts are still there.
        for key in AGENT_CHART_KEYS:
            self.assertIn(key, first["chart_keys"])

    def test_modules_that_bring_their_own_id_are_not_switched_on_for_the_caller(self):
        # The desktop sends every saved module with its id and ticks the active
        # ones in chart_keys; activating the rest would spend tokens it did not
        # ask for.
        service = self.make()
        run_id = self.seed(service)
        saved = {"id": "custom_abcdef", "title": "未勾选", "prompt": "不应运行"}
        self.finish(service, service.start_analyze(
            run_id, chart_keys=["topic_ranking"], custom_modules=[saved],
        ))
        self.assertEqual(self.processor.params[0]["chart_keys"], ["topic_ranking"])

    def test_more_than_three_modules_all_run(self):
        service = self.make()
        run_id = self.seed(service)
        modules = [{"title": f"视角{i}", "prompt": f"提示{i}"} for i in range(6)]
        self.finish(service, service.start_analyze(run_id, custom_modules=modules))
        sent = self.processor.params[0]["custom_modules"]
        self.assertEqual(len(sent), 6)
        self.assertTrue(all(item["id"] in self.processor.params[0]["chart_keys"] for item in sent))


class CliFlagTests(unittest.TestCase):
    def parse(self, *argv):
        return agent._build_parser().parse_args(list(argv))

    def test_analysis_flags_reach_the_service_arguments(self):
        args = self.parse(
            "crawl-and-analyze", "BV1xx411c7mD", "--max-pages", "0", "--strategy", "all",
            "--sample-size", "5000", "--batch-size", "40", "--charts", "word_cloud, topic_ranking",
            "--custom-module", "传播路径=分析争议如何扩散",
        )
        self.assertEqual(args.max_pages, 0)
        self.assertEqual(agent._analysis_kwargs(args), {
            "sample_size": 5000,
            "strategy": "all",
            "batch_size": 40,
            "chart_keys": ["word_cloud", "topic_ranking"],
            "custom_modules": [{"title": "传播路径", "prompt": "分析争议如何扩散"}],
        })

    def test_defaults_leave_the_service_to_decide(self):
        kwargs = agent._analysis_kwargs(self.parse("analyze-run", "20260101-000000-abcdef01"))
        self.assertIsNone(kwargs["batch_size"])
        self.assertIsNone(kwargs["chart_keys"])
        self.assertIsNone(kwargs["custom_modules"])

    def test_a_malformed_custom_module_is_an_input_error(self):
        from bilibili_crawler.service.models import ServiceError
        args = self.parse("analyze-run", "20260101-000000-abcdef01", "--custom-module", "只有标题")
        with self.assertRaises(ServiceError) as ctx:
            agent._analysis_kwargs(args)
        self.assertEqual(ctx.exception.code, "INVALID_INPUT")


@unittest.skipIf(Client is None, "MCP SDK not installed")
class McpParameterTests(ServiceTestCase, unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        ServiceTestCase.setUp(self)
        from bilibili_crawler import mcp_server
        self.mcp_server = mcp_server
        self.addCleanup(mcp_server.set_service, None)

    async def test_the_analysis_tools_expose_the_new_parameters(self):
        async with Client(self.mcp_server.mcp, raise_exceptions=False) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        for name in ("crawl_and_analyze", "analyze_run"):
            with self.subTest(tool=name):
                props = tools[name].input_schema["properties"]
                for key in ("strategy", "batch_size", "chart_keys", "custom_modules", "sample_size"):
                    self.assertIn(key, props)
                self.assertNotIn("上限 50", tools[name].description or "")

    async def test_crawl_and_analyze_forwards_them(self):
        service = self.make()
        self.mcp_server.set_service(service)
        async with Client(self.mcp_server.mcp, raise_exceptions=False) as client:
            result = await client.call_tool("crawl_and_analyze", {
                "url": "BV1xx411c7mD",
                "max_pages": 0,
                "strategy": "all",
                "sample_size": 3000,
                "batch_size": 25,
                "chart_keys": ["word_cloud"],
                "custom_modules": [{"title": "传播路径", "prompt": "分析争议如何扩散"}],
                "wait_seconds": 30,
            })
        self.assertFalse(result.is_error, result.content)
        self.assertEqual(self.crawlers[0].calls[0]["max_pages"], MAX_PAGES_UNLIMITED)
        sent = self.processor.params[0]
        self.assertEqual(sent["strategy"], "all")
        self.assertEqual(sent["sample_size"], 3000)
        self.assertEqual(sent["batch_size"], 25)
        module_id = sent["custom_modules"][0]["id"]
        self.assertEqual(sent["chart_keys"], ["word_cloud", module_id])
        # A full analysis ignores sample_size, so no cost warning.
        warnings = result.structured_content["warnings"]
        self.assertEqual([w for w in warnings if "sample_size" in w], [], json.dumps(warnings, ensure_ascii=False))

    async def test_a_large_sample_warns_through_the_tool_result(self):
        service = self.make()
        self.mcp_server.set_service(service)
        async with Client(self.mcp_server.mcp, raise_exceptions=False) as client:
            result = await client.call_tool("crawl_and_analyze", {
                "url": "BV1xx411c7mD", "sample_size": 2500, "wait_seconds": 30,
            })
        self.assertEqual(self.processor.params[0]["sample_size"], 2500)
        self.assertTrue(any("sample_size=2500" in w for w in result.structured_content["warnings"]))


if __name__ == "__main__":
    unittest.main()
