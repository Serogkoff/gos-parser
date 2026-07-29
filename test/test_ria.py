import unittest
from datetime import datetime

from bs4 import BeautifulSoup

from parsers.sites.ria import _parse_ria_cards, _parse_ria_date


class RiaDateTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 29, 16, 0)

    def test_reads_publication_date_from_article_url(self):
        self.assertEqual(
            _parse_ria_date(
                "https://ria.ru/20260724/novost-123.html",
                "15:30",
                now=self.now,
            ),
            "2026-07-24",
        )

    def test_uses_today_for_time_only(self):
        self.assertEqual(
            _parse_ria_date(
                "https://ria.ru/novost-123.html",
                "15:30",
                now=self.now,
            ),
            "2026-07-29",
        )

    def test_understands_yesterday(self):
        self.assertEqual(
            _parse_ria_date(
                "https://ria.ru/novost-123.html",
                "Вчера, 23:40",
                now=self.now,
            ),
            "2026-07-28",
        )


class RiaCardTests(unittest.TestCase):
    def test_reads_only_article_cards_and_removes_duplicates(self):
        soup = BeautifulSoup(
            """
            <div class="list-item" data-type="article">
                <a class="list-item__title"
                   href="https://ria.ru/20260729/pervaya-1.html">
                    РИА сообщило о важном событии
                </a>
                <div class="list-item__info-item" data-type="date">15:30</div>
            </div>
            <div class="list-item" data-type="article">
                <a class="list-item__title"
                   href="https://ria.ru/20260729/pervaya-1.html">
                    РИА сообщило о важном событии
                </a>
            </div>
            <div class="list-item" data-type="video">
                <a class="list-item__title"
                   href="https://ria.ru/20260729/video-2.html">
                    Служебная видеокарточка
                </a>
            </div>
            """,
            "html.parser",
        )

        news = _parse_ria_cards(
            soup,
            now=datetime(2026, 7, 29, 16, 0),
        )

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["source"], "РИА Новости")
        self.assertEqual(news[0]["date"], "2026-07-29")
        self.assertEqual(
            news[0]["url"],
            "https://ria.ru/20260729/pervaya-1.html",
        )


if __name__ == "__main__":
    unittest.main()
