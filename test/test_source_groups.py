import unittest
from unittest.mock import patch

import config
import web_app
from utils.source_groups import (
    AGENCIES_GROUP,
    GOVERNMENT_GROUP,
    NEWSPAPERS_GROUP,
    filter_news_by_group,
    source_group,
)


class SourceGroupTests(unittest.TestCase):
    def test_assigns_news_agencies_to_agencies_group(self):
        self.assertEqual(source_group("РИА Новости"), AGENCIES_GROUP)
        self.assertEqual(source_group("ТАСС"), AGENCIES_GROUP)
        self.assertEqual(source_group("Интерфакс"), AGENCIES_GROUP)
        self.assertEqual(source_group("Yonhap"), AGENCIES_GROUP)
        self.assertEqual(source_group("Киодо (共同通信)"), AGENCIES_GROUP)
        self.assertEqual(
            source_group("Yahoo! JAPAN · 時事通信"),
            AGENCIES_GROUP,
        )
        self.assertEqual(
            source_group("Yahoo! JAPAN · トップ"),
            AGENCIES_GROUP,
        )
        self.assertEqual(
            source_group("Yahoo! JAPAN · 新しい配信元"),
            AGENCIES_GROUP,
        )
        self.assertEqual(source_group("Независимая газета"), NEWSPAPERS_GROUP)
        self.assertEqual(source_group("Коммерсантъ"), NEWSPAPERS_GROUP)
        self.assertEqual(source_group("Известия"), NEWSPAPERS_GROUP)
        self.assertEqual(source_group("Российская газета"), NEWSPAPERS_GROUP)
        self.assertEqual(source_group("Ведомости"), NEWSPAPERS_GROUP)
        self.assertEqual(source_group("Красная звезда"), NEWSPAPERS_GROUP)
        self.assertEqual(
            source_group("Комсомольская правда"),
            NEWSPAPERS_GROUP,
        )
        self.assertEqual(source_group("МЧС"), GOVERNMENT_GROUP)
        self.assertEqual(source_group("Президент России"), GOVERNMENT_GROUP)

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
        self.assertEqual(config.YAHOO_UPDATE_INTERVAL, 600)
        self.assertEqual(config.KYODO_UPDATE_INTERVAL, 600)
        self.assertEqual(config.NEWSPAPER_UPDATE_HOUR, 8)


class SourceGroupPageTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        web_app.app.config["AUTH_DISABLED"] = True
        self.files = {
            "all_news.json": [
                {
                    "source": "МЧС",
                    "title": "Материал государственного ведомства",
                    "url": "https://mchs.gov.ru/news/1",
                    "date": "2026-07-29",
                },
                {
                    "source": "Президент России",
                    "title": "Материал сайта Президента России",
                    "url": "http://kremlin.ru/events/president/news/80509",
                    "date": "2026-08-11",
                    "article_paragraphs": [
                        "Официальный полный текст публикации Президента России."
                    ],
                },
                {
                    "source": "Минсельхоз",
                    "title": "Материал Минсельхоза",
                    "url": "https://mcx.gov.ru/press-service/news/test/",
                    "date": "2026-08-03",
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
                {
                    "source": "Yahoo! JAPAN · 時事通信",
                    "title": "Yahoo! JAPANのニュース",
                    "url": "https://news.yahoo.co.jp/articles/test-yahoo",
                    "date": "2026-08-20",
                    "section": "時事通信",
                    "summary": "Yahoo! JAPAN RSSの公式概要です。",
                },
                {
                    "source": "Независимая газета",
                    "title": "Материал свежего номера НГ",
                    "url": "https://www.ng.ru/world/2026-08-05/1_9553_test.html",
                    "date": "2026-08-05",
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
                    {"source": "Независимая газета", "status": "ok"},
                ],
            },
        }

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled

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
        self.assertIn("Yahoo! JAPANのニュース", html)
        self.assertIn('id="yahoo-source-toggle"', html)
        self.assertIn('aria-expanded="false"', html)
        self.assertIn("<span>Yahoo! JAPAN</span>", html)
        self.assertIn("<span>時事通信</span>", html)
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
        self.assertNotIn("Yahoo! JAPANのニュース", html)

    def test_multiple_sources_can_be_selected_together(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/agencies?source=%D0%A2%D0%90%D0%A1%D0%A1&"
                "source=%D0%98%D0%BD%D1%82%D0%B5%D1%80%D1%84%D0%B0%D0%BA%D1%81"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Материал ТАСС", html)
        self.assertIn("Материал Интерфакса", html)
        self.assertNotIn("Материал информационного агентства", html)
        self.assertNotIn("Yahoo! JAPANのニュース", html)
        self.assertIn("Выбрано источников: 2", html)
        self.assertIn('name="source" value="ТАСС"', html)
        self.assertIn('name="source" value="Интерфакс"', html)
        self.assertIn('data-source-filter="ТАСС"', html)
        self.assertIn('data-source-filter="Интерфакс"', html)
        self.assertIn("selectedSources.add(source)", html)
        self.assertIn("data-source-clear", html)

    def test_selected_yahoo_subsection_is_expanded(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/agencies/filter/Yahoo!%20JAPAN%20%C2%B7%20%E6%99%82%E4%BA%8B%E9%80%9A%E4%BF%A1"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn('class="source-list yahoo-expanded"', html)
        self.assertIn('aria-expanded="true"', html)

    def test_main_sections_are_rendered_inside_header(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        header_start = html.index('<header class="topbar">')
        header_end = html.index("</header>", header_start)
        header = html[header_start:header_end]
        self.assertIn("Госструктуры", header)
        self.assertIn("Информагентства", header)
        self.assertIn("Газеты", header)

    def test_newspapers_page_contains_only_newspaper_sources(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/newspapers")

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Свежие номера газет", html)
        self.assertIn("Материал свежего номера НГ", html)
        self.assertNotIn("Материал государственного ведомства", html)
        self.assertNotIn("Материал информационного агентства", html)

    def test_news_feed_is_paginated_by_20_items(self):
        self.files["all_news.json"] = [
            {
                "source": "Коммерсантъ",
                "title": f"Газетный материал {number:02d}",
                "url": f"https://www.kommersant.ru/doc/{number}",
                "date": "2026-08-11",
            }
            for number in range(80)
        ]
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            first = web_app.app.test_client().get("/newspapers")
            second = web_app.app.test_client().get("/newspapers?page=2")
            third = web_app.app.test_client().get("/newspapers?page=3")

        first_html = first.get_data(as_text=True)
        second_html = second.get_data(as_text=True)
        third_html = third.get_data(as_text=True)
        self.assertEqual(first_html.count('class="news-card '), 20)
        self.assertEqual(second_html.count('class="news-card '), 20)
        self.assertEqual(third_html.count('class="news-card '), 20)
        self.assertIn('aria-current="page">2</span>', second_html)
        self.assertIn("21–40 из 80", second_html)

    def test_server_search_covers_items_beyond_first_page(self):
        self.files["all_news.json"] = [
            {
                "source": "Коммерсантъ",
                "title": (
                    "Особый материал для поиска"
                    if number == 70
                    else f"Обычный материал {number:02d}"
                ),
                "url": f"https://www.kommersant.ru/doc/{number}",
                "date": "2026-08-11",
            }
            for number in range(80)
        ]
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/newspapers?q=%D0%9E%D1%81%D0%BE%D0%B1%D1%8B%D0%B9"
            )

        html = response.get_data(as_text=True)
        self.assertIn("Особый материал для поиска", html)
        self.assertEqual(html.count('class="news-card '), 1)
        self.assertIn("1–1 из 1", html)

    def test_minselkhoz_news_opens_original_page(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertIn(
            'href="https://mcx.gov.ru/press-service/news/test/" target="_blank"',
            html,
        )
        self.assertNotIn(
            "/article?url=https%3A%2F%2Fmcx.gov.ru%2Fpress-service%2Fnews%2Ftest%2F",
            html,
        )

    def test_header_contains_five_click_easter_egg(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertIn('id="brand-home"', html)
        self.assertIn("kyodo-easter-egg.webp", html)
        self.assertIn("if(brandClicks >= 5)", html)

    def test_coverage_names_problem_sources(self):
        self.files["parser_status.json"]["sources"].extend(
            [
                {
                    "source": "Минприроды",
                    "status": "error",
                    "error": "TimeoutError",
                },
                {
                    "source": "Минкульт",
                    "status": "empty",
                    "checked_at": "2026-08-11 14:00:00",
                },
            ]
        )
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertIn("Требуют внимания", html)
        self.assertIn("Минприроды", html)
        self.assertIn("Минкульт", html)
        self.assertIn("TimeoutError", html)

    def test_coverage_can_be_hidden_from_non_admin_user(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json), patch.object(
            web_app,
            "can_view_admin_diagnostics",
            return_value=False,
        ):
            response = web_app.app.test_client().get("/")

        html = response.get_data(as_text=True)
        self.assertNotIn("Сводка покрытия", html)

    def test_tass_article_uses_official_rss_summary(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/article?url=https%3A%2F%2Ftass.ru%2Fpolitika%2F123456"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Материал ТАСС", html)
        self.assertIn("Официальный анонс публикации ТАСС.", html)

    def test_yahoo_article_uses_official_rss_summary(self):
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._load_json,
        ), patch.object(
            web_app,
            "extract_article",
            return_value={
                "title": "Yahoo! JAPANのニュース",
                "paragraphs": [],
                "error": "Yahoo не отдал страницу",
            },
        ), patch.object(
            web_app,
            "load_cached_article",
            return_value=None,
        ), patch.object(
            web_app,
            "save_cached_article",
            return_value=None,
        ):
            response = web_app.app.test_client().get(
                "/article?url=https%3A%2F%2Fnews.yahoo.co.jp%2Farticles%2Ftest-yahoo"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Yahoo! JAPANのニュース", html)
        self.assertIn("Yahoo! JAPAN RSSの公式概要です。", html)

    def test_yahoo_article_loads_full_text_only_when_opened(self):
        full_article = {
            "title": "Yahoo! JAPANのニュース",
            "paragraphs": ["選択した記事の全文をオンデマンドで取得しました。"],
            "error": "",
        }
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._load_json,
        ), patch.object(
            web_app,
            "extract_article",
            return_value=full_article,
        ) as extractor, patch.object(
            web_app,
            "load_cached_article",
            return_value=None,
        ), patch.object(
            web_app,
            "save_cached_article",
            return_value=None,
        ):
            response = web_app.app.test_client().get(
                "/article?url=https%3A%2F%2Fnews.yahoo.co.jp%2Farticles%2Ftest-yahoo"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("選択した記事の全文をオンデマンドで取得しました。", html)
        self.assertNotIn("Yahoo! JAPAN RSSの公式概要です。", html)
        extractor.assert_called_once_with(
            "https://news.yahoo.co.jp/articles/test-yahoo",
            "Yahoo! JAPANのニュース",
        )

    def test_yahoo_polluted_cache_is_automatically_refreshed(self):
        polluted = {
            "title": "Yahoo! JAPANのニュース",
            "paragraphs": [
                "記事の本文です。",
                "1 ランキングの別の記事です。",
                "2 ランキングの二つ目の記事です。",
                "3 ランキングの三つ目の記事です。",
            ],
            "error": "",
        }
        cleaned = {
            "title": "Yahoo! JAPANのニュース",
            "paragraphs": ["再取得した記事のきれいな全文です。"],
            "error": "",
        }
        with patch.object(
            web_app,
            "load_json",
            side_effect=self._load_json,
        ), patch.object(
            web_app,
            "load_cached_article",
            return_value=polluted,
        ), patch.object(
            web_app,
            "extract_article",
            return_value=cleaned,
        ) as extractor, patch.object(
            web_app,
            "save_cached_article",
            return_value=None,
        ):
            response = web_app.app.test_client().get(
                "/article?url=https%3A%2F%2Fnews.yahoo.co.jp%2Farticles%2Ftest-yahoo"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("再取得した記事のきれいな全文です。", html)
        self.assertNotIn("ランキングの別の記事", html)
        extractor.assert_called_once()

    def test_kremlin_article_uses_full_atom_text(self):
        with patch.object(web_app, "load_json", side_effect=self._load_json):
            response = web_app.app.test_client().get(
                "/article?url=http%3A%2F%2Fkremlin.ru%2Fevents%2Fpresident%2Fnews%2F80509"
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn("Материал сайта Президента России", html)
        self.assertIn("Официальный полный текст публикации", html)


if __name__ == "__main__":
    unittest.main()
