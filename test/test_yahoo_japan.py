import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from bs4 import BeautifulSoup

import main
from parsers.sites import yahoo_japan
from utils.article_reader import extract_article


class YahooJapanRssTests(unittest.TestCase):
    def _soup(self, items):
        return BeautifulSoup(
            "<?xml version='1.0' encoding='UTF-8'?>"
            "<rss version='2.0'><channel>"
            f"{items}"
            "</channel></rss>",
            "xml",
        )

    def test_parses_rss_fields_and_stops_at_old_news(self):
        soup = self._soup(
            "<item>"
            "<title>日本の新しいニュースです</title>"
            "<link>http://news.yahoo.co.jp/articles/abc123?source=rss</link>"
            "<pubDate>Thu, 20 Aug 2026 03:15:00 GMT</pubDate>"
            "<description><![CDATA[<p>公式の <b>概要</b> です。</p>]]></description>"
            "</item>"
            "<item>"
            "<title>保存期間より古いニュースです</title>"
            "<link>https://news.yahoo.co.jp/articles/old123</link>"
            "<pubDate>Mon, 01 Jun 2026 03:15:00 GMT</pubDate>"
            "</item>"
        )
        with patch.object(yahoo_japan, "fetch_soup", return_value=soup) as fetch:
            items = yahoo_japan.parse_feed(
                yahoo_japan.SOURCE_DOMESTIC,
                "国内",
                "https://news.yahoo.co.jp/rss/categories/domestic.xml",
                now=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

        self.assertEqual(
            items,
            [
                {
                    "source": yahoo_japan.SOURCE_DOMESTIC,
                    "title": "日本の新しいニュースです",
                    "url": "https://news.yahoo.co.jp/articles/abc123?source=rss",
                    "date": "2026-08-20",
                    "section": "国内",
                    "summary": "公式の 概要 です。",
                }
            ],
        )
        fetch.assert_called_once_with(
            "https://news.yahoo.co.jp/rss/categories/domestic.xml",
            yahoo_japan.SOURCE_DOMESTIC,
            timeout=30,
            verify=True,
            parser="xml",
        )

    def test_uses_comments_url_when_link_is_missing(self):
        soup = self._soup(
            "<item>"
            "<title>コメントURLから復元するニュース</title>"
            "<comments>https://news.yahoo.co.jp/articles/abc123/comments</comments>"
            "<pubDate>Thu, 20 Aug 2026 03:15:00 GMT</pubDate>"
            "</item>"
        )
        with patch.object(yahoo_japan, "fetch_soup", return_value=soup):
            items = yahoo_japan.parse_feed(
                yahoo_japan.SOURCE_TOP,
                "トップ",
                yahoo_japan.YAHOO_FEEDS[4][2],
                now=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

        self.assertEqual(
            items[0]["url"],
            "https://news.yahoo.co.jp/articles/abc123",
        )

    def test_rejects_article_url_from_another_domain(self):
        soup = self._soup(
            "<item>"
            "<title>外部サイトへ移動させるニュース</title>"
            "<link>https://example.com/articles/unsafe</link>"
            "<guid>https://evil.example/news/unsafe</guid>"
            "<pubDate>Thu, 20 Aug 2026 03:15:00 GMT</pubDate>"
            "</item>"
        )
        with patch.object(yahoo_japan, "fetch_soup", return_value=soup):
            items = yahoo_japan.parse_feed(
                yahoo_japan.SOURCE_WORLD,
                "国際",
                yahoo_japan.YAHOO_FEEDS[6][2],
                now=datetime(2026, 8, 20, tzinfo=timezone.utc),
            )

        self.assertEqual(items, [])

    def test_reads_selected_article_body_without_page_navigation(self):
        soup = BeautifulSoup(
            "<html><head><meta property='og:title' "
            "content='日本の新しいニュースです'></head><body>"
            "<nav><p>トップ 国内 国際 経済</p></nav>"
            "<h1>日本の新しいニュースです</h1>"
            "<div class='article_body'>"
            "<p>これは選択した記事の本文の第一段落です。</p>"
            "<p>これは選択した記事の本文の第二段落です。</p>"
            "</div></body></html>",
            "html.parser",
        )
        with patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ) as fetch:
            article = extract_article(
                "https://news.yahoo.co.jp/articles/abc123",
                "日本の新しいニュースです",
            )

        self.assertEqual(
            article["paragraphs"],
            [
                "これは選択した記事の本文の第一段落です。",
                "これは選択した記事の本文の第二段落です。",
            ],
        )
        self.assertNotIn("トップ 国内", " ".join(article["paragraphs"]))
        fetch.assert_called_once_with(
            "https://news.yahoo.co.jp/articles/abc123",
            "Просмотр новости",
            timeout=25,
            verify=False,
        )

    def test_registers_exact_requested_feeds_without_exclusions(self):
        urls = {url for _source, _section, url in yahoo_japan.YAHOO_FEEDS}
        expected = {
            "https://news.yahoo.co.jp/rss/topics/top-picks.xml",
            "https://news.yahoo.co.jp/rss/categories/domestic.xml",
            "https://news.yahoo.co.jp/rss/categories/world.xml",
            "https://news.yahoo.co.jp/rss/categories/business.xml",
            "https://news.yahoo.co.jp/rss/categories/it.xml",
            "https://news.yahoo.co.jp/rss/categories/life.xml",
            "https://news.yahoo.co.jp/rss/categories/local.xml",
            "https://news.yahoo.co.jp/rss/categories/entertainment.xml",
            "https://news.yahoo.co.jp/rss/media/jij/all.xml",
            "https://news.yahoo.co.jp/rss/media/aptsushinv/all.xml",
            "https://news.yahoo.co.jp/rss/media/cnn/all.xml",
            "https://news.yahoo.co.jp/rss/media/teikokudb/all.xml",
        }
        self.assertEqual(urls, expected)
        self.assertEqual(len(yahoo_japan.YAHOO_SITES), 12)
        self.assertFalse(any("sport" in url for url in urls))
        self.assertFalse(any("itmedia" in url for url in urls))
        self.assertFalse(any("impress" in url for url in urls))

    def test_provider_feeds_run_before_overlapping_topics(self):
        self.assertEqual(
            [name for name, _parser in yahoo_japan.YAHOO_SITES[:4]],
            [
                yahoo_japan.SOURCE_JIJI,
                yahoo_japan.SOURCE_AP,
                yahoo_japan.SOURCE_CNN,
                yahoo_japan.SOURCE_TEIKOKUDB,
            ],
        )
        registered = [name for name, _parser in main.SITES]
        for name, _parser in yahoo_japan.YAHOO_SITES:
            self.assertIn(name, registered)
        self.assertEqual(main._parse_arguments(["--once", "yahoo"]).once, "yahoo")


if __name__ == "__main__":
    unittest.main()
