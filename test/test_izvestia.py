import unittest

from bs4 import BeautifulSoup

from parsers.sites.izvestia import _parse_newspaper_page, _parse_rss


class IzvestiaTests(unittest.TestCase):
    def test_reads_print_issue_page(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Газета «Известия» от 11 августа 2026 года</h1>
              <article>
                <a href="/1934567/ivan-ivanov/delovoi-material-izvestii">
                  Деловой материал свежего номера Известий
                </a>
              </article>
            </main>
            """,
            "html.parser",
        )

        result = _parse_newspaper_page(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Известия")
        self.assertEqual(result[0]["date"], "2026-08-11")
        self.assertEqual(result[0]["edition_date"], "2026-08-11")

    def test_official_rss_is_available_as_fallback(self):
        soup = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Материал резервной ленты Известий</title>
              <link>https://iz.ru/1934568/ivan-ivanov/rezervnyi-material</link>
              <pubDate>Tue, 11 Aug 2026 08:00:00 +0300</pubDate>
              <description><![CDATA[<p>Краткий анонс публикации.</p>]]></description>
            </item></channel></rss>
            """,
            "xml",
        )

        result = _parse_rss(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-11")


if __name__ == "__main__":
    unittest.main()
