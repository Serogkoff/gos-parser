import time
import unittest
from unittest import mock

import main
from utils.parser_runner import (
    ParserExecutionError,
    ParserTimeoutError,
    run_parser_with_timeout,
)


def _quick_parser():
    return [{"title": "Готово"}]


def _slow_parser():
    time.sleep(5)
    return []


def _broken_parser():
    raise ValueError("тестовая ошибка")


class NightStabilityTests(unittest.TestCase):
    def test_parser_result_crosses_process_boundary(self):
        self.assertEqual(
            run_parser_with_timeout(_quick_parser, 3),
            [{"title": "Готово"}],
        )

    def test_hung_parser_is_stopped(self):
        started = time.monotonic()
        with self.assertRaises(ParserTimeoutError):
            run_parser_with_timeout(_slow_parser, 1)
        self.assertLess(time.monotonic() - started, 4)

    def test_parser_exception_is_reported(self):
        with self.assertRaisesRegex(ParserExecutionError, "тестовая ошибка"):
            run_parser_with_timeout(_broken_parser, 3)

    def test_failed_group_uses_capped_exponential_backoff(self):
        self.assertEqual(main._schedule_delay(600, 0, True, 3600), 600)
        self.assertEqual(main._schedule_delay(600, 1, True, 3600), 1200)
        self.assertEqual(main._schedule_delay(600, 2, True, 3600), 2400)
        self.assertEqual(main._schedule_delay(600, 3, True, 3600), 3600)
        self.assertEqual(main._schedule_delay(600, 8, True, 3600), 3600)

    def test_manual_newspaper_update_writes_results_immediately(self):
        with mock.patch.object(main, "run_once") as run_once:
            main.run_manual_group("newspapers")

        run_once.assert_called_once_with(
            main.NEWSPAPER_SITES,
            group_name="Газеты · ручное обновление",
            merge_status=True,
        )


if __name__ == "__main__":
    unittest.main()
