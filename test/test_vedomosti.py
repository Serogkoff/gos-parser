import unittest

from bs4 import BeautifulSoup

from parsers.sites.vedomosti import _parse_issue_rss


class VedomostiTests(unittest.TestCase):
    def test_reads_official_issue_feed(self):
        soup = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Деловой материал последнего номера Ведомостей</title>
              <link>https://www.vedomosti.ru/economics/articles/2026/08/11/123456-test</link>
              <pubDate>Tue, 11 Aug 2026 07:00:00 +0300</pubDate>
              <description><![CDATA[<p>Анонс делового материала.</p>]]></description>
            </item></channel></rss>
            """,
            "xml",
        )

        result = _parse_issue_rss(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Ведомости")
        self.assertEqual(result[0]["date"], "2026-08-11")
        self.assertEqual(result[0]["summary"], "Анонс делового материала.")


if __name__ == "__main__":
    unittest.main()
