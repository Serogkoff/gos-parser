import unittest

from bs4 import BeautifulSoup

from parsers.sites.kommersant import _extract_latest_issue, _parse_daily_rss


class KommersantTests(unittest.TestCase):
    def test_extracts_first_fresh_issue_without_incrementing_id(self):
        soup = BeautifulSoup(
            """
            <section>
              <article>
                <a href="/daily/166441">№141</a>
                <span>06 августа 2026 г., Чт</span>
              </article>
              <article>
                <a href="/daily/166440">№140</a>
                <span>05 августа 2026 г., Ср</span>
              </article>
            </section>
            """,
            "html.parser",
        )
        issue = _extract_latest_issue(soup)
        self.assertEqual(issue["id"], "166441")
        self.assertEqual(issue["number"], "141")
        self.assertEqual(issue["date"], "2026-08-06")

    def test_reads_articles_from_full_daily_rss(self):
        soup = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Тестовый материал свежего номера Коммерсанта</title>
              <link>https://www.kommersant.ru/doc/8863491</link>
              <pubDate>Thu, 06 Aug 2026 08:00:00 +0300</pubDate>
              <description><![CDATA[<p>Краткий анонс материала.</p>]]></description>
            </item></channel></rss>
            """,
            "xml",
        )
        result = _parse_daily_rss(
            soup,
            issue={"id": "166441", "date": "2026-08-06"},
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Коммерсантъ")
        self.assertEqual(result[0]["date"], "2026-08-06")
        self.assertEqual(result[0]["edition_id"], "166441")
        self.assertEqual(result[0]["summary"], "Краткий анонс материала.")


if __name__ == "__main__":
    unittest.main()
