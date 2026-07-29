import unittest

from bs4 import BeautifulSoup

from parsers.sites.sk import (
    _article_id,
    _channel_dates_from_soup,
)


class SkPublicationDateTests(unittest.TestCase):
    def test_extracts_article_id_from_both_supported_urls(self):
        self.assertEqual(
            _article_id("https://sledcom.ru/news/item/2111623/"),
            "2111623",
        )
        self.assertEqual(
            _article_id("https://sledcom.ru/news/detail/2111557/?tab=video"),
            "2111557",
        )

    def test_matches_official_channel_date_to_article(self):
        soup = BeautifulSoup(
            """
            <div class="tgme_widget_message">
                <a href="https://sledcom.ru/news/item/2111557/">
                    Вчерашняя публикация
                </a>
                <time datetime="2026-07-28T17:09:00+03:00"></time>
            </div>
            <div class="tgme_widget_message">
                <a href="https://sledcom.ru/news/item/2111623/">
                    Сегодняшняя публикация
                </a>
                <time datetime="2026-07-29T06:11:00+03:00"></time>
            </div>
            """,
            "html.parser",
        )

        dates = _channel_dates_from_soup(soup)

        self.assertEqual(dates["2111557"], "2026-07-28")
        self.assertEqual(dates["2111623"], "2026-07-29")

    def test_ignores_date_outside_message(self):
        soup = BeautifulSoup(
            """
            <time datetime="2026-07-28T00:00:00+03:00"></time>
            <a href="https://sledcom.ru/news/item/2111623/">
                Публикация без собственной даты
            </a>
            """,
            "html.parser",
        )

        self.assertEqual(_channel_dates_from_soup(soup), {})


if __name__ == "__main__":
    unittest.main()
