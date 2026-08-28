"""Direct tests for CSVExporter's cell sanitization and column contract."""
import csv
import tempfile
import unittest
from pathlib import Path

from src.exporter.csv_exporter import CSVExporter


class SanitizeCellTests(unittest.TestCase):
    def test_every_unsafe_prefix_gets_an_apostrophe(self) -> None:
        for prefix in ("=", "+", "-", "@", "\t", "\r"):
            with self.subTest(prefix=repr(prefix)):
                self.assertEqual(CSVExporter._sanitize_cell(prefix + "payload"), "'" + prefix + "payload")

    def test_safe_values_pass_through_untouched(self) -> None:
        self.assertEqual(CSVExporter._sanitize_cell("正常评论"), "正常评论")
        self.assertEqual(CSVExporter._sanitize_cell("——前排"), "——前排")  # em dash is not "-"
        self.assertEqual(CSVExporter._sanitize_cell(""), "")
        self.assertEqual(CSVExporter._sanitize_cell(123), 123)
        self.assertIsNone(CSVExporter._sanitize_cell(None))

    def test_new_columns_are_appended_at_the_tail(self) -> None:
        # Consumers that parse by column position (row[N]) rely on the
        # pre-existing indices staying stable across schema growth: the two
        # columns added most recently must sit at the end and in no other spot.
        self.assertEqual(CSVExporter.DEFAULT_COLUMNS[-2:], ["parent_id", "user_id"])
        self.assertEqual(
            [col for col in CSVExporter.DEFAULT_COLUMNS if col not in ("parent_id", "user_id")],
            ["comment_id", "root_id", "is_reply", "username", "user_level", "content",
             "like_count", "reply_count", "ctime_text", "ip_location"],
        )

    def test_export_writes_sanitized_cells(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "comments.csv"
            ok = CSVExporter.export(
                [
                    {
                        "comment_id": 1,
                        "content": "=1+1",
                        "username": "用户A",
                    }
                ],
                str(path),
            )
            self.assertTrue(ok)
            with path.open(encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
        content_idx = rows[0].index("评论内容")
        self.assertEqual(rows[1][content_idx], "'=1+1")


if __name__ == "__main__":
    unittest.main()
