import unittest

from bs4 import BeautifulSoup

from parsers.sites.kp import _parse_latest_rss


class KomsomolskayaPravdaTests(unittest.TestCase):
    def test_reads_only_latest_moscow_date(self):
        soup = BeautifulSoup(
            """
            <rss><channel>
              <item>
                <title>Свежая статья Комсомольской правды</title>
                <link>https://www.kp.ru/daily/277805.4/5288487/?from=twall</link>
                <pubDate>Mon, 10 Aug 2026 21:31:00 GMT</pubDate>
                <category>Политика</category>
                <description>Краткий анонс свежей публикации.</description>
              </item>
              <item>
                <title>Предыдущая статья Комсомольской правды</title>
                <link>https://www.kp.ru/daily/277804/5288000/</link>
                <pubDate>Mon, 10 Aug 2026 18:00:00 GMT</pubDate>
                <category>Общество</category>
              </item>
            </channel></rss>
            """,
            "xml",
        )

        result = _parse_latest_rss(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Комсомольская правда")
        self.assertEqual(result[0]["date"], "2026-08-11")
        self.assertEqual(result[0]["edition_id"], "277805.4")
        self.assertEqual(result[0]["section"], "Политика")
        self.assertEqual(
            result[0]["url"],
            "https://www.kp.ru/daily/277805.4/5288487",
        )
        self.assertEqual(
            result[0]["summary"],
            "Краткий анонс свежей публикации.",
        )


if __name__ == "__main__":
    unittest.main()
