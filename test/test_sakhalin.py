import unittest
from datetime import datetime
from unittest import mock

from parsers.sites import sakhalin


class SakhalinApiTests(unittest.TestCase):
    NOW = datetime(2026, 8, 20, 12, 0)

    def test_parses_json_api_and_builds_https_article_urls(self):
        payload = {
            "data": [
                {
                    "id": 101,
                    "date": "2026-08-17 13:59:00",
                    "name": "  На Сахалине открыли новый социальный объект  ",
                    "slug": "/news/novyy-sotsialnyy-obekt",
                },
                {
                    "id": 100,
                    "date": "2026-08-16 09:10:00",
                    "name": "Правительство области подвело итоги недели",
                    "slug": "http://sakhalin.gov.ru/news/itogi-nedeli",
                },
            ],
            "links": {"next": None},
        }

        with mock.patch.object(
            sakhalin,
            "fetch_json",
            return_value=payload,
        ) as fetch:
            result = sakhalin.parse(now=self.NOW)

        self.assertEqual(
            result,
            [
                {
                    "source": sakhalin.SOURCE_NAME,
                    "title": "На Сахалине открыли новый социальный объект",
                    "url": "https://sakhalin.gov.ru/news/novyy-sotsialnyy-obekt",
                    "date": "2026-08-17",
                },
                {
                    "source": sakhalin.SOURCE_NAME,
                    "title": "Правительство области подвело итоги недели",
                    "url": "https://sakhalin.gov.ru/news/itogi-nedeli",
                    "date": "2026-08-16",
                },
            ],
        )
        self.assertFalse(fetch.call_args.kwargs["verify"])

    def test_follows_cursor_and_stops_when_old_news_is_reached(self):
        first_page = {
            "data": [self._item(3, "2026-08-19 08:00:00")],
            "links": {
                "next": "http://sakhalin.gov.ru/api/news?cursor=second"
            },
        }
        second_page = {
            "data": [
                self._item(2, "2026-08-18 08:00:00"),
                self._item(1, "2026-07-01 08:00:00"),
                self._item(0, "2026-08-17 08:00:00"),
            ],
            "links": {
                "next": "http://sakhalin.gov.ru/api/news?cursor=third"
            },
        }

        with mock.patch.object(
            sakhalin,
            "fetch_json",
            side_effect=[first_page, second_page],
        ) as fetch:
            result = sakhalin.parse(now=self.NOW)

        self.assertEqual([item["date"] for item in result], ["2026-08-19", "2026-08-18"])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            fetch.call_args_list[1].args[0],
            "https://sakhalin.gov.ru/api/news?cursor=second",
        )

    def test_rejects_next_url_from_another_domain(self):
        payload = {
            "data": [self._item(1, "2026-08-19 08:00:00")],
            "links": {
                "next": "https://example.com/api/news?cursor=stolen"
            },
        }

        with mock.patch.object(
            sakhalin,
            "fetch_json",
            return_value=payload,
        ) as fetch:
            result = sakhalin.parse(now=self.NOW)

        self.assertEqual(len(result), 1)
        fetch.assert_called_once()

    @staticmethod
    def _item(item_id, date):
        return {
            "id": item_id,
            "date": date,
            "name": f"Свежая новость Сахалинской области номер {item_id}",
            "slug": f"/news/item-{item_id}",
        }


if __name__ == "__main__":
    unittest.main()
