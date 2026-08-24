import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import (
    minselkhoz,
    minstroy,
    mintsifry,
    mintrans,
    minvostok,
)
from parsers.sites.minselkhoz import _is_article_url as is_mcx_article
from parsers.sites.minstroy import _is_article_url as is_minstroy_article
from parsers.sites.mintrans import _is_article_url as is_mintrans_article
from parsers.sites.minvostok import _is_article_url as is_minvr_article
from utils.parser_links import find_article_url


class FixedJulyDateTime(datetime):
    """Фиксирует свежесть карточек, чтобы тесты не зависели от даты запуска."""

    @classmethod
    def now(cls, tz=None):
        value = cls(2026, 7, 29, 12, 0, 0)
        return value if tz is None else value.replace(tzinfo=tz)


class SourceArticleUrlTests(unittest.TestCase):
    def test_accepts_real_article_shapes(self):
        self.assertTrue(
            is_mcx_article(
                "https://mcx.gov.ru/press-service/news/novaya-publikatsiya/"
            )
        )
        self.assertTrue(
            is_minstroy_article(
                "https://www.minstroyrf.gov.ru/press/novaya-publikatsiya/"
            )
        )
        self.assertTrue(
            is_minvr_article(
                "https://minvr.gov.ru/press-center/news/novaya_publikatsiya/"
            )
        )
        self.assertTrue(
            is_mintrans_article(
                "https://www.mintrans.gov.ru/press-center/news/12628"
            )
        )

    def test_rejects_news_list_pages(self):
        self.assertFalse(
            is_mcx_article("https://mcx.gov.ru/press-service/news/")
        )
        self.assertFalse(
            is_minstroy_article("https://minstroyrf.gov.ru/press/")
        )
        self.assertFalse(
            is_minvr_article("https://minvr.gov.ru/press-center/news/")
        )
        self.assertFalse(
            is_mintrans_article(
                "https://mintrans.gov.ru/press-center/news?page=2"
            )
        )


class FindArticleUrlTests(unittest.TestCase):
    def test_finds_anchor_wrapping_the_whole_card(self):
        soup = BeautifulSoup(
            """
            <a href="/press-service/news/novaya-publikatsiya/">
                <div class="newsList__wrapContent">
                    <div class="newsList__title">Настоящий заголовок</div>
                </div>
            </a>
            """,
            "html.parser",
        )
        node = soup.select_one(".newsList__wrapContent")
        self.assertEqual(
            find_article_url(
                node,
                "https://mcx.gov.ru/press-service/news/",
                is_mcx_article,
            ),
            "https://mcx.gov.ru/press-service/news/novaya-publikatsiya/",
        )

    def test_finds_link_next_to_the_header(self):
        soup = BeautifulSoup(
            """
            <article>
                <div class="article__header"><time>28.07.2026</time></div>
                <a class="article__link"
                   href="/press-center/news/novaya_publikatsiya/">
                    Настоящий заголовок публикации
                </a>
            </article>
            """,
            "html.parser",
        )
        node = soup.select_one(".article__header")
        self.assertEqual(
            find_article_url(
                node,
                "https://minvr.gov.ru/press-center/news/",
                is_minvr_article,
            ),
            "https://minvr.gov.ru/press-center/news/novaya_publikatsiya/",
        )


