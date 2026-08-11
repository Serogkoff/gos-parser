import unittest
from datetime import datetime
from unittest.mock import patch

import main


class RecordingStopEvent:
    def __init__(self):
        self.stopped = False
        self.events = []

    def is_set(self):
        return self.stopped

    def wait(self, seconds):
        self.events.append(("wait", seconds))
        if sum(name == "wait" for name, *_ in self.events) >= 2:
            self.stopped = True


class DailyScheduleTests(unittest.TestCase):
    def test_waits_until_scheduled_hour_before_first_run(self):
        stop_event = RecordingStopEvent()
        fixed_now = datetime(2026, 8, 11, 23, 30)

        def record_run(*args, **kwargs):
            stop_event.events.append(("run",))

        class FixedDatetime:
            @classmethod
            def now(cls):
                return fixed_now

        with patch.object(main, "datetime", FixedDatetime), patch.object(
            main,
            "run_once",
            side_effect=record_run,
        ) as run_once:
            main.run_daily_schedule([], "Газеты", 8, stop_event)

        self.assertEqual(stop_event.events[0][0], "wait")
        self.assertEqual(stop_event.events[1][0], "run")
        self.assertEqual(stop_event.events[0][1], 8 * 60 * 60 + 30 * 60)
        run_once.assert_called_once_with(
            [],
            group_name="Газеты",
            merge_status=True,
        )


if __name__ == "__main__":
    unittest.main()
