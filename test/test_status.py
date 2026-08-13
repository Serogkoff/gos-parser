import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from utils import status


class ParserStatusTests(unittest.TestCase):
    def test_preserves_last_success_after_empty_run(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser_status.json"
            with patch.object(status, "STATUS_FILE", path):
                first = status.save_parser_status(
                    [{
                        "source": "Источник",
                        "status": "ok",
                        "news_count": 5,
                        "with_date": 5,
                        "matches_count": 1,
                        "duration_seconds": 1.0,
                        "error": "",
                    }],
                    "test",
                    now=datetime(2026, 7, 27, 10, 0),
                )
                second = status.save_parser_status(
                    [{
                        "source": "Источник",
                        "status": "empty",
                        "news_count": 0,
                        "with_date": 0,
                        "matches_count": 0,
                        "duration_seconds": 1.0,
                        "error": "",
                    }],
                    "test",
                    now=datetime(2026, 7, 27, 11, 0),
                )

        self.assertEqual(first["summary"]["ok"], 1)
        self.assertEqual(
            second["sources"][0]["last_success"],
            "2026-07-27 10:00:00",
        )
        self.assertEqual(second["sources"][0]["failure_streak"], 1)
        self.assertEqual(second["sources"][0]["availability"], "temporary")

    def test_marks_long_failure_as_down_and_resets_after_success(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser_status.json"
            with patch.object(status, "STATUS_FILE", path):
                status.save_parser_status(
                    [{"source": "Источник", "status": "ok"}],
                    "test",
                    now=datetime(2026, 7, 27, 10, 0),
                )
                failed = status.save_parser_status(
                    [{"source": "Источник", "status": "error"}],
                    "test",
                    now=datetime(2026, 7, 29, 10, 1),
                )
                restored = status.save_parser_status(
                    [{"source": "Источник", "status": "ok"}],
                    "test",
                    now=datetime(2026, 7, 29, 10, 2),
                )

        self.assertEqual(failed["sources"][0]["availability"], "down")
        self.assertEqual(restored["sources"][0]["availability"], "ok")
        self.assertEqual(restored["sources"][0]["failure_streak"], 0)

    def test_merges_independent_source_groups(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser_status.json"
            with patch.object(status, "STATUS_FILE", path):
                status.save_parser_status(
                    [{
                        "source": "Правительство РФ",
                        "status": "ok",
                        "news_count": 5,
                        "with_date": 5,
                        "matches_count": 1,
                        "duration_seconds": 1.0,
                        "error": "",
                    }],
                    "test",
                    now=datetime(2026, 7, 29, 10, 0),
                    merge=True,
                )
                merged = status.save_parser_status(
                    [{
                        "source": "РИА Новости",
                        "status": "ok",
                        "news_count": 20,
                        "with_date": 20,
                        "matches_count": 2,
                        "duration_seconds": 2.0,
                        "error": "",
                    }],
                    "test",
                    now=datetime(2026, 7, 29, 10, 3),
                    merge=True,
                )

        self.assertEqual(merged["summary"]["total_sources"], 2)
        self.assertEqual(
            {item["source"] for item in merged["sources"]},
            {"Правительство РФ", "РИА Новости"},
        )


if __name__ == "__main__":
    unittest.main()