class ParserCardTests(unittest.TestCase):
    def _parse_with_html(self, module, html):
        soup = BeautifulSoup(html, "html.parser")
        with patch.object(module, "fetch_soup", return_value=soup):
            return module.parse()

    def test_minselKhoz_uses_wrapping_card_link(self):
        news = self._parse_with_html(
            minselkhoz,
            """
            <a href="/press-service/news/novaya-publikatsiya/">
                <div class="newsList__wrapContent">
                    <div class="newsList__title">
                        Минсельхоз представил важную отраслевую инициативу
                    </div>
                </div>
            </a>
            """,
        )
        self.assertEqual(len(news), 1)
        self.assertNotEqual(news[0]["url"], "https://mcx.gov.ru/press-service/news/")

    def test_minstroy_uses_link_around_card(self):
        news = self._parse_with_html(
            minstroy,
            """
            <a href="/press/novaya-publikatsiya/">
                <div class="item-new">
                    <div class="new-text">
                        Минстрой сообщил о запуске нового проекта
                    </div>
                </div>
            </a>
            """,
        )
        self.assertEqual(len(news), 1)
        self.assertIn("/press/novaya-publikatsiya/", news[0]["url"])

    def test_minvostok_uses_sibling_article_link(self):
        news = self._parse_with_html(
            minvostok,
            """
            <article>
                <div class="article__header"></div>
                <a class="article__link"
                   href="/press-center/news/novaya_publikatsiya/">
                    Минвостокразвития сообщило о новом проекте
                </a>
            </article>
            """,
        )
        self.assertEqual(len(news), 1)
        self.assertIn("/news/novaya_publikatsiya/", news[0]["url"])

    def test_mintrans_requires_numeric_article_id(self):
        news = self._parse_with_html(
            mintrans,
            """
            <div class="news-inf">
                <div class="news-text">
                    <a href="/press-center/news/12628">
                        Минтранс сообщил о развитии транспортной отрасли
                    </a>
                </div>
            </div>
            """,
        )
        self.assertEqual(len(news), 1)
        self.assertTrue(news[0]["url"].endswith("/12628"))

    def test_mintsifry_keeps_the_date_of_each_card(self):
        soup = BeautifulSoup(
            """
            <main class="main__container">
                <article>
                    <time>29 июля 2026</time>
                    <a href="/news/segodnyashnyaya-publikacziya">
                        Минцифры представило сегодняшний цифровой проект
                    </a>
                </article>
                <article>
                    <time>28 июля 2026</time>
                    <a href="/news/vcherashnyaya-publikacziya">
                        Минцифры рассказало о вчерашней важной инициативе
                    </a>
                </article>
            </main>
            """,
            "html.parser",
        )
        with (
            patch.object(mintsifry, "fetch_soup_js", return_value=soup),
            patch.object(mintsifry, "datetime", FixedJulyDateTime),
        ):
            news = mintsifry.parse()

        self.assertEqual(len(news), 2)
        self.assertEqual(
            [item["date"] for item in news],
            ["2026-07-29", "2026-07-28"],
        )

    def test_mintsifry_prefers_date_inside_link_over_page_date(self):
        soup = BeautifulSoup(
            """
            <main class="main__container">
                <div class="page-date">28 июля 2026</div>
                <a href="/news/pozdravlenie-s-10-000-m-nomerom">
                    <span>24 июля</span>
                    <strong>
                        Поздравление с 10 000-м номером Российской газеты
                    </strong>
                </a>
            </main>
            """,
            "html.parser",
        )
        with (
            patch.object(mintsifry, "fetch_soup_js", return_value=soup),
            patch.object(mintsifry, "datetime", FixedJulyDateTime),
        ):
            news = mintsifry.parse()

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["date"], "2026-07-24")

    def test_mintsifry_falls_back_to_http_when_browser_fails(self):
        soup = BeautifulSoup(
            """
            <main class="main__container">
                <a href="/news/rezervnaya-zagruzka">
                    <span>24 июля</span>
                    <strong>
                        Минцифры опубликовало материал через резервную загрузку
                    </strong>
                </a>
            </main>
            """,
            "html.parser",
        )
        with (
            patch.object(mintsifry, "fetch_soup_js", return_value=None),
            patch.object(mintsifry, "fetch_soup", return_value=soup),
            patch.object(mintsifry, "datetime", FixedJulyDateTime),
        ):
            news = mintsifry.parse()

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["date"], "2026-07-24")


if __name__ == "__main__":
    unittest.main()
