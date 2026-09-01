import unittest
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import mid


class MidFeedTests(unittest.TestCase):
    def test_reads_primary_rss_with_date_and_summary(self):
        soup = BeautifulSoup(
            """
            <rss version="2.0"><channel>
              <item>
                <title>Комментарий официального представителя МИД России</title>
                <link>https://mid.ru/ru/foreign_policy/news/2050001/</link>
                <pubDate>Wed, 26 Aug 2026 12:40:00 +0300</pubDate>
                <description><![CDATA[<p>Новый официальный комментарий.</p>]]></description>
              </item>
            </channel></rss>
            """,
            "xml",
        )

        with mock.patch.object(mid, "_fetch_feed", return_value=soup) as fetch:
            result = mid.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "МИД РФ")
        self.assertEqual(result[0]["date"], "2026-08-26")
        self.assertEqual(
            result[0]["url"],
            "https://mid.ru/ru/foreign_policy/news/2050001",
        )
        self.assertEqual(result[0]["summary"], "Новый официальный комментарий.")
        fetch.assert_called_once_with(mid.PRIMARY_FEED_URL)

    def test_primary_html_challenge_uses_fallback_atom_feed(self):
        challenge = BeautifulSoup(
            "<html><script>window['bobcmn'] = 'challenge'</script></html>",
            "xml",
        )
        fallback = BeautifulSoup(
            """
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <title>Выступление Министра иностранных дел России</title>
                <link href="https://www.mid.ru/ru/foreign_policy/news/2050002/"
                      rel="alternate" />
                <published>2026-08-26T10:15:00+03:00</published>
                <summary>Текст официального выступления.</summary>
              </entry>
            </feed>
            """,
            "xml",
        )

        with mock.patch.object(
            mid,
            "_fetch_feed",
            side_effect=[challenge, fallback],
        ) as fetch:
            result = mid.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-26")
        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            [mid.PRIMARY_FEED_URL, mid.FALLBACK_FEED_URL],
        )

    def test_empty_primary_feed_uses_fallback_without_duplicates(self):
        empty = BeautifulSoup("<rss><channel /></rss>", "xml")
        fallback = BeautifulSoup(
            """
            <feed xmlns="http://www.w3.org/2005/Atom">
              <entry>
                <title>Сообщение для средств массовой информации</title>
                <id>https://mid.ru/ru/press_service/news/2050003/</id>
                <updated>2026-08-25T18:00:00+03:00</updated>
              </entry>
              <entry>
                <title>Сообщение для средств массовой информации</title>
                <id>https://mid.ru/ru/press_service/news/2050003/</id>
                <updated>2026-08-25T18:00:00+03:00</updated>
              </entry>
            </feed>
            """,
            "xml",
        )

        with mock.patch.object(
            mid,
            "_fetch_feed",
            side_effect=[empty, fallback],
        ):
            result = mid.parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-25")

    def test_fetches_feed_with_exact_minimal_headers(self):
        response = mock.Mock(
            content="""
                <feed xmlns="http://www.w3.org/2005/Atom">
                  <entry><title>МИД России</title></entry>
                </feed>
            """.encode("utf-8"),
        )

        with mock.patch.object(
            mid.requests,
            "get",
            return_value=response,
        ) as get:
            soup = mid._fetch_feed(mid.PRIMARY_FEED_URL)

        self.assertEqual(len(soup.find_all("entry")), 1)
        response.raise_for_status.assert_called_once_with()
        get.assert_called_once_with(
            mid.PRIMARY_FEED_URL,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36"
                ),
            },
            timeout=30,
        )

    def test_returns_empty_when_both_requests_fail(self):
        with mock.patch.object(mid, "_fetch_feed", return_value=None) as fetch:
            result = mid.parse()

        self.assertEqual(result, [])
        self.assertEqual(fetch.call_count, 2)

    def test_fetch_returns_none_on_network_error(self):
        with mock.patch.object(
            mid.requests,
            "get",
            side_effect=mid.requests.exceptions.ConnectionError("blocked"),
        ):
            result = mid._fetch_feed(mid.PRIMARY_FEED_URL)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
