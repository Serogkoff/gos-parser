import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import logger


class ErrorLogTests(unittest.TestCase):
    def test_reads_only_last_requested_log_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "parser_errors.log"
            path.write_text("\n".join(f"ошибка {number}" for number in range(20)), encoding="utf-8")
            with patch.object(logger, "ERROR_LOG_FILE", path):
                lines = logger.read_recent_errors(limit=3)
                stats = logger.error_log_stats()

        self.assertEqual(lines, ["ошибка 17", "ошибка 18", "ошибка 19"])
        self.assertGreater(stats["size_bytes"], 0)
        self.assertTrue(stats["modified_at"])

    def test_missing_log_is_reported_as_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "missing.log"
            with patch.object(logger, "ERROR_LOG_FILE", path):
                self.assertEqual(logger.read_recent_errors(), [])
                self.assertEqual(logger.error_log_stats()["size_bytes"], 0)

    def test_web_performance_log_is_separate_and_bounded(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "web_performance.log"
            path.write_text("старые замеры", encoding="utf-8")
            with (
                patch.object(logger, "WEB_PERFORMANCE_LOG_FILE", path),
                patch.object(logger, "PERFORMANCE_LOG_MAX_BYTES", 1),
            ):
                result = logger.write_web_performance(
                    "Лента route=/found total=12.3ms"
                )
            content = path.read_text(encoding="utf-8")

        self.assertTrue(result)
        self.assertNotIn("старые замеры", content)
        self.assertIn("Лента route=/found total=12.3ms", content)


if __name__ == "__main__":
    unittest.main()
