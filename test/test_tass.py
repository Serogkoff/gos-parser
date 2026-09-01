import unittest
from datetime import datetime, timezone
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import tass
from parsers.sites.tass import _parse_tass_date, _parse_tass_feed


RSS = """
<rss version="2.0">
  <channel>
    <item>
      <title>ТАСС сообщил о важном событии в России</title>
      <link>https://tass.ru/politika/123456</link>
      <pubDate>Wed, 29 Jul 2026 16:44:35 +0300</pubDate>
      <category>Политика</category>
      <description><![CDATA[<p>Короткий официальный анонс новости.</p>]]></description>
    </item>
    <item>
      <title>ТАСС сообщил о старом событии</title>
      <link>https://tass.ru/obschestvo/100000</link>
      <pubDate>Mon, 01 Jun 2026 10:00:00 +0300</pubDate>
      <category>Общество</category>
    </item>
  </channel>
</rss>
"""


class TassParserTests(unittest.TestCase):
    def test_reads_official_rss_fields_and_skips_old_items(self):
        soup = BeautifulSoup(RSS, "xml")

        news = _parse_tass_feed(
            soup,
            now=datetime(2026, 7, 29, 17, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(news), 1)
        self.assertEqual(news[0]["source"], "ТАСС")
        self.assertEqual(news[0]["date"], "2026-07-29")
        self.assertEqual(news[0]["section"], "Политика")
        self.assertEqual(
            news[0]["summary"],
            "Короткий официальный анонс новости.",
        )

    def test_understands_rss_timezone(self):
        self.assertEqual(
            _parse_tass_date("Wed, 29 Jul 2026 23:59:59 +0300"),
            "2026-07-29",
        )

    def test_parse_uses_one_official_feed_request(self):
        soup = BeautifulSoup(RSS, "xml")
        with mock.patch.object(tass, "fetch_soup", return_value=soup) as fetch:
            news = tass.parse(
                now=datetime(2026, 7, 29, 17, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(len(news), 1)
        fetch.assert_called_once_with(
            tass.FEED_URL,
            tass.SOURCE_NAME,
            timeout=30,
            verify=True,
            parser="xml",
        )


if __name__ == "__main__":
    unittest.main()
