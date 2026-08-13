import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from utils import storage


class SourceIncidentTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.patchers = (
            patch.object(storage, "DATABASE_FILE", directory / "news.db"),
            patch.object(storage, "ALL_NEWS_FILE", directory / "all_news.json"),
            patch.object(storage, "FOUND_NEWS_FILE", directory / "found_news.json"),
            patch.object(storage, "BACKUP_DIR", directory / "backups"),
        )
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        for patcher in reversed(self.patchers):
            patcher.stop()
        self.temporary.cleanup()

    @staticmethod
    def status(state, streak=0, error=""):
        return [{
            "source": "МЧС",
            "status": state,
            "failure_streak": streak,
            "error": error,
        }]

    def test_repeated_failure_escalates_and_success_closes_incident(self):
        opened = storage.sync_source_incidents(
            self.status("error", 1, "HTTP 503"),
            now=datetime(2026, 8, 13, 10, 0),
        )
        updated = storage.sync_source_incidents(
            self.status("error", 3, "HTTP 503"),
            now=datetime(2026, 8, 13, 10, 10),
        )
        active = storage.list_source_incidents("active")

        self.assertEqual(opened["opened"], 1)
        self.assertEqual(updated["updated"], 1)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["level"], "critical")
        self.assertEqual(active[0]["checks_count"], 2)
        self.assertIn("HTTP 503", active[0]["message"])

        closed = storage.sync_source_incidents(
            self.status("ok"),
            now=datetime(2026, 8, 13, 10, 25),
        )
        resolved = storage.list_source_incidents("resolved")

        self.assertEqual(closed["resolved"], 1)
        self.assertEqual(storage.list_source_incidents("active"), [])
        self.assertEqual(resolved[0]["duration_seconds"], 25 * 60)
        self.assertEqual(resolved[0]["resolution"], "Работа восстановлена")

    def test_change_from_empty_to_error_creates_separate_incidents(self):
        storage.sync_source_incidents(
            self.status("empty", 1),
            now=datetime(2026, 8, 13, 9, 0),
        )
        changed = storage.sync_source_incidents(
            self.status("error", 2, "Timeout"),
            now=datetime(2026, 8, 13, 9, 5),
        )

        incidents = storage.list_source_incidents("all")
        self.assertEqual(changed, {"opened": 1, "updated": 0, "resolved": 1})
        self.assertEqual(len(incidents), 2)
        self.assertEqual({item["code"] for item in incidents}, {"empty", "error"})

    def test_disabling_source_closes_active_incident(self):
        storage.sync_source_incidents(
            self.status("empty", 1),
            now=datetime(2026, 8, 13, 8, 0),
        )
        storage.sync_source_incidents(
            self.status("disabled"),
            now=datetime(2026, 8, 13, 8, 3),
        )

        incident = storage.list_source_incidents("resolved")[0]
        self.assertEqual(incident["resolution"], "Источник отключён")

    def test_statistics_count_active_critical_and_recent_resolution(self):
        storage.sync_source_incidents(
            self.status("error", 3),
            now=datetime(2026, 8, 13, 10, 0),
        )
        stats = storage.source_incident_statistics(
            now=datetime(2026, 8, 13, 11, 0),
        )
        self.assertEqual(stats["total"], 1)
        self.assertEqual(stats["active"], 1)
        self.assertEqual(stats["critical"], 1)
        self.assertEqual(stats["resolved_24h"], 0)

    def test_reliability_uses_incident_duration_and_includes_clean_sources(self):
        storage.sync_source_incidents(
            self.status("error", 1),
            now=datetime(2026, 8, 10, 10, 0),
        )
        storage.sync_source_incidents(
            self.status("ok"),
            now=datetime(2026, 8, 10, 22, 0),
        )

        rows = storage.source_reliability_statistics(
            days=1,
            now=datetime(2026, 8, 11, 10, 0),
            sources=["МЧС", "МИД РФ"],
        )
        by_source = {item["source"]: item for item in rows}

        self.assertEqual(by_source["МЧС"]["downtime_seconds"], 12 * 3600)
        self.assertEqual(by_source["МЧС"]["uptime_percent"], 50.0)
        self.assertEqual(by_source["МЧС"]["incident_count"], 1)
        self.assertEqual(by_source["МИД РФ"]["uptime_percent"], 100.0)

    def test_reliability_clips_active_incident_to_selected_period(self):
        storage.sync_source_incidents(
            self.status("empty", 3),
            now=datetime(2026, 8, 1, 10, 0),
        )

        row = storage.source_reliability_statistics(
            days=7,
            now=datetime(2026, 8, 13, 10, 0),
            sources=["МЧС"],
        )[0]

        self.assertEqual(row["downtime_seconds"], 7 * 86400)
        self.assertEqual(row["uptime_percent"], 0.0)
        self.assertEqual(row["active_count"], 1)


if __name__ == "__main__":
    unittest.main()
