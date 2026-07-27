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


if __name__ == "__main__":
    unittest.main()
