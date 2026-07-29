import unittest
from unittest.mock import patch

import config
import web_app
from utils.source_groups import (
    AGENCIES_GROUP,
    GOVERNMENT_GROUP,
    filter_news_by_group,
    source_group,
)


class SourceGroupTests(unittest.TestCase):
    def test_assigns_ria_to_agencies(self):
        self.assertEqual(source_group("РИА Новости"), AGENCIES_GROUP)
        self.assertEqual(source_group("МЧС"), GOVERNMENT_GROUP)

    def test_filters_news_without_losing_fields(self):
        items = [
            {"source": "МЧС", "title": "Государственная новость"},
            {
                "source": "РИА Новости",
                "title": "Новость информагентства",
                "section": "Политика",
            },
        ]
        agency_news = filter_news_by_group(items, AGENCIES_GROUP)
        self.assertEqual(len(agency_news), 1)
        self.assertEqual(agency_news[0]["section"], "Политика")

    def test_update_intervals_are_independent(self):
        self.assertEqual(config.GOVERNMENT_UPDATE_INTERVAL, 300)
        self.assertEqual(config.AGENCY_UPDATE_INTERVAL, 180)


class SourceGroupPageTests(unittest.TestCase):
    def setUp(self):
        self.files = {
            "all_news.json": [
                {
                    "source": "МЧС",
                    "title": "Материал государственного ведомства",
                    "url": "https://mchs.gov.ru/news/1",
                    "date": "2026-07-29",
                },
                {
                    "source": "РИА Новости",
                    "title": "Материал информационного агентства",
                    "url": "https://ria.ru/20260729/test-1.html",
                    "date": "2026-07-29",
                    "section": "Политика",
                },
            ],
            "found_news.json": [],
            "parser_status.json": {
                "generated_at": "2026-07-29 15:00:00",
                "sources": [
                    {"source": "МЧС", "status": "ok"},
                    {"source": "РИА Новости", "status": "ok"},
                ],
            },
        }

    def _load_json(self, filename, default):
        return self.files.get(filename, default)

    def test_agency_page_contains_only_agency_sources(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/agencies")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Новости информагентств", html)
        self.assertIn("Материал информационного агентства", html)
        self.assertIn("Политика", html)
        self.assertNotIn("Материал государственного ведомства", html)

    def test_government_page_contains_only_government_sources(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Новости госорганов", html)
        self.assertIn("Материал государственного ведомства", html)
        self.assertNotIn("Материал информационного агентства", html)


if __name__ == "__main__":
    unittest.main()
