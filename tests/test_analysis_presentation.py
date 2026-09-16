"""What the analysis hands back to a reader: prose, word frequencies, report.

These cover presentation defects found running the published package against
real comments: a reply's addressing markup leaking into the model input and the
word cloud, multi-batch prose glued into one impossible sentence, and a region
section that renders as an empty heading when nobody was logged in.
"""
import unittest
from unittest.mock import patch

from bilibili_crawler.processor.analysis_processor import LLMAnalysisProcessor as P


def comment(content, **extra):
    base = {
        "comment_id": 1,
        "is_reply": True,
        "username": "用户A",
        "user_level": 5,
        "content": content,
        "like_count": 0,
        "reply_count": 0,
        "ctime": 1735660800,
        "ctime_text": "2025-01-01 00:00:00",
        "ip_location": "",
    }
    base.update(extra)
    return base


class ReplyPrefixTests(unittest.TestCase):
    def test_the_addressing_prefix_is_dropped(self):
        cases = [
            ("回复 @吃货大魔法师 :我可是没ai那个时代的人", "我可是没ai那个时代的人"),
            ("回复 @fhjfjfghcjfdj : 现在有ai，可以随便学", "现在有ai，可以随便学"),
            ("回复 @某人：全角冒号也算", "全角冒号也算"),
            # The whole addressing run up to the colon is markup, not opinion.
            ("回复 @a @b :多个艾特都算前缀", "多个艾特都算前缀"),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                self.assertEqual(P._strip_reply_prefix(raw), expected)

    def test_ordinary_text_survives_untouched(self):
        for raw in [
            "回复很快的up主值得点赞",
            "我回复了他：他没理我",
            "这条评论提到 @某人 但不是回复开头",
            "",
        ]:
            with self.subTest(raw=raw):
                self.assertEqual(P._strip_reply_prefix(raw), raw.strip())

    def test_the_addressed_username_never_reaches_the_analysis_record(self):
        record = P._comment_record(comment("回复 @隐私用户名 :正文内容"))
        self.assertEqual(record["content"], "正文内容")
        self.assertNotIn("隐私用户名", record["content"])

    def test_the_prefix_no_longer_dominates_the_word_counts(self):
        records = [P._comment_record(comment(f"回复 @某人{i} :大学教育很重要")) for i in range(10)]
        words = {item["name"]: item["value"] for item in P._build_word_counts(records)}
        self.assertNotIn("回复", words)
        self.assertIn("大学", words)


class BatchProseTests(unittest.TestCase):
    """Driven through the real merge, so batch numbers come from real batches."""

    @staticmethod
    def sociology(*per_batch):
        """Merge one batch result per argument; None means the key was omitted."""
        results = [
            {} if text is None else {"deep_analysis": {"sociology": text}}
            for text in per_batch
        ]
        merged = P._merge_llm_results(
            results, [], 10, 10, 0, "all", ["deep_analysis"], None,
        )
        return merged["deep_analysis"]["sociology"]

    def test_batches_stay_separate_paragraphs_instead_of_one_sentence(self):
        merged = self.sociology("第一段结束。", "第二段结束。")
        # "。；" was the seam the old join produced.
        self.assertNotIn("。；", merged)
        self.assertEqual(merged, "（第 1 批）第一段结束。\n\n（第 2 批）第二段结束。")

    def test_a_single_batch_is_not_labelled(self):
        self.assertEqual(self.sociology("只有一段"), "只有一段")

    def test_identical_batches_collapse(self):
        self.assertEqual(self.sociology("同一段", "同一段"), "同一段")

    def test_a_duplicate_does_not_renumber_the_batches_after_it(self):
        # [A, A, C]: C came from batch 3 and must not be called batch 2.
        self.assertEqual(
            self.sociology("甲", "甲", "丙"),
            "（第 1 批）甲\n\n（第 3 批）丙",
        )

    def test_a_batch_that_said_nothing_does_not_renumber_the_rest(self):
        # The same drift without any duplicate: batch 1 omitted the key, so
        # list position and batch number disagreed before dedup ever ran.
        self.assertEqual(
            self.sociology(None, "乙", "丙"),
            "（第 2 批）乙\n\n（第 3 批）丙",
        )

    def test_empty_input_stays_empty(self):
        self.assertEqual(self.sociology(), "")
        self.assertEqual(self.sociology("", "  "), "")


class RegionSectionTests(unittest.TestCase):
    def result(self, ip_locations, region_counts):
        return {
            "summary": "总结",
            "overview": {"ip_locations": ip_locations},
            "region_counts": region_counts,
            "overseas_region_counts": [{"name": "未知", "value": 3}],
            "meta": {"chart_keys": ["region_map"], "ip_locations": ip_locations,
                     "total_records": 3, "analyzed_records": 3},
        }

    def test_an_empty_region_section_explains_itself(self):
        report = P._build_markdown_report(self.result(0, []))
        self.assertIn("### 国内 / 地图数据", report)
        body = report.split("### 国内 / 地图数据", 1)[1].split("### 海外", 1)[0]
        # An empty heading reads as a broken report.
        self.assertIn("登录", body)
        self.assertIn("暂无", body)
        # The desktop exports this same report; its users log in by QR code.
        self.assertNotIn("BILIBILI_COOKIE", body)

    def test_locations_present_but_none_domestic_says_so_instead(self):
        report = P._build_markdown_report(self.result(3, []))
        body = report.split("### 国内 / 地图数据", 1)[1].split("### 海外", 1)[0]
        self.assertNotIn("登录", body)
        self.assertIn("国内省份", body)

    def test_real_region_data_is_rendered_as_before(self):
        report = P._build_markdown_report(self.result(3, [{"name": "上海", "value": 2}]))
        body = report.split("### 国内 / 地图数据", 1)[1].split("### 海外", 1)[0]
        self.assertIn("上海", body)
        self.assertNotIn("暂无", body)


class RegionWarningTests(unittest.TestCase):
    """The warning rides the warnings channel the service forwards to callers.

    Driven through the real analyze(), with only the HTTP call replaced: a test
    that re-implemented the decision here would pass with the feature deleted.
    """

    def analyze(self, comments, chart_keys):
        with patch.object(P, "_call_llm", return_value={"summary": "总结"}):
            return P.analyze(
                comments,
                [],
                {
                    "source": "comments",
                    "strategy": "sample",
                    "chart_keys": chart_keys,
                    "llm_config": {"api_key": "sk-test", "model": "m", "base_url": "http://127.0.0.1:1/v1"},
                },
            )

    def test_warning_is_attached_when_no_comment_has_a_location(self):
        result = self.analyze([comment("正文", ip_location="") for _ in range(3)], ["region_map"])
        self.assertTrue(any("地域分布没有数据" in w for w in result.get("warnings", [])))
        # Shared with the desktop: how to log in is the service's call.
        self.assertFalse(any("BILIBILI_COOKIE" in w for w in result.get("warnings", [])))

    def test_no_warning_when_the_region_chart_was_not_requested(self):
        result = self.analyze([comment("正文", ip_location="") for _ in range(3)], ["topic_ranking"])
        self.assertEqual([w for w in result.get("warnings", []) if "地域分布" in w], [])

    def test_no_warning_when_locations_are_present(self):
        result = self.analyze([comment("正文", ip_location="上海") for _ in range(3)], ["region_map"])
        self.assertEqual([w for w in result.get("warnings", []) if "地域分布" in w], [])


if __name__ == "__main__":
    unittest.main()
