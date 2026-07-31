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
    def test_assigns_news_agencies_to_agencies_group(self):
        self.assertEqual(source_group("РИА Новости"), AGENCIES_GROUP)
        self.assertEqual(source_group("ТАСС"), AGENCIES_GROUP)
        self.assertEqual(source_group("Интерфакс"), AGENCIES_GROUP)
        self.assertEqual(source_group("Yonhap"), AGENCIES_GROUP)
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
                {
                    "source": "ТАСС",
                    "title": "Материал ТАСС",
                    "url": "https://tass.ru/politika/123456",
                    "date": "2026-07-29",
                    "section": "Политика",
                    "summary": "Официальный анонс публикации ТАСС.",
                },
                {
                    "source": "Интерфакс",
                    "title": "Материал Интерфакса",
                    "url": "https://www.interfax.ru/russia/1106527",
                    "date": "2026-07-30",
                    "section": "В России",
                },
            ],
            "found_news.json": [],
            "parser_status.json": {
                "generated_at": "2026-07-29 15:00:00",
                "sources": [
                    {"source": "МЧС", "status": "ok"},
                    {"source": "РИА Новости", "status": "ok"},
                    {"source": "ТАСС", "status": "ok"},
                    {"source": "Интерфакс", "status": "ok"},
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
        self.assertIn("Госструктуры", html)
        self.assertIn("Материал информационного агентства", html)
        self.assertIn("Материал ТАСС", html)
        self.assertIn("Материал Интерфакса", html)
        self.assertIn("Политика", html)
        self.assertNotIn("Материал государственного ведомства", html)

    def test_government_page_contains_only_government_sources(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Новости госструктур", html)
        self.assertIn("Материал государственного ведомства", html)
        self.assertNotIn("Материал информационного агентства", html)

    def test_main_sections_are_rendered_inside_header(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        header_start = html.index('<header class="topbar">')
        header_end = html.index("</header>", header_start)
        header = html[header_start:header_end]
        self.assertIn("Госструктуры", header)
        self.assertIn("Информагентства", header)

    def test_header_contains_five_click_easter_egg(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertIn('id="brand-home"', html)
        self.assertIn("kyodo-easter-egg.webp", html)
        self.assertIn("if(brandClicks >= 5)", html)

    def test_tass_article_uses_official_rss_summary(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/article?url=https%3A%2F%2Ftass.ru%2Fpolitika%2F123456"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Материал ТАСС", html)
        self.assertIn("Официальный анонс публикации ТАСС.", html)


if __name__ == "__main__":
    unittest.main()
