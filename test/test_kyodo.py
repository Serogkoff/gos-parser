import json
import tempfile
import unittest
import warnings
from datetime import datetime
from pathlib import Path
from unittest import mock

import requests
from bs4 import BeautifulSoup

from parsers.sites import kyodo
from parsers.sites.kyodo import (
    _clean_summary,
    _is_47news_article_url,
    _parse_47news_page,
)
from utils.article_reader import extract_article


def _page_soup(page_props):
    payload = json.dumps(
        {"props": {"pageProps": page_props}},
        ensure_ascii=False,
    )
    return BeautifulSoup(
        f'<script id="__NEXT_DATA__" type="application/json">{payload}</script>',
        "html.parser",
    )


KYODO_ITEM = {
    "id": "14718157",
    "title": "ロシアと日本の代表団が会談",
    "url": "/14718157.html",
    "startDate": "2026-07-31 19:13:52",
    "body": "ロシアと日本の代表団が重要な問題について協議した。 ... ",
    "image": {"url": "https://img.cf.47news.jp/photo.jpg"},
    "user": {"title": "共同通信"},
}


class KyodoParserTests(unittest.TestCase):
    def test_reads_sections_and_filters_other_newspapers(self):
        local_item = {
            **KYODO_ITEM,
            "id": "999",
            "url": "/999.html",
            "title": "地方紙だけの記事",
            "user": {"title": "北海道新聞"},
        }
        soup = _page_soup(
            {
                "worldNews": [KYODO_ITEM, local_item],
                "politicsNews": [{**KYODO_ITEM, "title": "重複記事"}],
            }
        )

        result = _parse_47news_page(
            soup,
            now=datetime(2026, 7, 31, 20, 0),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Киодо (共同通信)")
        self.assertEqual(result[0]["section"], "Международные новости")
        self.assertEqual(result[0]["date"], "2026-07-31")
        self.assertEqual(
            result[0]["url"],
            "https://www.47news.jp/14718157.html",
        )
        self.assertNotIn("...", result[0]["summary"])

    def test_reads_top_news_nested_article_list(self):
        result = _parse_47news_page(
            _page_soup({"topNews": {"Article": [KYODO_ITEM]}}),
            now=datetime(2026, 7, 31, 20, 0),
        )
        self.assertEqual(result[0]["section"], "Главное")

    def test_reads_lightweight_kyodo_news_page(self):
        result = _parse_47news_page(
            {"data": {"categoryNewsList": [KYODO_ITEM]}},
            now=datetime(2026, 7, 31, 20, 0),
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["section"], "Все новости")

    def test_accepts_only_numbered_47news_articles(self):
        self.assertTrue(
            _is_47news_article_url("https://www.47news.jp/14718157.html")
        )
        self.assertFalse(_is_47news_article_url("https://www.47news.jp/world"))
        self.assertFalse(
            _is_47news_article_url("https://example.com/14718157.html")
        )

    def test_plain_summary_does_not_trigger_markup_locator_warning(self):
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            summary = _clean_summary("exchange-rate-14.html")
        self.assertEqual(summary, "exchange-rate-14.html")

    def test_publisher_description_is_not_used_as_summary(self):
        self.assertEqual(
            _clean_summary(
                "国内外約100の拠点を軸に、世界情勢から地域の話題まで、"
                "旬のニュースを的確に、いち早くお届けします。"
            ),
            "",
        )

    def test_parse_uses_compact_next_data(self):
        page_props = {"worldNews": [KYODO_ITEM]}
        with mock.patch.object(
            kyodo,
            "_fetch_page_props",
            return_value=page_props,
        ) as fetch, mock.patch.object(
            kyodo,
            "_fetch_category_page_props",
            return_value={},
        ):
            result = kyodo.parse()

        self.assertEqual(len(result), 1)
        fetch.assert_called_once_with()

    def test_parse_collects_distinct_category_feeds(self):
        def page(number):
            return {
                "data": {
                    "categoryNewsList": [{
                        **KYODO_ITEM,
                        "id": str(number),
                        "url": f"/{number}.html",
                        "title": f"共同通信のニュース記事 {number}",
                    }],
                    "categoryNewsListCount": 220,
                }
            }

        with mock.patch.object(
            kyodo,
            "_fetch_page_props",
            return_value=page(1),
        ), mock.patch.object(
            kyodo,
            "CATEGORY_ROUTES",
            (("Политика", "/news/politics/"), ("Экономика", "/news/economics/")),
        ), mock.patch.object(
            kyodo,
            "_fetch_category_page_props",
            side_effect=[page(2), page(3)],
        ) as categories:
            result = kyodo.parse()

        self.assertEqual(len(result), 3)
        self.assertEqual([item["source_id"] for item in result], ["1", "2", "3"])
        self.assertEqual(result[1]["section"], "Политика")
        self.assertEqual(result[2]["section"], "Экономика")
        self.assertEqual(
            categories.call_args_list,
            [mock.call("/news/politics/"), mock.call("/news/economics/")],
        )

    def test_browser_fallback_refreshes_next_build_id(self):
        soup = _page_soup({"worldNews": [KYODO_ITEM]})
        script = soup.find("script", id="__NEXT_DATA__")
        payload = json.loads(script.string)
        payload["buildId"] = "new-build-id"
        script.string = json.dumps(payload, ensure_ascii=False)

        response = mock.Mock()
        response.raise_for_status.side_effect = requests.HTTPError("old build")
        old_build_id = kyodo._next_build_id
        try:
            with tempfile.TemporaryDirectory() as directory, mock.patch.object(
                kyodo,
                "BUILD_ID_FILE",
                Path(directory) / "kyodo-build.txt",
            ), mock.patch.object(kyodo.requests, "get", return_value=response), mock.patch.object(
                kyodo,
                "_fetch_page_props_with_curl",
                return_value={},
            ), mock.patch.object(
                kyodo,
                "_fetch_news_payload_http",
                return_value={},
            ), mock.patch.object(
                kyodo,
                "_fetch_news_payload_with_curl",
                return_value={},
            ), mock.patch.object(
                kyodo,
                "fetch_soup_js",
                return_value=soup,
            ) as browser:
                page_props = kyodo._fetch_page_props()

            self.assertIn("worldNews", page_props)
            self.assertEqual(kyodo._next_build_id, "new-build-id")
            browser.assert_called_once()
        finally:
            kyodo._next_build_id = old_build_id

    def test_http_news_page_refreshes_build_without_browser(self):
        soup = _page_soup({"data": {"categoryNewsList": [KYODO_ITEM]}})
        script = soup.find("script", id="__NEXT_DATA__")
        payload = json.loads(script.string)
        payload["buildId"] = "current-build"
        script.string = json.dumps(payload, ensure_ascii=False)

        response = mock.Mock(content=str(soup).encode("utf-8"))
        response.raise_for_status.return_value = None
        with mock.patch.object(kyodo.requests, "get", return_value=response):
            payload = kyodo._fetch_news_payload_http()

        self.assertEqual(payload["buildId"], "current-build")
        self.assertIn("categoryNewsList", payload["props"]["pageProps"]["data"])

    def test_build_id_is_saved_between_isolated_runs(self):
        with tempfile.TemporaryDirectory() as directory, mock.patch.object(
            kyodo,
            "BUILD_ID_FILE",
            Path(directory) / "kyodo-build.txt",
        ):
            kyodo._save_build_id("fresh-build")
            self.assertEqual(kyodo._load_build_id(), "fresh-build")

    def test_curl_fallback_reads_compact_feed(self):
        payload = json.dumps(
            {"pageProps": {"data": {"categoryNewsList": [KYODO_ITEM]}}},
            ensure_ascii=False,
        ).encode("utf-8")
        completed = mock.Mock(stdout=payload)
        with mock.patch.object(kyodo.shutil, "which", return_value="curl.exe"), mock.patch.object(
            kyodo.subprocess,
            "run",
            return_value=completed,
        ):
            page_props = kyodo._fetch_page_props_with_curl("https://example.test/news.json")

        self.assertEqual(
            page_props["data"]["categoryNewsList"][0]["title"],
            KYODO_ITEM["title"],
        )

    def test_internal_reader_uses_full_article_json(self):
        page_props = {
            "data": {
                "article": {
                    **KYODO_ITEM,
                    "body": """
                        <p>ロシアと日本の代表団が重要な問題について協議した。</p>
                        <p>会談では今後の協力と国際情勢について意見を交換した。</p>
                    """,
                }
            }
        }
        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=_page_soup(page_props),
        ):
            article = extract_article(
                "https://www.47news.jp/14718157.html",
                KYODO_ITEM["title"],
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("今後の協力", article["paragraphs"][1])

    def test_internal_reader_routes_only_kyodo_through_proxy(self):
        page_props = {
            "data": {
                "article": {
                    **KYODO_ITEM,
                    "body": "<p>ロシアと日本の代表団が重要な問題について協議した。</p>",
                }
            }
        }
        proxy_url = "socks5h://user:password@203.0.113.7:1080"
        with mock.patch(
            "utils.article_reader.kyodo_proxy_url",
            return_value=proxy_url,
        ), mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=_page_soup(page_props),
        ) as fetch:
            article = extract_article(
                "https://www.47news.jp/14718157.html",
                KYODO_ITEM["title"],
            )

        self.assertFalse(article["error"])
        self.assertEqual(fetch.call_args.kwargs["proxy_url"], proxy_url)

    def test_internal_reader_rejects_publisher_description(self):
        page_props = {
            "data": {
                "article": {
                    **KYODO_ITEM,
                    "body": (
                        "<p>国内外約100の拠点を軸に、世界情勢から地域の話題まで、"
                        "旬のニュースを的確に、いち早くお届けします。</p>"
                    ),
                }
            }
        }
        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=_page_soup(page_props),
        ):
            article = extract_article(
                "https://www.47news.jp/14718157.html",
                KYODO_ITEM["title"],
            )

        self.assertTrue(article["error"])
        self.assertEqual(article["paragraphs"], [])


if __name__ == "__main__":
    unittest.main()
