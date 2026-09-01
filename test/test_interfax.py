import unittest
from datetime import datetime, timezone
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import interfax
from parsers.sites.interfax import (
    _is_interfax_article_url,
    _parse_interfax_date,
    _parse_interfax_feed,
)
from utils.article_reader import extract_article


MAIN_RSS = """
<rss version="2.0">
  <channel>
    <item>
      <title>Интерфакс сообщил о важном событии в России</title>
      <link>https://www.interfax.ru/russia/1106527</link>
      <pubDate>Thu, 30 Jul 2026 11:44:00 +0300</pubDate>
      <category>В России</category>
      <description><![CDATA[<p>Короткий официальный анонс.</p>]]></description>
    </item>
    <item>
      <title>Служебная ссылка на раздел новостей</title>
      <link>https://www.interfax.ru/news/</link>
      <pubDate>Thu, 30 Jul 2026 11:40:00 +0300</pubDate>
    </item>
  </channel>
</rss>
"""

SPORT_RSS = """
<rss version="2.0">
  <channel>
    <item>
      <title>Российская команда победила на международном турнире</title>
      <link>https://www.sport-interfax.ru/1106404</link>
      <pubDate>Wed, 29 Jul 2026 21:48:00 +0300</pubDate>
      <category>Спорт</category>
      <description>Спортсмены успешно завершили соревнования.</description>
    </item>
  </channel>
</rss>
"""


class InterfaxParserTests(unittest.TestCase):
    def test_reads_main_and_sport_feed_fields(self):
        now = datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc)
        main = _parse_interfax_feed(
            BeautifulSoup(MAIN_RSS, "xml"),
            default_section="Последние новости",
            now=now,
        )
        sport = _parse_interfax_feed(
            BeautifulSoup(SPORT_RSS, "xml"),
            default_section="Спорт",
            now=now,
        )

        self.assertEqual(len(main), 1)
        self.assertEqual(len(sport), 1)
        self.assertEqual(main[0]["source"], "Интерфакс")
        self.assertEqual(main[0]["date"], "2026-07-30")
        self.assertEqual(main[0]["section"], "В России")
        self.assertEqual(main[0]["summary"], "Короткий официальный анонс.")
        self.assertEqual(sport[0]["section"], "Спорт")

    def test_accepts_only_real_interfax_article_urls(self):
        self.assertTrue(
            _is_interfax_article_url(
                "https://www.interfax.ru/business/1106525"
            )
        )
        self.assertTrue(
            _is_interfax_article_url(
                "https://www.sport-interfax.ru/1106404"
            )
        )
        self.assertFalse(
            _is_interfax_article_url("https://www.interfax.ru/news/")
        )
        self.assertFalse(
            _is_interfax_article_url("https://special.interfax.ru/advert")
        )

    def test_understands_rss_timezone(self):
        self.assertEqual(
            _parse_interfax_date("Thu, 30 Jul 2026 23:59:00 +0300"),
            "2026-07-30",
        )

    def test_parse_requests_each_official_feed_once(self):
        soups = [
            BeautifulSoup(MAIN_RSS, "xml"),
            BeautifulSoup(SPORT_RSS, "xml"),
        ]
        with mock.patch.object(
            interfax,
            "fetch_soup",
            side_effect=soups,
        ) as fetch:
            news = interfax.parse(
                now=datetime(2026, 7, 30, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(len(news), 2)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            [url for _, url in interfax.FEED_URLS],
        )

    def test_internal_reader_prefers_full_article_over_short_description(self):
        soup = BeautifulSoup(
            """
            <html>
              <head>
                <meta property="og:title"
                      content="Интерфакс сообщил о важном событии">
                <script type="application/ld+json">
                  {
                    "@type": "NewsArticle",
                    "headline": "Интерфакс сообщил о важном событии",
                    "description": "Короткий анонс публикации Интерфакса."
                  }
                </script>
              </head>
              <body>
                <article itemprop="articleBody">
                  <h1>Интерфакс сообщил о важном событии</h1>
                  <p>Москва. 30 июля. INTERFAX.RU — Первый полный абзац
                  публикации содержит важные подробности события.</p>
                  <p>Второй полный абзац содержит дополнительную информацию
                  и комментарий официального представителя.</p>
                </article>
              </body>
            </html>
            """,
            "html.parser",
        )
        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ):
            article = extract_article(
                "https://www.interfax.ru/russia/1106527",
                "Интерфакс сообщил о важном событии",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("Первый полный абзац", article["paragraphs"][0])


if __name__ == "__main__":
    unittest.main()
