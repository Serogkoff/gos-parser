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
    def test_carnegie_uses_its_own_hourly_schedule(self):
        carnegie_names = [name for name, _parser in main.CARNEGIE_SITES]
        daily_names = [name for name, _parser in main.DAILY_NEWSPAPER_SITES]

        self.assertEqual(carnegie_names, ["Берлинский центр Карнеги"])
        self.assertNotIn("Берлинский центр Карнеги", daily_names)
        self.assertEqual(main.CARNEGIE_UPDATE_INTERVAL, 3600)

    def test_global_affairs_uses_its_own_two_hour_schedule(self):
        source_names = [name for name, _parser in main.GLOBAL_AFFAIRS_SITES]
        daily_names = [name for name, _parser in main.DAILY_NEWSPAPER_SITES]

        self.assertEqual(source_names, ["Россия в глобальной политике"])
        self.assertNotIn("Россия в глобальной политике", daily_names)
        self.assertEqual(main.GLOBAL_AFFAIRS_UPDATE_INTERVAL, 7200)

    def test_vpn_media_are_split_between_requested_intervals(self):
        self.assertEqual(
            [name for name, _parser in main.FAST_VPN_MEDIA_SITES],
            ["Meduza", "The Insider"],
        )
        self.assertEqual(
            [name for name, _parser in main.VPN_MEDIA_SITES],
            ["BBC Russian", "The Moscow Times", "Важные истории", "Вёрстка"],
        )

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

    def test_manual_vpn_media_update_contains_all_six_sources(self):
        with mock.patch.object(main, "run_once") as run_once:
            main.run_manual_group("vpn-media")

        sites = run_once.call_args.args[0]
        self.assertEqual(
            {name for name, _parser in sites},
            {
                "BBC Russian", "The Moscow Times", "Meduza",
                "Важные истории", "Вёрстка", "The Insider",
            },
        )
        self.assertEqual(
            run_once.call_args.kwargs["group_name"],
            "Газеты · VPN · ручное обновление",
        )

    def test_admin_queue_runs_source_once_and_finishes_job(self):
        class StopAfterIdle:
            stopped = False

            def is_set(self):
                return self.stopped

            def wait(self, _seconds):
                self.stopped = True

        job = {"id": 17, "source": "МЧС"}
        with (
            mock.patch.object(
                main,
                "claim_next_parser_job",
                side_effect=[job, None],
            ),
            mock.patch.object(main, "source_is_enabled", return_value=True),
            mock.patch.object(
                main,
                "run_once",
                return_value=[{"source": "МЧС", "status": "ok"}],
            ) as run_once,
            mock.patch.object(main, "finish_parser_job") as finish,
        ):
            main.run_admin_job_queue(StopAfterIdle())

        run_once.assert_called_once_with(
            [("МЧС", dict(main.SITES)["МЧС"])],
            group_name="МЧС · запуск из админ-панели",
            merge_status=True,
            wait_for_busy=True,
        )
        finish.assert_called_once_with(17, True, "")


if __name__ == "__main__":
    unittest.main()
