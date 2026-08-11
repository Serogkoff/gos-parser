import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.minpromtorg import NEWS_URL, _parse_news_page, parse


PAGE_HTML = """
<html><body>
    <a href="/press-centre/news/">Все новости</a>
    <a href="/press-centre/news/aa36a925-5fa7-4b31-9531-88ecb3264252">
        <span>08.08.2026</span>
        <span>Состоялась 10-я встреча министров промышленности стран БРИКС</span>
    </a>
    <a href="/press-centre/news/old-item">
        01.06.2026 Слишком старый материал Минпромторга России
    </a>
</body></html>
"""


class MinpromtorgTests(unittest.TestCase):
    def test_reads_js_card_with_separate_date_and_title(self):
        soup = BeautifulSoup(PAGE_HTML, "html.parser")

        result = _parse_news_page(
            soup,
            NEWS_URL,
            datetime(2026, 7, 12),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["title"],
            "Состоялась 10-я встреча министров промышленности стран БРИКС",
        )
        self.assertEqual(result[0]["date"], "2026-08-08")
        self.assertEqual(
            result[0]["url"],
            f"{NEWS_URL}/aa36a925-5fa7-4b31-9531-88ecb3264252",
        )

    @patch("parsers.sites.minpromtorg.datetime")
    @patch("parsers.sites.minpromtorg.fetch_soup_js")
    @patch("parsers.sites.minpromtorg.fetch_soup")
    def test_uses_browser_when_plain_html_is_empty(
        self,
        fetch,
        fetch_js,
        mocked_datetime,
    ):
        mocked_datetime.now.return_value = datetime(2026, 8, 11)
        mocked_datetime.strptime = datetime.strptime
        fetch.return_value = BeautifulSoup("<html></html>", "html.parser")
        fetch_js.return_value = BeautifulSoup(PAGE_HTML, "html.parser")

        result = parse()

        self.assertEqual(len(result), 1)
        self.assertEqual(fetch.call_count, 2)
        fetch_js.assert_called_once_with(
            NEWS_URL,
            "Минпромторг",
            wait_ms=5000,
            timeout_ms=60000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )


if __name__ == "__main__":
    unittest.main()
