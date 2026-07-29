import unittest
from datetime import datetime
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import ria
from parsers.sites.ria import (
    SECTION_URLS,
    _parse_ria_cards,
    _parse_ria_date,
)


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

    def test_all_main_ria_sections_are_configured(self):
        self.assertEqual(
            {name for name, _ in SECTION_URLS},
            {
                "Политика",
                "В мире",
                "Экономика",
                "Общество",
                "Происшествия",
                "Наука",
                "Культура",
                "Туризм",
                "Спорт",
            },
        )

    def test_section_scan_keeps_section_name(self):
        soup = BeautifulSoup(
            """
            <div class="list-item" data-type="article">
                <a class="list-item__title"
                   href="https://ria.ru/20260729/politika-1.html">
                    РИА опубликовало политическую новость
                </a>
            </div>
            """,
            "html.parser",
        )

        with (
            mock.patch.object(
                ria,
                "SECTION_URLS",
                (("Политика", "https://ria.ru/politics/"),),
            ),
            mock.patch.object(ria, "fetch_soup", return_value=soup),
            mock.patch.dict(ria._section_cache, {}, clear=True),
            mock.patch.object(ria, "_next_section_index", 0),
        ):
            ria._refresh_next_sections()
            item = ria._section_cache["Политика"][0]

        self.assertEqual(item["section"], "Политика")

    def test_reads_sport_and_tourism_card_templates(self):
        soup = BeautifulSoup(
            """
            <a class="cell-list__item-link"
               href="https://ria.ru/20260729/sport-1.html"
               title="Спортивная федерация сообщила важную новость">
                <span class="cell-list__item-title">
                    Спортивная федерация сообщила важную новость
                </span>
                <div class="cell-info__date">12:47</div>
            </a>
            <a class="cell-list-f__main-link"
               href="https://ria.ru/20260728/tourism-2.html">
                <span class="cell-list-f__main-title">
                    Туристам рассказали о новом маршруте
                </span>
                <div class="cell-info__date">28 июля, 08:00</div>
            </a>
            """,
            "html.parser",
        )

        news = _parse_ria_cards(
            soup,
            now=datetime(2026, 7, 29, 16, 0),
            section="Спорт и туризм",
        )

        self.assertEqual(len(news), 2)
        self.assertEqual(
            {item["date"] for item in news},
            {"2026-07-29", "2026-07-28"},
        )


if __name__ == "__main__":
    unittest.main()
