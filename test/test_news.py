import unittest

from bs4 import BeautifulSoup

from utils.news import (
    deduplicate_news,
    is_valid_news_item,
    merge_news,
    normalize_url,
    sort_news_by_publication,
)
from utils.dates import (
    date_from_ancestors,
    date_from_document,
    date_from_news_card,
    parse_date,
    validate_publication_date,
)


class NormalizeUrlTests(unittest.TestCase):
    def test_removes_fragment_and_tracking_parameters(self):
        url = "HTTPS://Example.COM/news/1/?utm_source=test&id=3#top"
        self.assertEqual(normalize_url(url), "https://example.com/news/1?id=3")

    def test_preserves_root_slash(self):
        self.assertEqual(normalize_url("https://example.com"), "https://example.com/")

    def test_preserves_required_article_slashes(self):
        urls = (
            "https://mcx.gov.ru/press-service/news/test",
            "https://minstroyrf.gov.ru/press/test",
            "https://minvr.gov.ru/press-center/news/test",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertTrue(normalize_url(url).endswith("/"))


class DeduplicateNewsTests(unittest.TestCase):
    def test_removes_same_url_in_one_run(self):
        items = [
            {"source": "A", "title": "Первая версия", "url": "https://a.ru/news/1/"},
            {"source": "A", "title": "Вторая версия", "url": "https://a.ru/news/1"},
        ]
        self.assertEqual(len(deduplicate_news(items)), 1)

    def test_merges_date_into_existing_item(self):
        old = [{"source": "A", "title": "Новость", "url": "https://a.ru/1"}]
        new = [{
            "source": "A",
            "title": "Новость",
            "url": "https://a.ru/1/",
            "date": "2026-07-27",
        }]
        merged = merge_news(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["date"], "2026-07-27")

    def test_does_not_merge_different_urls(self):
        items = [
            {"source": "A", "title": "Новость", "url": "https://a.ru/news/1"},
            {"source": "A", "title": "Новость", "url": "https://a.ru/news/2"},
        ]
        self.assertEqual(len(deduplicate_news(items)), 2)

    def test_removes_known_service_links(self):
        items = [
            {
                "source": "Минэкономразвития",
                "title": "Официальная символика",
                "url": "https://economy.gov.ru/material/press/symbols/",
            },
            {
                "source": "Минэкономразвития",
                "title": "Настоящая новость",
                "url": "https://economy.gov.ru/material/news/real_news.html",
            },
        ]
        self.assertEqual(len(deduplicate_news(items)), 1)

    def test_removes_duplicate_source_title_with_different_urls(self):
        items = [
            {
                "source": "МЧС",
                "title": "Спасатели МЧС России провели учения",
                "url": "https://mchs.gov.ru/news/first",
            },
            {
                "source": "МЧС",
                "title": "Спасатели МЧС России — провели учения!",
                "url": "https://mchs.gov.ru/news/second",
            },
        ]
        self.assertEqual(len(deduplicate_news(items)), 1)

    def test_keeps_same_title_from_different_sources(self):
        items = [
            {
                "source": "МЧС",
                "title": "Ведомства провели совместное совещание",
                "url": "https://mchs.gov.ru/news/1",
            },
            {
                "source": "Минюст",
                "title": "Ведомства провели совместное совещание",
                "url": "https://minjust.gov.ru/news/1",
            },
        ]
        self.assertEqual(len(deduplicate_news(items)), 2)

    def test_merges_same_source_title_when_url_changes(self):
        old = [{
            "source": "Минэнерго",
            "title": "Министерство опубликовало новый доклад",
            "url": "https://minenergo.gov.ru/news/old",
        }]
        new = [{
            "source": "Минэнерго",
            "title": "Министерство опубликовало новый доклад",
            "url": "https://minenergo.gov.ru/news/new",
            "date": "2026-07-28",
        }]
        merged = merge_news(old, new)
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["date"], "2026-07-28")

    def test_replaces_cached_list_url_with_real_article_url(self):
        old = [{
            "source": "Минстрой",
            "title": "Министерство сообщило о новом проекте",
            "url": "https://minstroyrf.gov.ru/press/",
        }]
        new = [{
            "source": "Минстрой",
            "title": "Министерство сообщило о новом проекте",
            "url": (
                "https://minstroyrf.gov.ru/press/"
                "ministerstvo-soobshchilo-o-novom-proekte/"
            ),
            "date": "2026-07-29",
        }]
        merged = merge_news(old, new)
        self.assertEqual(len(merged), 1)
        self.assertIn(
            "ministerstvo-soobshchilo-o-novom-proekte",
            merged[0]["url"],
        )

    def test_rejects_list_url_for_fixed_sources(self):
        self.assertFalse(is_valid_news_item({
            "source": "Минтранс",
            "title": "Служебная запись",
            "url": "https://mintrans.gov.ru/press-center/news",
        }))

    def test_removes_impossible_future_publication_date(self):
        items = [{
            "source": "Сахалинская обл.",
            "title": "Новость с ошибочной датой",
            "url": "https://sakhalin.gov.ru/news/test/",
            "date": "2099-09-01",
        }]
        cleaned = deduplicate_news(items)
        self.assertEqual(cleaned[0]["date"], "")


