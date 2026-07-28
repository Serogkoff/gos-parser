import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.mintrud import _is_news_article_url
from utils.article_reader import (
    _clean_mnr_paragraphs,
    _paragraphs,
    extract_article,
)


class MintrudUrlTests(unittest.TestCase):
    def test_accepts_news_materials_with_numeric_id(self):
        self.assertTrue(
            _is_news_article_url(
                "https://mintrud.gov.ru/employment/employment/816"
            )
        )
        self.assertTrue(
            _is_news_article_url("https://mintrud.gov.ru/employment/72")
        )

    def test_rejects_events_and_service_pages(self):
        self.assertFalse(
            _is_news_article_url("https://mintrud.gov.ru/events/1451")
        )
        self.assertFalse(
            _is_news_article_url(
                "https://mintrud.gov.ru/news/news/list?page=2&per-page=10"
            )
        )


class ArticleCleanupTests(unittest.TestCase):
    def test_uses_fallback_title_for_generic_page_heading(self):
        soup = BeautifulSoup(
            """
            <main>
                <h1>Новости</h1>
                <p>Юрий Трутнев провёл совещание по вопросам развития
                Дальнего Востока и реализации новых проектов.</p>
            </main>
            """,
            "html.parser",
        )
        with patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "http://government.ru/news/59382/",
                "Юрий Трутнев провёл совещание",
            )

        self.assertEqual(
            article["title"],
            "Юрий Трутнев провёл совещание",
        )

    def test_removes_minfin_license_footer(self):
        soup = BeautifulSoup(
            """
            <main>
                <p>Основной текст публикации Министерства финансов Российской Федерации.</p>
                <p>Все материалы сайта доступны по лицензии: Creative Commons
                «Attribution» 4.0 Всемирная.</p>
            </main>
            """,
            "html.parser",
        )
        self.assertEqual(
            _paragraphs(soup),
            [
                "Основной текст публикации Министерства финансов "
                "Российской Федерации."
            ],
        )

    def test_mnr_does_not_return_news_list_heading(self):
        soup = BeautifulSoup(
            """
            <article>
                <p>Новости и пресс-релизы соседних подразделений министерства.</p>
                <p>Шесть российских объектов представили на международной
                сессии ЮНЕСКО в ходе рабочего заседания.</p>
            </article>
            """,
            "html.parser",
        )
        self.assertEqual(
            _clean_mnr_paragraphs(soup, "Заголовок"),
            [
                "Шесть российских объектов представили на международной "
                "сессии ЮНЕСКО в ходе рабочего заседания."
            ],
        )


if __name__ == "__main__":
    unittest.main()
