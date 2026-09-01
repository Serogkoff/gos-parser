import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import yonhap
from parsers.sites.yonhap import (
    _is_yonhap_article_url,
    _parse_yonhap_date,
    _parse_yonhap_feed,
)
from utils import keywords
from utils.article_reader import extract_article


YONHAP_RSS = """
<rss version="2.0"
     xmlns:dc="http://purl.org/dc/elements/1.1/"
     xmlns:media="http://search.yahoo.com/mrss/">
  <channel>
    <item>
      <title><![CDATA[북한과 러시아가 새로운 협력 계획을 발표했다]]></title>
      <link>https://www.yna.co.kr/view/AKR20260731148500504</link>
      <pubDate>Fri, 31 Jul 2026 17:31:37 +0900</pubDate>
      <dc:creator>김지헌</dc:creator>
      <description><![CDATA[(서울=연합뉴스) 북한과 러시아 관련 공식 발표가 나왔다.]]></description>
      <media:content url="https://img.yna.co.kr/test.jpg" type="image/jpeg"/>
    </item>
  </channel>
</rss>
"""


class YonhapParserTests(unittest.TestCase):
    def test_reads_official_feed_fields(self):
        result = _parse_yonhap_feed(
            BeautifulSoup(YONHAP_RSS, "xml"),
            now=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Yonhap")
        self.assertEqual(result[0]["date"], "2026-07-31")
        self.assertEqual(result[0]["section"], "Северная Корея")
        self.assertEqual(result[0]["author"], "김지헌")
        self.assertIn("북한과 러시아", result[0]["summary"])
        self.assertEqual(result[0]["image"], "https://img.yna.co.kr/test.jpg")

    def test_accepts_only_yonhap_article_urls(self):
        self.assertTrue(
            _is_yonhap_article_url(
                "https://www.yna.co.kr/view/AKR20260731148500504"
            )
        )
        self.assertFalse(_is_yonhap_article_url("https://www.yna.co.kr/nk/index"))
        self.assertFalse(_is_yonhap_article_url("https://example.com/view/AKR123"))

    def test_understands_korean_timezone(self):
        self.assertEqual(
            _parse_yonhap_date("Fri, 31 Jul 2026 23:59:00 +0900"),
            "2026-07-31",
        )

    def test_parse_requests_official_rss_once(self):
        soup = BeautifulSoup(YONHAP_RSS, "xml")
        with mock.patch.object(yonhap, "fetch_soup", return_value=soup) as fetch:
            result = yonhap.parse(
                now=datetime(2026, 7, 31, 12, 0, tzinfo=timezone.utc),
            )

        self.assertEqual(len(result), 1)
        fetch.assert_called_once_with(
            yonhap.FEED_URL,
            yonhap.SOURCE_NAME,
            timeout=30,
            verify=True,
            parser="xml",
        )

    def test_korean_keywords_are_seeded_once_and_search_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            keyword_file = Path(temp_dir) / "keywords.json"
            migration_file = Path(temp_dir) / "migrations.json"
            with mock.patch.object(keywords, "KEYWORDS_FILE", keyword_file), mock.patch.object(
                keywords,
                "KEYWORD_MIGRATIONS_FILE",
                migration_file,
            ):
                active = keywords.load_keywords()
                self.assertIn("일본", active)
                self.assertIn("군사훈련", active)

                found = keywords.search_keywords(
                    [
                        {
                            "source": "Yonhap",
                            "title": "새로운 소식",
                            "summary": "일본에서 군사훈련 관련 발표가 나왔다.",
                        }
                    ]
                )
                self.assertEqual(found[0]["keywords"], ["일본", "군사훈련"])

                keywords.save_keywords(
                    word for word in active if word != "군사훈련"
                )
                self.assertNotIn("군사훈련", keywords.load_keywords())

    def test_internal_reader_extracts_only_yonhap_article_body(self):
        soup = BeautifulSoup(
            """
            <html>
              <head>
                <meta property="og:title" content="북한과 러시아가 새로운 협력 계획을 발표했다 | 연합뉴스">
              </head>
              <body>
                <header class="title-article01">
                  <h1 class="tit01">북한과 러시아가 새로운 협력 계획을 발표했다</h1>
                  <article class="story-summary"><p>AI 세 줄 요약입니다.</p></article>
                </header>
                <article id="articleWrap">
                  <div class="story-news article">
                    <figure><figcaption><p>사진 설명입니다.</p></figcaption></figure>
                    <p>북한과 러시아가 새로운 협력 계획을 공식 발표했다고 관계 기관이 밝혔다.</p>
                    <aside><p>광고 문구입니다.</p></aside>
                    <p>두 번째 본문 문단에는 발표의 자세한 내용과 향후 일정이 담겨 있다.</p>
                    <p>reporter@yna.co.kr</p>
                    <p class="txt-copyright">저작권자 연합뉴스 무단 전재 금지</p>
                  </div>
                </article>
              </body>
            </html>
            """,
            "html.parser",
        )
        with mock.patch("utils.article_reader.fetch_soup", return_value=soup):
            article = extract_article(
                "https://www.yna.co.kr/view/AKR20260731148500504",
                "북한과 러시아가 새로운 협력 계획을 발표했다",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertNotIn("AI", " ".join(article["paragraphs"]))
        self.assertNotIn("광고", " ".join(article["paragraphs"]))


if __name__ == "__main__":
    unittest.main()
