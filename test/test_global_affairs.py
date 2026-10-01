import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import global_affairs
from utils.article_reader import extract_article


class GlobalAffairsParserTests(unittest.TestCase):
    @staticmethod
    def _soup(html, parser="html.parser"):
        return BeautifulSoup(html, parser)

    def test_rss_keeps_articles_and_rejects_announcements(self):
        rss = self._soup(
            """
            <rss><channel>
              <item>
                <title>Новый аналитический материал о международной политике</title>
                <link>https://globalaffairs.ru/articles/novyj-material/?utm_source=rss</link>
                <pubDate>Wed, 30 Sep 2026 22:30:00 +0000</pubDate>
                <category>Мнения</category>
                <description><![CDATA[<p>Краткое описание нового материала.</p>]]></description>
              </item>
              <item>
                <title>Анонс очередного мероприятия редакции журнала</title>
                <link>https://globalaffairs.ru/articles/anons-meropriyatiya/</link>
                <pubDate>Wed, 30 Sep 2026 12:00:00 +0000</pubDate>
                <category>Мероприятия</category>
              </item>
              <item>
                <title>Ссылка на посторонний сайт не должна попасть в ленту</title>
                <link>https://example.org/articles/foreign/</link>
                <pubDate>Wed, 30 Sep 2026 12:00:00 +0000</pubDate>
              </item>
            </channel></rss>
            """,
            "xml",
        )

        items = global_affairs._parse_rss(rss)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], global_affairs.SOURCE_NAME)
        self.assertEqual(items[0]["date"], "2026-10-01")
        self.assertEqual(items[0]["section"], "Мнения")
        self.assertEqual(
            items[0]["url"],
            "https://globalaffairs.ru/articles/novyj-material",
        )
        self.assertEqual(items[0]["summary"], "Краткое описание нового материала.")

    def test_listing_uses_longest_title_and_nearby_date(self):
        page = self._soup(
            """
            <article>
              <time datetime="2026-09-29T10:00:00+03:00"></time>
              <a href="/articles/test-story/">Короткий заголовок статьи</a>
              <a href="/articles/test-story/?ref=card">
                Полный заголовок аналитического материала редакции
              </a>
            </article>
            """
        )

        items = global_affairs._parse_listing(
            page,
            "Аналитика",
            "https://globalaffairs.ru/analytics/",
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-09-29")
        self.assertEqual(items[0]["section"], "Аналитика")
        self.assertIn("Полный заголовок", items[0]["title"])

    def test_parse_prefers_rss_without_opening_fallback_pages(self):
        rss = self._soup(
            """
            <rss><channel><item>
              <title>Свежий аналитический материал о мировой политике</title>
              <link>https://globalaffairs.ru/articles/fresh-story/</link>
              <pubDate>Thu, 01 Oct 2026 06:00:00 +0300</pubDate>
              <category>Колонка редактора</category>
            </item></channel></rss>
            """,
            "xml",
        )

        with (
            patch.object(global_affairs, "fetch_soup", return_value=rss) as fetch,
            patch.object(global_affairs, "fetch_soup_js") as browser,
        ):
            items = global_affairs.parse()

        self.assertEqual(len(items), 1)
        self.assertEqual(fetch.call_count, 1)
        browser.assert_not_called()

    def test_internal_reader_uses_verified_article_container(self):
        title = "Большой материал о международных отношениях"
        article = self._soup(
            f"""
            <meta property="og:title" content="{title}">
            <main>
              <div class="article__content">
                <p>Первый содержательный абзац журнальной публикации достаточной длины.</p>
                <p>Второй содержательный абзац продолжает авторский анализ ситуации.</p>
              </div>
              <aside>Посторонний анонс следующего мероприятия редакции.</aside>
            </main>
            """
        )

        with patch("utils.article_reader.fetch_soup", return_value=article):
            result = extract_article(
                "https://globalaffairs.ru/articles/test-story/",
                title,
            )

        self.assertFalse(result["error"])
        self.assertEqual(len(result["paragraphs"]), 2)
        self.assertNotIn("Посторонний анонс", " ".join(result["paragraphs"]))


if __name__ == "__main__":
    unittest.main()
