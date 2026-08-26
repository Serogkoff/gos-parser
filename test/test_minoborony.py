import json
import unittest
from datetime import datetime
from unittest import mock

from bs4 import BeautifulSoup

import main
import web_app
from parsers.sites import minoborony
from parsers.sites.minoborony import _is_article_url, _parse_news_page
from utils.article_reader import extract_article
from utils.source_groups import GOVERNMENT_GROUP, source_group


ARTICLE_ID = "8563d99d-64cb-4375-96a9-b5b5e51e2ecd"
ARTICLE_URL = f"https://z.mil.ru/news/{ARTICLE_ID}"
NEW_ARTICLE_ID = "557bf1ff-4edd-46ad-8bd8-f992df4d950b"
NEW_ARTICLE_URL = f"https://mil.ru/news/{NEW_ARTICLE_ID}"
TITLE = "Министр обороны России проинспектировал группировку войск"


class MinoboronyParserTests(unittest.TestCase):
    def setUp(self):
        self.previous_auth_disabled = web_app.app.config["AUTH_DISABLED"]
        web_app.app.config["AUTH_DISABLED"] = True

    def tearDown(self):
        web_app.app.config["AUTH_DISABLED"] = self.previous_auth_disabled

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
            base_url="https://z.mil.ru/news",
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
        self.assertEqual(
            result[0]["summary"],
            "Краткое описание публикации Министерства обороны России.",
        )

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
        self.assertTrue(_is_article_url(NEW_ARTICLE_URL))
        self.assertFalse(_is_article_url("https://z.mil.ru/news"))
        self.assertFalse(_is_article_url("https://mil.ru/news"))
        self.assertFalse(
            _is_article_url(f"https://example.com/news/{ARTICLE_ID}")
        )

    def test_reads_relative_article_from_new_domain(self):
        soup = BeautifulSoup(
            f"""
            <article class="news-card">
              <time>25 августа 2026 10:30</time>
              <a href="/news/{NEW_ARTICLE_ID}">
                <h3>Новая публикация Министерства обороны России</h3>
              </a>
            </article>
            """,
            "html.parser",
        )

        result = _parse_news_page(
            soup,
            now=datetime(2026, 8, 25, 12, 0),
            base_url="https://mil.ru/news",
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], NEW_ARTICLE_URL)
        self.assertEqual(result[0]["date"], "2026-08-25")

    def test_combines_old_and_new_feeds_without_duplicate_uuid(self):
        legacy_soup = BeautifulSoup(
            f"""
            <article>
              <time>25 августа 2026 10:30</time>
              <a href="/news/{NEW_ARTICLE_ID}">
                <h3>Общая публикация Министерства обороны России</h3>
              </a>
            </article>
            """,
            "html.parser",
        )
        new_soup = BeautifulSoup(
            f"""
            <article>
              <time>25 августа 2026 10:30</time>
              <a href="https://mil.ru/news/{NEW_ARTICLE_ID}">
                <h3>Общая публикация Министерства обороны России</h3>
              </a>
            </article>
            <article>
              <time>25 августа 2026 11:00</time>
              <a href="/news/{ARTICLE_ID}">
                <h3>Отдельная публикация на новом домене Минобороны</h3>
              </a>
            </article>
            """,
            "html.parser",
        )

        def fetch(url, *_args, **_kwargs):
            if url == "https://z.mil.ru/news":
                return legacy_soup
            if url == "https://mil.ru/news":
                return new_soup
            return None

        with mock.patch.object(minoborony, "fetch_soup", side_effect=fetch), mock.patch.object(
            minoborony,
            "fetch_soup_js",
        ) as fetch_js:
            result = minoborony.parse()

        self.assertEqual(len(result), 2)
        self.assertEqual(
            [item["url"] for item in result],
            [
                f"https://mil.ru/news/{NEW_ARTICLE_ID}",
                f"https://mil.ru/news/{ARTICLE_ID}",
            ],
        )
        fetch_js.assert_not_called()

    def test_browser_falls_back_from_old_feed_to_new_feed(self):
        new_soup = BeautifulSoup(
            f"""
            <article>
              <time>25 августа 2026 11:00</time>
              <a href="/news/{NEW_ARTICLE_ID}">
                <h3>Военнослужащие выполнили поставленные учебные задачи</h3>
              </a>
            </article>
            """,
            "html.parser",
        )

        def fetch_js(url, *_args, **_kwargs):
            if url == "https://mil.ru/news":
                return new_soup
            return None

        with mock.patch.object(minoborony, "fetch_soup", return_value=None), mock.patch.object(
            minoborony,
            "fetch_soup_js",
            side_effect=fetch_js,
        ) as browser_fetch:
            result = minoborony.parse()

        self.assertEqual([item["url"] for item in result], [NEW_ARTICLE_URL])
        self.assertEqual(
            [call.args[0] for call in browser_fetch.call_args_list],
            ["https://mil.ru/news", "https://z.mil.ru/news"],
        )

    def test_empty_new_dom_uses_browser_even_when_legacy_feed_has_items(self):
        legacy_soup = BeautifulSoup(
            f"""
            <article>
              <time>25 августа 2026 10:30</time>
              <a href="/news/{ARTICLE_ID}">
                <h3>Публикация из резервной ленты Министерства обороны</h3>
              </a>
            </article>
            """,
            "html.parser",
        )
        modern_browser_soup = BeautifulSoup(
            f"""
            <article>
              <time>26 августа 2026 12:00</time>
              <a href="/news/{NEW_ARTICLE_ID}">
                <h3>Свежая публикация с обновлённого сайта Министерства обороны</h3>
              </a>
            </article>
            """,
            "html.parser",
        )

        def fetch(url, *_args, **_kwargs):
            return legacy_soup if url == "https://z.mil.ru/news" else None

        def fetch_js(url, *_args, **_kwargs):
            return modern_browser_soup if url == "https://mil.ru/news" else None

        with mock.patch.object(
            minoborony, "fetch_soup", side_effect=fetch
        ), mock.patch.object(
            minoborony, "fetch_soup_js", side_effect=fetch_js
        ) as browser_fetch:
            result = minoborony.parse()

        self.assertEqual(
            [item["url"] for item in result],
            [NEW_ARTICLE_URL, ARTICLE_URL],
        )
        self.assertEqual(
            [call.args[0] for call in browser_fetch.call_args_list],
            ["https://mil.ru/news"],
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

    def test_internal_reader_accepts_new_domain(self):
        soup = BeautifulSoup(
            f"""
            <article itemprop="articleBody">
              <h1>{TITLE}</h1>
              <p>Министерство обороны опубликовало новый официальный материал.</p>
            </article>
            """,
            "html.parser",
        )

        with mock.patch(
            "utils.article_reader.fetch_soup_js",
            return_value=soup,
        ):
            article = extract_article(NEW_ARTICLE_URL, TITLE)

        self.assertFalse(article["error"])
        self.assertEqual(
            article["paragraphs"],
            ["Министерство обороны опубликовало новый официальный материал."],
        )

    def test_web_page_uses_card_summary_when_article_has_no_body(self):
        summary = (
            "Ежедневно подразделения группировки выявляют и уничтожают "
            "замаскированные пункты управления беспилотными аппаратами."
        )

        def load_json(filename, default):
            if filename == "all_news.json":
                return [{
                    "source": "Минобороны РФ",
                    "title": TITLE,
                    "url": ARTICLE_URL,
                    "date": "2026-07-31",
                    "summary": summary,
                }]
            return default

        with mock.patch.object(web_app, "load_json", side_effect=load_json), mock.patch.object(
            web_app,
            "extract_article",
            return_value={
                "title": TITLE,
                "paragraphs": [],
                "error": "Текста нет",
            },
        ):
            response = web_app.app.test_client().get(
                "/article?url=" + ARTICLE_URL
            )

        html = response.get_data(as_text=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(summary, html)
        self.assertNotIn("Текста нет", html)


if __name__ == "__main__":
    unittest.main()
