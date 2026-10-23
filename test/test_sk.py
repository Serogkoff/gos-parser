import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.sk import (
    _confirmed_date_from_sk_article,
    _date_from_sk_label,
    _date_from_sk_article,
    _load_date_cache,
    _save_date_cache,
)
from parsers.sites import sk


class SkPublicationDateTests(unittest.TestCase):
    def test_parse_caches_card_date_without_opening_article(self):
        soup = BeautifulSoup(
            """
            <div class="news-item">
                <div class="news-item__data">23 октября 2026</div>
                <a href="/news/item/300/">
                    Новая публикация Следственного комитета России
                </a>
            </div>
            """,
            "html.parser",
        )
        saved_cache = {}

        with (
            patch.object(sk, "fetch_soup", return_value=soup) as fetch_http,
            patch.object(sk, "fetch_soup_js") as fetch_browser,
            patch.object(sk, "_load_date_cache", return_value={}),
            patch.object(
                sk,
                "_save_date_cache",
                side_effect=lambda cache: saved_cache.update(cache),
            ),
        ):
            items = sk.parse()

        self.assertEqual(items[0]["date"], "2026-10-23")
        self.assertEqual(fetch_http.call_count, 1)
        fetch_browser.assert_not_called()
        self.assertEqual(
            saved_cache["https://sledcom.ru/news/item/300/"],
            "2026-10-23",
        )

    def test_parse_never_rechecks_cached_date(self):
        soup = BeautifulSoup(
            """
            <div class="news-item">
                <a href="/news/item/301/">
                    Известная публикация Следственного комитета России
                </a>
            </div>
            """,
            "html.parser",
        )

        with (
            patch.object(sk, "fetch_soup", return_value=soup) as fetch_http,
            patch.object(sk, "fetch_soup_js") as fetch_browser,
            patch.object(
                sk,
                "_load_date_cache",
                return_value={
                    "https://sledcom.ru/news/item/301/": "2026-10-23",
                },
            ),
            patch.object(sk, "_save_date_cache") as save_cache,
        ):
            items = sk.parse()

        self.assertEqual(items[0]["date"], "2026-10-23")
        self.assertEqual(fetch_http.call_count, 1)
        fetch_browser.assert_not_called()
        save_cache.assert_not_called()

    def test_parse_limits_browser_date_fallback_to_one_article(self):
        soup = BeautifulSoup(
            """
            <div class="news-item">
                <a href="/news/item/302/">
                    Первая публикация Следственного комитета России
                </a>
            </div>
            <div class="news-item">
                <a href="/news/item/303/">
                    Вторая публикация Следственного комитета России
                </a>
            </div>
            """,
            "html.parser",
        )

        with (
            patch.object(
                sk,
                "fetch_soup",
                side_effect=[soup, None, None],
            ) as fetch_http,
            patch.object(sk, "fetch_soup_js", return_value=None) as browser,
            patch.object(sk, "_load_date_cache", return_value={}),
            patch.object(sk, "_save_date_cache"),
            patch.object(sk.time, "sleep"),
        ):
            items = sk.parse()

        self.assertEqual(len(items), 2)
        self.assertEqual(fetch_http.call_count, 3)
        self.assertEqual(browser.call_count, 1)

    def test_relative_sk_dates(self):
        now = datetime(2026, 8, 6, 13, 0)
        self.assertEqual(
            _date_from_sk_label("Сегодня", now=now),
            "2026-08-06",
        )
        self.assertEqual(
            _date_from_sk_label("Вчера", now=now),
            "2026-08-05",
        )

    def test_confirmed_date_uses_relative_date_from_detail_card(self):
        soup = BeautifulSoup(
            """
            <html><body>
                <h1>Новости</h1>
                <div class="news-card">
                    <div class="news-card__title-text">
                        Нужная публикация СК России
                    </div>
                    <div class="news-card__data">Сегодня</div>
                </div>
            </body></html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _confirmed_date_from_sk_article(
                soup,
                expected_title="Нужная публикация СК России",
            ),
            datetime.now().strftime("%Y-%m-%d"),
        )

    def test_confirmed_date_uses_matching_json_ld(self):
        soup = BeautifulSoup(
            """
            <html><body>
                <h1>Новости</h1>
                <script type="application/ld+json">
                {
                    "@type": "NewsArticle",
                    "headline": "Нужная публикация СК России",
                    "datePublished": "2026-08-06T10:15:00+03:00"
                }
                </script>
                <div class="news-item__date">05 Августа 2026</div>
            </body></html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _confirmed_date_from_sk_article(
                soup,
                expected_title="Нужная публикация СК России",
            ),
            "2026-08-06",
        )

    def test_confirmed_date_rejects_date_from_generic_news_card(self):
        soup = BeautifulSoup(
            """
            <html>
                <head><title>Новости - Следственный комитет</title></head>
                <body>
                    <h1>Новости</h1>
                    <article>
                        <div class="news-item__date">05 Августа 2026</div>
                        <a href="/news/item/222/">Нужная публикация СК России</a>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _confirmed_date_from_sk_article(
                soup,
                expected_title="Нужная публикация СК России",
            ),
            "",
        )

    def test_uses_date_displayed_on_article_page(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-27T18:20:00+03:00">
                </head>
                <body>
                    <div class="page-date">29 июля 2026</div>
                    <article>
                        <h1>Публикация Следственного комитета</h1>
                        <div class="news-item__date">28 Июля 2026</div>
                        <div class="news-item__time">18:20</div>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(soup),
            "2026-07-28",
        )

    def test_generic_news_page_uses_date_of_requested_card(self):
        soup = BeautifulSoup(
            """
            <html>
                <head><title>Новости - Следственный комитет</title></head>
                <body>
                    <h1>Новости</h1>
                    <article>
                        <div class="news-item__date">02 Августа 2026</div>
                        <a href="/news/item/111/">Соседняя публикация</a>
                    </article>
                    <article>
                        <div class="news-item__date">03 Августа 2026</div>
                        <a href="/news/item/222/">Нужная публикация СК России</a>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(
                soup,
                expected_title="Нужная публикация СК России",
                article_url="https://sledcom.ru/news/item/222/",
            ),
            "2026-08-03",
        )

    def test_generic_news_page_never_uses_neighbor_date(self):
        soup = BeautifulSoup(
            """
            <html>
                <head><title>Новости - Следственный комитет</title></head>
                <body>
                    <h1>Новости</h1>
                    <article>
                        <div class="news-item__date">02 Августа 2026</div>
                        <a href="/news/item/111/">Соседняя публикация</a>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(
                soup,
                expected_title="Искомая публикация",
                article_url="https://sledcom.ru/news/item/222/",
            ),
            "",
        )

    def test_article_metadata_is_used_only_for_matching_article(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="og:title" content="Нужная публикация">
                    <meta property="article:published_time"
                          content="2026-08-04T11:20:00+03:00">
                </head>
                <body><h1>Новости</h1></body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(
                soup,
                expected_title="Нужная публикация",
                article_url="https://sledcom.ru/news/item/222/",
            ),
            "2026-08-04",
        )

    def test_falls_back_to_publication_metadata(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-29T10:15:00+03:00">
                </head>
                <body>
                    <h1>Другой шаблон страницы СК</h1>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(soup),
            "2026-07-29",
        )

    def test_returns_empty_date_when_article_is_unavailable(self):
        self.assertEqual(_date_from_sk_article(None), "")

    def test_date_cache_preserves_normalized_article_url(self):
        with TemporaryDirectory() as directory:
            cache_file = Path(directory) / "sk_dates.json"
            with patch(
                "parsers.sites.sk.DATE_CACHE_FILE",
                cache_file,
            ):
                _save_date_cache({
                    "https://sledcom.ru/news/item/2111766": "2026-07-29",
                })
                cache = _load_date_cache()

        self.assertEqual(
            cache["https://sledcom.ru/news/item/2111766/"],
            "2026-07-29",
        )


if __name__ == "__main__":
    unittest.main()
