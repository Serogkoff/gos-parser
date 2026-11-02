import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import minobrnauki


LISTING_HTML = """
<html><body><main>
  <article class="news-item">
    <div class="news-item__date">2 ноября</div>
    <h3 class="news-item__title">
      <a href="/press-center/news/nauka/102119/">
        В ПетрГУ разработали беспроводную систему вибрационного мониторинга
      </a>
    </h3>
  </article>
</main></body></html>
"""


class MinobrnaukiParserTests(unittest.TestCase):
    def setUp(self):
        self.soup = BeautifulSoup(LISTING_HTML, "html.parser")
        self.now = datetime(2026, 11, 2, 12, 0)

    def test_first_page_uses_clean_non_www_url_and_current_card_markup(self):
        with (
            patch(
                "parsers.sites.minobrnauki.fetch_soup",
                side_effect=(self.soup, None),
            ) as fetch,
            patch(
                "parsers.sites.minobrnauki.fetch_soup_js",
                return_value=None,
            ),
        ):
            items = minobrnauki.parse(now=self.now)

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-11-02")
        self.assertEqual(
            items[0]["url"],
            "https://minobrnauki.gov.ru/press-center/news/nauka/102119/",
        )
        self.assertEqual(fetch.call_args_list[0].args[0], minobrnauki.BASE_URL)
        self.assertIn("PAGEN_1=2", fetch.call_args_list[1].args[0])
        self.assertIn("SIZEN_1=9", fetch.call_args_list[1].args[0])

    def test_browser_is_used_after_direct_request_is_blocked(self):
        with (
            patch(
                "parsers.sites.minobrnauki.fetch_soup",
                side_effect=(None, None),
            ),
            patch(
                "parsers.sites.minobrnauki.fetch_soup_js",
                side_effect=(self.soup, None),
            ) as browser,
        ):
            items = minobrnauki.parse(now=self.now)

        self.assertEqual(len(items), 1)
        self.assertEqual(browser.call_args_list[0].args[0], minobrnauki.BASE_URL)
        self.assertTrue(browser.call_args_list[0].kwargs["browser_like"])
        self.assertTrue(browser.call_args_list[0].kwargs["reject_http_errors"])


if __name__ == "__main__":
    unittest.main()
