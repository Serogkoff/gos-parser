import unittest

from utils.news import (
    deduplicate_news,
    merge_news,
    normalize_url,
    sort_news_by_publication,
)
from utils.dates import parse_date


class NormalizeUrlTests(unittest.TestCase):
    def test_removes_fragment_and_tracking_parameters(self):
        url = "HTTPS://Example.COM/news/1/?utm_source=test&id=3#top"
        self.assertEqual(normalize_url(url), "https://example.com/news/1?id=3")

    def test_preserves_root_slash(self):
        self.assertEqual(normalize_url("https://example.com"), "https://example.com/")


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


class ParseDateTests(unittest.TestCase):
    def test_russian_date_without_year(self):
        now = __import__("datetime").datetime(2026, 7, 27)
        self.assertEqual(parse_date("27 июля, 11:30", now=now), "2026-07-27")

    def test_date_from_url(self):
        self.assertEqual(
            parse_date("https://site.ru/news/2026/07/15/title"),
            "2026-07-15",
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