class ParseDateTests(unittest.TestCase):
    def test_russian_date_without_year(self):
        now = __import__("datetime").datetime(2026, 7, 27)
        self.assertEqual(parse_date("27 июля, 11:30", now=now), "2026-07-27")

    def test_date_from_url(self):
        self.assertEqual(
            parse_date("https://site.ru/news/2026/07/15/title"),
            "2026-07-15",
        )

    def test_rejects_date_far_in_the_future(self):
        now = __import__("datetime").datetime(2026, 7, 29, 12, 0)
        self.assertEqual(
            validate_publication_date("1 сентября 2026", now=now),
            "",
        )

    def test_allows_one_day_for_timezone_difference(self):
        now = __import__("datetime").datetime(2026, 7, 29, 23, 30)
        self.assertEqual(
            validate_publication_date("30 июля 2026", now=now),
            "2026-07-30",
        )

    def test_strict_ancestor_ignores_event_date_in_title(self):
        soup = BeautifulSoup(
            """
            <article>
                <a id="news">Конференция состоится 1 сентября 2026 года</a>
            </article>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_ancestors(
                soup.select_one("#news"),
                strict=True,
                now=now,
            ),
            "",
        )

    def test_strict_ancestor_reads_only_card_date(self):
        soup = BeautifulSoup(
            """
            <section>
                <article>
                    <span class="publication-date">28 июля 2026</span>
                    <a id="first">Первая новость министерства</a>
                </article>
                <article>
                    <span class="publication-date">27 июля 2026</span>
                    <a>Вторая новость министерства</a>
                </article>
            </section>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_ancestors(
                soup.select_one("#first"),
                max_levels=5,
                strict=True,
                now=now,
            ),
            "2026-07-28",
        )

    def test_card_date_does_not_use_date_from_news_title(self):
        soup = BeautifulSoup(
            """
            <article>
                <time>29 июля 2026</time>
                <a id="news" href="/news/123">
                    Завершить ремонт к 1 сентября 2026 года
                </a>
            </article>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_news_card(
                soup.select_one("#news"),
                r"/news/",
                now=now,
            ),
            "2026-07-29",
        )

    def test_card_date_stops_before_neighboring_news(self):
        soup = BeautifulSoup(
            """
            <section>
                <div class="page-date">29 июля 2026</div>
                <article>
                    <a id="first" href="/press/101/first">Первая новость</a>
                </article>
                <article>
                    <a href="/press/102/second">Вторая новость</a>
                </article>
            </section>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_news_card(
                soup.select_one("#first"),
                r"/press/\d+",
                now=now,
            ),
            "",
        )

    def test_document_date_is_taken_from_publication_metadata(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-25T12:30:00+03:00">
                </head>
                <body>
                    <h1>Материал министерства</h1>
                    <p>В тексте упоминается заседание 29 июля 2026 года.</p>
                </body>
            </html>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_document(soup, now=now),
            "2026-07-25",
        )

    def test_visible_article_date_can_override_stale_metadata(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-28T12:30:00+03:00">
                </head>
                <body>
                    <article>
                        <h1>Сегодняшняя публикация</h1>
                        <time class="news-date">29 июля 2026, 10:15</time>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )
        now = __import__("datetime").datetime(2026, 7, 29)
        self.assertEqual(
            date_from_document(
                soup,
                now=now,
                prefer_visible=True,
            ),
            "2026-07-29",
        )


class PublicationSortingTests(unittest.TestCase):
    def test_publication_dates_come_first_and_descending(self):
        items = [
            {"title": "Без даты", "parsed_date": "2026-07-27 13:00"},
            {"title": "Старая", "date": "2026-07-20"},
            {"title": "Новая", "date": "2026-07-27"},
        ]
        sorted_items = sort_news_by_publication(items)
        self.assertEqual(
            [item["title"] for item in sorted_items],
            ["Новая", "Старая", "Без даты"],
        )

    def test_undated_items_use_parsed_date(self):
        items = [
            {"title": "Старая", "parsed_date": "2026-07-26 10:00"},
            {"title": "Новая", "parsed_date": "2026-07-27 10:00"},
        ]
        sorted_items = sort_news_by_publication(items)
        self.assertEqual(sorted_items[0]["title"], "Новая")


if __name__ == "__main__":
    unittest.main()
