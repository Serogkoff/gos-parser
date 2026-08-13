import unittest
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import rg
from parsers.sites.rg import _parse_fresh_issue, _parse_xml_feed


class RussianGazetteTests(unittest.TestCase):
    def test_reads_articles_and_issue_metadata(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Российская газета 11 августа 2026 г. №10014</h1>
              <section>
                <span>10.08.2026</span>
                <a href="/2026/08/10/vladimir-putin-potreboval-navesti-poriadok.html">
                  Владимир Путин потребовал навести порядок в сфере транспорта
                </a>
              </section>
              <a href="/economics/">Экономика</a>
              <a href="/2026/08/11/fz323-dok.html">
                Федеральный закон от 4 августа 2026 г. N 323-ФЗ
                «О безопасном обращении с пестицидами»
              </a>
              <a href="/2026/08/11/zakon-izmenit-pravila.html">
                Новый закон изменит правила обращения с пестицидами
              </a>
            </main>
            """,
            "html.parser",
        )

        result = _parse_fresh_issue(soup)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["source"], "Российская газета")
        self.assertEqual(result[0]["date"], "2026-08-10")
        self.assertEqual(result[0]["edition_date"], "2026-08-11")
        self.assertEqual(result[0]["edition_id"], "10014")
        self.assertEqual(
            result[1]["title"],
            "Новый закон изменит правила обращения с пестицидами",
        )
        self.assertFalse(any("323-ФЗ" in item["title"] for item in result))

    def test_reads_only_newest_day_from_official_xml_fallback(self):
        soup = BeautifulSoup(
            """
            <rss><channel>
              <item>
                <title>Новая редакционная статья Российской газеты</title>
                <link>https://rg.ru/2026/08/13/novyi-material.html</link>
                <pubDate>Thu, 13 Aug 2026 08:00:00 +0300</pubDate>
                <description><![CDATA[
                  &lt;p&gt;Краткий анонс свежего материала с
                  &lt;a href=&quot;https://example.test&quot;&gt;лишней ссылкой&lt;/a&gt;.&lt;/p&gt;
                ]]></description>
              </item>
              <item>
                <title>Вчерашняя редакционная статья Российской газеты</title>
                <link>https://rg.ru/2026/08/12/staryi-material.html</link>
                <pubDate>Wed, 12 Aug 2026 08:00:00 +0300</pubDate>
              </item>
              <item>
                <title>Федеральный закон от 12 августа 2026 г. N 1-ФЗ</title>
                <link>https://rg.ru/2026/08/13/fz1-dok.html</link>
                <pubDate>Thu, 13 Aug 2026 09:00:00 +0300</pubDate>
              </item>
            </channel></rss>
            """,
            "html.parser",
        )

        result = _parse_xml_feed(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-13")
        self.assertEqual(result[0]["section"], "XML · резерв")
        self.assertIn("Краткий анонс", result[0]["summary"])
        self.assertNotIn("<a", result[0]["summary"])

    def test_parse_uses_xml_after_page_and_browser_fail(self):
        feed = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Свежая редакционная статья Российской газеты</title>
              <link>https://rg.ru/2026/08/13/novyi-material.html</link>
              <pubDate>Thu, 13 Aug 2026 08:00:00 +0300</pubDate>
            </item></channel></rss>
            """,
            "html.parser",
        )
        with mock.patch.object(
            rg,
            "fetch_soup",
            side_effect=[None, feed],
        ) as fetch, mock.patch.object(
            rg,
            "fetch_soup_js",
            return_value=None,
        ):
            result = rg.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args.kwargs["attempts"], 1)


if __name__ == "__main__":
    unittest.main()
