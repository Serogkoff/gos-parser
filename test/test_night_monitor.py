import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest


def _load_module():
    fake_psutil = types.SimpleNamespace(
        NoSuchProcess=type("NoSuchProcess", (Exception,), {}),
        AccessDenied=type("AccessDenied", (Exception,), {}),
        ZombieProcess=type("ZombieProcess", (Exception,), {}),
    )
    previous = sys.modules.get("psutil")
    sys.modules["psutil"] = fake_psutil
    try:
        path = Path(__file__).parents[1] / "scripts" / "night_monitor.py"
        spec = importlib.util.spec_from_file_location("night_monitor", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("psutil", None)
        else:
            sys.modules["psutil"] = previous


night_monitor = _load_module()


class NightMonitorTests(unittest.TestCase):
    def test_child_parser_always_uses_utf8_for_redirected_log(self):
        environment = night_monitor._child_environment()

        self.assertEqual(environment["PYTHONIOENCODING"], "utf-8")
        self.assertEqual(environment["PYTHONUTF8"], "1")

    def test_process_kind_separates_python_and_browser(self):
        self.assertEqual(night_monitor._kind("python.exe"), "python")
        self.assertEqual(night_monitor._kind("chrome.exe"), "browser")
        self.assertEqual(night_monitor._kind("conhost.exe"), "other")

    def test_database_stats_reads_counts_without_writing(self):
        import sqlite3

        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "news.db"
            connection = sqlite3.connect(database)
            try:
                connection.execute("CREATE TABLE news_items (id INTEGER)")
                connection.execute("CREATE TABLE found_items (id INTEGER)")
                connection.executemany(
                    "INSERT INTO news_items VALUES (?)",
                    [(1,), (2,), (3,)],
                )
                connection.execute("INSERT INTO found_items VALUES (1)")
                connection.commit()
            finally:
                connection.close()

            stats = night_monitor._database_stats(database)

        self.assertEqual(stats["news_count"], 3)
        self.assertEqual(stats["found_count"], 1)
        self.assertGreater(stats["database_mb"], 0)

    def test_summary_reports_memory_growth_and_peak(self):
        rows = [
            {
                "elapsed_seconds": 0,
                "tree_rss_mb": 100,
                "browser_rss_mb": 20,
                "system_memory_percent": 40,
            },
            {
                "elapsed_seconds": 3600,
                "tree_rss_mb": 145,
                "browser_rss_mb": 70,
                "system_memory_percent": 55,
            },
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "summary.json"
            summary = night_monitor._write_summary(
                path,
                rows,
                night_monitor.datetime.now(),
                0,
                "test",
            )
            saved = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(summary["tree_rss_growth_mb"], 45)
        self.assertEqual(saved["tree_rss_max_mb"], 145)
        self.assertEqual(saved["browser_rss_max_mb"], 70)


if __name__ == "__main__":
    unittest.main()
