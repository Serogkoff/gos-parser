import unittest
from datetime import datetime

from utils.diagnostics import alert_summary, source_alerts, system_alerts


NOW = datetime(2026, 8, 13, 12, 0, 0)


def source(**changes):
    item = {
        "source": "РИА Новости",
        "group_label": "Информагентства",
        "enabled": True,
        "status_class": "ok",
        "checked_at": "2026-08-13 11:57:00",
        "last_received": "2026-08-13 11:55:00",
        "total_news": 100,
        "failure_streak": 0,
        "error": "",
    }
    item.update(changes)
    return item


class DiagnosticsTests(unittest.TestCase):
    def test_healthy_source_has_no_alerts(self):
        self.assertEqual(source_alerts([source()], now=NOW), [])

    def test_empty_result_is_warning_and_repeated_empty_is_critical(self):
        warning = source_alerts([
            source(status_class="empty", failure_streak=1),
        ], now=NOW)
        critical = source_alerts([
            source(status_class="empty", failure_streak=3),
        ], now=NOW)

        self.assertEqual(warning[0]["code"], "empty-result")
        self.assertEqual(warning[0]["level"], "warning")
        self.assertEqual(critical[0]["level"], "critical")

    def test_repeated_error_is_critical_and_keeps_reason(self):
        alerts = source_alerts([
            source(
                status_class="error",
                failure_streak=4,
                error="HTTP 403",
            ),
        ], now=NOW)

        self.assertEqual(alerts[0]["code"], "source-error")
        self.assertEqual(alerts[0]["level"], "critical")
        self.assertIn("HTTP 403", alerts[0]["message"])

    def test_stale_schedule_is_grouped_instead_of_spamming(self):
        stale = [
            source(
                source=f"Агентство {number}",
                checked_at="2026-08-13 10:00:00",
            )
            for number in range(4)
        ]

        alerts = source_alerts(stale, now=NOW)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["code"], "stale-schedule")
        self.assertEqual(alerts[0]["level"], "critical")
        self.assertIn("main.py", alerts[0]["message"])

    def test_no_news_threshold_depends_on_group(self):
        agency = source(last_received="2026-08-12 20:00:00")
        ministry = source(
            source="Минздрав",
            group_label="Госструктуры",
            last_received="2026-08-12 20:00:00",
        )

        alerts = source_alerts([agency, ministry], now=NOW)

        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]["subject"], "РИА Новости")
        self.assertEqual(alerts[0]["code"], "no-new-materials")

    def test_disabled_source_is_not_diagnosed(self):
        alerts = source_alerts([
            source(enabled=False, status_class="error", failure_streak=20),
        ], now=NOW)
        self.assertEqual(alerts, [])

    def test_system_reports_database_and_missing_backup(self):
        alerts = system_alerts(
            {"integrity": "malformed", "json_migrated": True},
            [],
            now=NOW,
        )

        self.assertEqual(alert_summary(alerts)["critical"], 2)
        self.assertEqual(
            {item["code"] for item in alerts},
            {"database-integrity", "no-backup"},
        )

    def test_system_reports_stale_backup_but_not_recent_one(self):
        database = {"integrity": "ok", "json_migrated": True}
        stale = [{"modified_at": "2026-08-11T20:00:00"}]
        recent = [{"modified_at": "2026-08-13T08:00:00"}]

        self.assertEqual(
            system_alerts(database, stale, now=NOW)[0]["code"],
            "stale-backup",
        )
        self.assertEqual(system_alerts(database, recent, now=NOW), [])


if __name__ == "__main__":
    unittest.main()
