import unittest
from datetime import datetime
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import mvd


class MvdParserTests(unittest.TestCase):
    def test_reads_redesigned_cards_marked_today(self):
        soup = BeautifulSoup(
            """
            <section class="news-list">
              <article class="publication-card">
                <span class="publication-card__date">СЕГОДНЯ, 14:35</span>
                <h3 class="publication-card__title">
                  <a href="/news/item/999001/">
                    Сотрудники полиции сообщили о результатах операции
                  </a>
                </h3>
              </article>
            </section>
            """,
            "html.parser",
        )

        with mock.patch.object(mvd, "fetch_soup", return_value=soup):
            result = mvd.parse(now=datetime(2026, 8, 26, 15, 0))

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-26")
        self.assertEqual(
            result[0]["url"],
            "https://мвд.рф/news/item/999001/",
        )
        self.assertEqual(
            result[0]["title"],
            "Сотрудники полиции сообщили о результатах операции",
        )

    def test_rejects_lookalike_host(self):
        self.assertFalse(
            mvd._is_article_url(
                "https://evilxn--b1aew.xn--p1ai/news/item/999001"
            )
        )


if __name__ == "__main__":
    unittest.main()
