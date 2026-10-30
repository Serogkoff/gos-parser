import unittest
from datetime import datetime, timezone
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import belta


FEED = """
<rss version="2.0"><channel>
  <item>
    <title>Беларусь и Россия расширяют сотрудничество в промышленности</title>
    <description><![CDATA[<p>Официальный анонс материала БЕЛТА.</p>]]></description>
    <link>https://www.belta.by/economics/view/belarus-i-rossija-808536-2026/?utm_source=rss</link>
    <category>Экономика</category>
    <pubDate>Fri, 30 Oct 2026 13:06:29 +0300</pubDate>
  </item>
  <item>
    <title>Служебная ссылка</title>
    <link>https://belta.by/contacts/</link>
    <pubDate>Fri, 30 Oct 2026 12:00:00 +0300</pubDate>
  </item>
</channel></rss>
"""


class BeltaParserTests(unittest.TestCase):
    def test_parses_official_rss_and_normalizes_article_url(self):
        soup = BeautifulSoup(FEED, "xml")
        items = belta._parse_belta_feed(
            soup,
            now=datetime(2026, 10, 30, 14, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["source"], "БЕЛТА")
        self.assertEqual(items[0]["date"], "2026-10-30")
        self.assertEqual(items[0]["section"], "Экономика")
        self.assertEqual(
            items[0]["url"],
            "https://belta.by/economics/view/belarus-i-rossija-808536-2026",
        )
        self.assertEqual(
            items[0]["summary"],
            "Официальный анонс материала БЕЛТА.",
        )

    def test_one_broken_feed_does_not_break_scheduler_contract(self):
        with mock.patch.object(belta, "fetch_soup", return_value=None):
            self.assertEqual(belta.parse(), [])


if __name__ == "__main__":
    unittest.main()
