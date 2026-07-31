import json
import unittest
from datetime import datetime
from unittest import mock

from bs4 import BeautifulSoup

import main
from parsers.sites import minoborony
from parsers.sites.minoborony import _is_article_url, _parse_news_page
from utils.article_reader import extract_article
from utils.source_groups import GOVERNMENT_GROUP, source_group


ARTICLE_ID = "8563d99d-64cb-4375-96a9-b5b5e51e2ecd"
ARTICLE_URL = f"https://z.mil.ru/news/{ARTICLE_ID}"
TITLE = "Министр обороны России проинспектировал группировку войск"


class MinoboronyParserTests(unittest.TestCase):
    def test_reads_real_article_links_and_card_dates(self):
        soup = BeautifulSoup(
            f"""
            <article class="news-card">
              <time datetime="2026-07-31T12:00:00+03:00">31 июля 2026</time>
              <a href="/news/{ARTICLE_ID}"><h3>{TITLE}</h3></a>
            </article>
            <a href="/news">Общий раздел новостей</a>
            """,
            "html.parser",
        )

        result = _parse_news_page(
            soup,
            now=datetime(2026, 7, 31, 14, 0),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Минобороны РФ")
        self.assertEqual(result[0]["title"], TITLE)
        self.assertEqual(result[0]["date"], "2026-07-31")
        self.assertEqual(result[0]["url"], ARTICLE_URL)

    def test_reads_date_from_generated_css_card(self):
        soup = BeautifulSoup(
            f"""
            <div class="css-ut84ul-CardWrapper">
              <div class="css-bo01xn-Card">
                <a href="/news/{ARTICLE_ID}">{TITLE}</a>
                <p>Краткое описание публикации Министерства обороны России.</p>
                <div class="css-random-name">31 июля 2026 12:31</div>
              </div>
            </div>
            """,
            "html.parser",
        )

        result = _parse_news_page(
            soup,
            now=datetime(2026, 7, 31, 14, 0),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-07-31")

    def test_reads_embedded_page_state(self):
        payload = {
            "items": [{
                "url": f"/news/{ARTICLE_ID}",
                "title": TITLE,
                "datePublished": "2026-07-30T19:10:00+03:00",
            }]
        }
        soup = BeautifulSoup(
            '<script id="initial-data" type="application/json">'
            + json.dumps(payload, ensure_ascii=False)
            + "</script>",
            "html.parser",
        )

        result = _parse_news_page(
            soup,
            now=datetime(2026, 7, 31, 14, 0),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-07-30")

    def test_accepts_only_uuid_articles_on_official_host(self):
        self.assertTrue(_is_article_url(ARTICLE_URL))
        self.assertFalse(_is_article_url("https://z.mil.ru/news"))
        self.assertFalse(
            _is_article_url(f"https://example.com/news/{ARTICLE_ID}")
        )

    def test_registered_as_government_source(self):
        self.assertEqual(source_group("Минобороны РФ"), GOVERNMENT_GROUP)
        self.assertIn(
            "Минобороны РФ",
            [name for name, _parser in main.GOVERNMENT_SITES],
        )

    def test_internal_reader_keeps_only_article_body(self):
        soup = BeautifulSoup(
            f"""
            <html><head>
              <meta property="og:title" content="{TITLE}">
            </head><body>
              <nav>Главная Новости Структура Министерства</nav>
              <article itemprop="articleBody">
                <h1>{TITLE}</h1>
                <p>Министр обороны Российской Федерации заслушал доклады командования о текущей обстановке и выполнении поставленных задач.</p>
                <p>Особое внимание было уделено обеспечению подразделений современной техникой и средствами связи.</p>
              </article>
              <footer>Контакты и карта сайта</footer>
            </body></html>
            """,
            "html.parser",
        )

        with mock.patch(
            "utils.article_reader.fetch_soup_js",
            return_value=soup,
        ):
            article = extract_article(ARTICLE_URL, TITLE)

        self.assertFalse(article["error"])
        self.assertEqual(article["title"], TITLE)
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertNotIn("Структура Министерства", " ".join(article["paragraphs"]))


if __name__ == "__main__":
    unittest.main()
