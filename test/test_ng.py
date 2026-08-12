import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.ng import (
    FRESH_ISSUE_URL,
    RSS_URL,
    _parse_fresh_issue,
    _parse_markdown_issue,
    _parse_proxy_feed,
    _parse_rss,
    parse,
)


class NgFreshIssueTests(unittest.TestCase):
    def test_failed_run_makes_one_request_per_official_endpoint(self):
        with patch("parsers.sites.ng.fetch_soup", return_value=None) as fetch, patch(
            "parsers.sites.ng._fetch_issue_mirror",
            return_value=None,
        ) as issue_mirror, patch(
            "parsers.sites.ng._fetch_issue_proxy",
            return_value=None,
        ) as issue_proxy, patch(
            "parsers.sites.ng._fetch_rss_proxy",
            return_value=None,
        ) as rss_proxy:
            result = parse()

        self.assertEqual(result, [])
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(
            fetch.call_args_list[0].args,
            (FRESH_ISSUE_URL, "Независимая газета"),
        )
        self.assertEqual(fetch.call_args_list[0].kwargs["attempts"], 1)
        self.assertEqual(
            fetch.call_args_list[1].args,
            (RSS_URL, "Независимая газета · RSS"),
        )
        self.assertEqual(fetch.call_args_list[1].kwargs["parser"], "xml")
        self.assertEqual(fetch.call_args_list[1].kwargs["attempts"], 1)
        issue_mirror.assert_called_once_with()
        issue_proxy.assert_called_once_with()
        rss_proxy.assert_called_once_with()

    def test_rss_fallback_keeps_only_newest_day(self):
        soup = BeautifulSoup(
            """
            <rss><channel>
                <item>
                    <title>Свежий материал Независимой газеты</title>
                    <link>https://www.ng.ru/news/200.html</link>
                    <pubDate>Tue, 11 Aug 2026 15:20:00 +0300</pubDate>
                    <description><![CDATA[Краткий официальный анонс свежего материала газеты.]]></description>
                </item>
                <item>
                    <title>Второй свежий материал Независимой газеты</title>
                    <link>https://www.ng.ru/news/201.html</link>
                    <pubDate>Tue, 11 Aug 2026 12:00:00 +0300</pubDate>
                </item>
                <item>
                    <title>Вчерашний материал Независимой газеты</title>
                    <link>https://www.ng.ru/news/199.html</link>
                    <pubDate>Mon, 10 Aug 2026 18:00:00 +0300</pubDate>
                </item>
            </channel></rss>
            """,
            "xml",
        )

        result = _parse_rss(soup)

        self.assertEqual(len(result), 2)
        self.assertTrue(all(item["date"] == "2026-08-11" for item in result))
        self.assertTrue(
            all(item["section"] == "Онлайн НГ · резерв" for item in result)
        )
        self.assertIn("официальный анонс", result[0]["summary"])

    def test_external_gateway_keeps_only_newest_day(self):
        result = _parse_proxy_feed({
            "status": "ok",
            "items": [
                {
                    "title": "Свежая публикация Независимой газеты",
                    "link": "https://www.ng.ru/news/301.html",
                    "pubDate": "2026-08-12 06:45:00",
                    "description": "Официальный анонс свежей публикации НГ.",
                },
                {
                    "title": "Предыдущая публикация Независимой газеты",
                    "link": "https://www.ng.ru/news/300.html",
                    "pubDate": "2026-08-11 21:00:00",
                    "description": "Официальный анонс предыдущего материала.",
                },
            ],
        })

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-12")
        self.assertEqual(result[0]["section"], "Онлайн НГ · резерв")

    def test_markdown_gateway_reads_complete_current_issue(self):
        result = _parse_markdown_issue(
            """
            Title: Свежий номер
            Среда 12.08.2026 10:11
            [Старый материал выпуска](https://www.ng.ru/world/2026-08-05/1_9553_old.html)
            [Первый материал свежего номера](https://www.ng.ru/world/2026-08-11/1_9557_first.html)
            ### [Второй материал свежего номера](https://www.ng.ru/politics/2026-08-11/3_9557_second.html)
            [Первый материал свежего номера](https://www.ng.ru/world/2026-08-11/1_9557_first.html)
            """
        )

        self.assertEqual(len(result), 2)
        self.assertTrue(all("_9557_" in item["url"] for item in result))
        self.assertTrue(all(item["date"] == "2026-08-11" for item in result))
        self.assertTrue(
            all(item["edition_date"] == "2026-08-12" for item in result)
        )

    def test_reads_only_articles_from_current_issue(self):
        soup = BeautifulSoup(
            """
            <html><body>
                <div role="main">
                    <h1 class="htitle">Газета
                        <span class="num">2026-08-06 142 (9553)</span>
                    </h1>
                    <div class="anonce">
                        <h3><a href="/world/2026-08-05/1_9553_iran.html">
                            Ормузский пролив поделят на юг и север
                            <span class="numnpage">(5 полоса)</span>
                        </a></h3>
                    </div>
                    <div class="anonce">
                        <h3><a href="/world/2026-08-05/1_9553_iran.html">
                            Ормузский пролив поделят на юг и север
                        </a></h3>
                    </div>
                    <div class="anonce">
                        <h3><a href="/politics/2026-08-04/1_9552_old.html">
                            Материал предыдущего номера
                        </a></h3>
                    </div>
                </div>
            </body></html>
            """,
            "html.parser",
        )

        result = _parse_fresh_issue(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Независимая газета")
        self.assertEqual(
            result[0]["title"],
            "Ормузский пролив поделят на юг и север",
        )
        self.assertEqual(result[0]["date"], "2026-08-05")
        self.assertEqual(result[0]["edition_date"], "2026-08-06")

    def test_restores_original_links_from_google_issue_copy(self):
        soup = BeautifulSoup(
            """
            <div role="main">
                <h1 class="htitle">Газета
                    <span class="num">2026-08-12 146 (9557)</span>
                </h1>
                <div class="anonce"><h3>
                    <a href="https://www-ng-ru.translate.goog/world/2026-08-11/1_9557_story.html?_x_tr_sl=auto&amp;_x_tr_tl=ru">
                        Полный материал свежего выпуска газеты
                    </a>
                </h3></div>
            </div>
            """,
            "html.parser",
        )

        result = _parse_fresh_issue(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["url"],
            "https://www.ng.ru/world/2026-08-11/1_9557_story.html",
        )


if __name__ == "__main__":
    unittest.main()
