import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

import config
from parsers.sites import (
    bbc_russian,
    istories,
    meduza,
    moscow_times,
    the_insider,
    verstka,
)
from parsers.sites.vpn_rss import (
    VpnRssSource,
    extract_paragraphs,
    load_article,
    parse_feed,
    parse_source,
)
from utils.source_groups import (
    ADMIN_ONLY_SOURCES,
    NEWSPAPERS_GROUP,
    source_group,
)


class VpnRssMediaTests(unittest.TestCase):
    def setUp(self):
        self.config = VpnRssSource(
            name="Тестовое СМИ",
            feed_url="https://example.test/feed",
            domains=("example.test",),
            article_selectors=(".article-body",),
        )

    def test_feed_keeps_metadata_time_and_clean_discovery_url(self):
        soup = BeautifulSoup(
            """
            <rss xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><item>
              <title>Новый содержательный материал</title>
              <link>https://example.test/news/1?utm_source=rss&amp;keep=yes</link>
              <pubDate>Thu, 01 Oct 2026 09:11:56 +0300</pubDate>
              <description><![CDATA[<p>Краткое описание новости.</p>]]></description>
              <category>Политика</category>
              <dc:creator>Иван Иванов</dc:creator>
            </item></channel></rss>
            """,
            "xml",
        )

        items = parse_feed(soup, self.config)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.test/news/1?keep=yes")
        self.assertEqual(items[0]["date"], "2026-10-01")
        self.assertEqual(items[0]["published_at"], "2026-10-01T09:11:56+03:00")
        self.assertEqual(items[0]["author"], "Иван Иванов")
        self.assertEqual(items[0]["section"], "Политика")
        self.assertEqual(items[0]["summary"], "Краткое описание новости.")

    def test_article_uses_canonical_metadata_and_removes_page_noise(self):
        soup = BeautifulSoup(
            """
            <html><head>
              <link rel="canonical" href="https://example.test/news/canonical">
              <meta property="article:published_time" content="2026-10-01T06:15:00Z">
              <meta property="article:section" content="Расследования">
              <meta name="author" content="Анна Авторова">
            </head><body>
              <div class="article-body">
                <p>Первый большой абзац полного текста, в котором достаточно полезной информации для читателя.</p>
                <div class="related"><p>Читайте также совершенно другой материал, который не относится к статье.</p></div>
                <p>Второй большой абзац полного текста с продолжением содержательного авторского материала.</p>
                <footer><p>Подписывайтесь на наши социальные сети и рассылку редакции.</p></footer>
              </div>
            </body></html>
            """,
            "html.parser",
        )
        item = {
            "source": self.config.name,
            "title": "Новый содержательный материал",
            "url": "https://example.test/news/1",
            "rss_url": "https://example.test/news/1",
            "date": "2026-10-01",
            "published_at": "2026-10-01T09:11:56+03:00",
            "section": "Новости",
        }

        with patch("parsers.sites.vpn_rss.fetch_soup", return_value=soup):
            result = load_article(item, self.config, proxy_url="vpn-route")

        self.assertEqual(result["url"], "https://example.test/news/canonical")
        self.assertEqual(result["author"], "Анна Авторова")
        self.assertEqual(result["section"], "Расследования")
        self.assertEqual(result["published_at"], "2026-10-01T06:15:00+00:00")
        self.assertEqual(len(result["article_paragraphs"]), 2)
        joined = " ".join(result["article_paragraphs"])
        self.assertNotIn("Читайте также", joined)
        self.assertNotIn("Подписывайтесь", joined)

    def test_repeated_bbc_text_blocks_are_collected_together(self):
        soup = BeautifulSoup(
            """
            <main>
              <div data-component="text-block"><p>Первый содержательный абзац материала Би-би-си с подробностями события.</p></div>
              <div data-component="text-block"><p>Второй содержательный абзац материала Би-би-си с дополнительным контекстом.</p></div>
              <div data-component="text-block"><p>Третий содержательный абзац материала Би-би-си завершает публикацию.</p></div>
            </main>
            """,
            "html.parser",
        )
        paragraphs = extract_paragraphs(
            soup,
            ("[data-component='text-block']", "main"),
        )
        self.assertEqual(len(paragraphs), 3)

    def test_existing_rss_alias_skips_repeated_article_request(self):
        feed = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Уже сохранённая публикация</title>
              <link>https://example.test/news/rss-address</link>
              <pubDate>Thu, 01 Oct 2026 09:11:56 +0300</pubDate>
            </item></channel></rss>
            """,
            "xml",
        )
        aliases = {
            "https://example.test/news/rss-address": {
                "url": "https://example.test/news/canonical",
                "has_article": True,
            }
        }
        with (
            patch("parsers.sites.vpn_rss.kyodo_proxy_url", return_value="vpn-route"),
            patch("parsers.sites.vpn_rss.fetch_soup", return_value=feed) as fetch,
            patch("parsers.sites.vpn_rss.load_source_url_aliases", return_value=aliases),
        ):
            items = parse_source(self.config)

        self.assertEqual(items[0]["url"], "https://example.test/news/canonical")
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.kwargs["proxy_url"], "vpn-route")

    def test_browser_feed_fallback_keeps_original_domain_and_rss_text(self):
        feed = BeautifulSoup(
            """
            <rss xmlns:content="http://purl.org/rss/1.0/modules/content/">
              <channel><item>
                <title>Редакция опубликовала подробности нового события</title>
                <link>https://verstka.media/news/original</link>
                <pubDate>Thu, 01 Oct 2026 09:11:56 +0300</pubDate>
                <content:encoded><![CDATA[
                  <p>Первый большой абзац полного текста публикации, содержащий все необходимые подробности события.</p>
                  <p>Второй большой абзац продолжает публикацию и содержит достаточно полезной информации.</p>
                  <p>Третий большой абзац завершает полный материал редакции и добавляет важный контекст.</p>
                  <p>Четвёртый большой абзац нужен для надёжной проверки достаточной длины полного текста.</p>
                  <p>Пятый большой абзац подтверждает, что RSS содержит полную публикацию без запроса страницы.</p>
                  <p>Шестой большой абзац содержит дополнительные факты и завершает проверочный материал.</p>
                ]]></content:encoded>
              </item></channel>
            </rss>
            """,
            "xml",
        )
        source = VpnRssSource(
            name="Вёрстка",
            feed_url="https://verstka.media/feed/",
            domains=("verstka.media",),
            article_selectors=("article",),
            rss_full_text_fallback=True,
            prefer_rss_full_text=True,
            browser_fallback=True,
            browser_warmup_url="https://verstka.media/",
        )
        with (
            patch("parsers.sites.vpn_rss.kyodo_proxy_url", return_value="vpn-route"),
            patch("parsers.sites.vpn_rss.fetch_soup", return_value=None),
            patch(
                "parsers.sites.vpn_rss.fetch_response_soup_js",
                return_value=feed,
            ) as browser_fetch,
            patch("parsers.sites.vpn_rss.load_source_url_aliases", return_value={}),
            patch("parsers.sites.vpn_rss.load_article") as load_page,
        ):
            items = parse_source(source)

        self.assertEqual(len(items), 1)
        self.assertGreaterEqual(len(items[0]["article_paragraphs"]), 6)
        self.assertEqual(items[0]["url"], "https://verstka.media/news/original")
        browser_fetch.assert_called_once()
        load_page.assert_not_called()

    def test_moscow_times_combines_ru_and_english_feeds_as_one_source(self):
        russian = [{"source": moscow_times.SOURCE_NAME, "url": "https://ru.themoscowtimes.com/a/1"}]
        english = [{"source": moscow_times.SOURCE_NAME, "url": "https://www.themoscowtimes.com/a/2"}]
        with patch(
            "parsers.sites.moscow_times.parse_source",
            side_effect=(russian, english),
        ) as parse_feed_source:
            items = moscow_times.parse()

        self.assertEqual(len(items), 2)
        self.assertEqual(parse_feed_source.call_count, 2)
        self.assertEqual(
            parse_feed_source.call_args_list[0].args[0].feed_url,
            "https://ru.themoscowtimes.com/rss/news",
        )
        self.assertEqual(
            parse_feed_source.call_args_list[1].args[0].feed_url,
            "https://www.themoscowtimes.com/rss/news",
        )
        self.assertTrue(all(item["source"] == "The Moscow Times" for item in items))

    def test_all_sources_use_exact_feeds_domains_and_admin_visibility(self):
        expected = {
            bbc_russian.SOURCE_NAME: ("https://feeds.bbci.co.uk/russian/rss.xml", "bbc.com"),
            moscow_times.SOURCE_NAME: ("https://ru.themoscowtimes.com/rss/news", "ru.themoscowtimes.com"),
            meduza.SOURCE_NAME: ("https://meduza.io/rss2/all", "meduza.io"),
            istories.SOURCE_NAME: ("https://istories.media/rss/all.xml", "istories.media"),
            verstka.SOURCE_NAME: ("https://verstka.media/feed/", "verstka.media"),
            the_insider.SOURCE_NAME: ("https://theins.ru/feed", "theins.ru"),
        }
        modules = (bbc_russian, moscow_times, meduza, istories, verstka, the_insider)
        for module in modules:
            with self.subTest(source=module.SOURCE_NAME):
                feed, domain = expected[module.SOURCE_NAME]
                self.assertEqual(module.CONFIG.feed_url, feed)
                self.assertIn(domain, module.CONFIG.domains)
                self.assertIn(module.SOURCE_NAME, ADMIN_ONLY_SOURCES)
                self.assertEqual(source_group(module.SOURCE_NAME), NEWSPAPERS_GROUP)
        self.assertNotIn("nproxy.org", verstka.CONFIG.feed_url)
        self.assertNotIn("nproxy.org", " ".join(verstka.CONFIG.feed_fallback_urls))
        self.assertTrue(verstka.CONFIG.browser_fallback)
        self.assertTrue(verstka.CONFIG.prefer_rss_full_text)
        self.assertEqual(
            moscow_times.CONFIG_EN.feed_url,
            "https://www.themoscowtimes.com/rss/news",
        )
        self.assertEqual(config.FAST_VPN_MEDIA_UPDATE_INTERVAL, 300)
        self.assertEqual(config.VPN_MEDIA_UPDATE_INTERVAL, 600)


if __name__ == "__main__":
    unittest.main()
