import unittest
from unittest import mock

from bs4 import BeautifulSoup

from parsers.sites import sakhalin


class SakhalinStabilityTests(unittest.TestCase):
    def test_uses_short_browser_load_and_limits_detail_requests(self):
        links = "".join(
            f'<a href="/news/{index}">Достаточно длинный заголовок новости номер {index}</a>'
            for index in range(12)
        )
        soup = BeautifulSoup(f"<main>{links}</main>", "html.parser")

        with mock.patch.object(
            sakhalin,
            "fetch_soup_js",
            return_value=soup,
        ) as browser, mock.patch.object(
            sakhalin,
            "date_from_news_card",
            return_value="",
        ), mock.patch.object(
            sakhalin,
            "fetch_soup",
            return_value=None,
        ) as detail:
            result = sakhalin.parse()

        self.assertEqual(len(result), 12)
        self.assertEqual(browser.call_count, 2)
        self.assertEqual(detail.call_count, 8)
        self.assertEqual(browser.call_args.kwargs["timeout_ms"], 25000)
        self.assertEqual(browser.call_args.kwargs["wait_until"], "domcontentloaded")
        self.assertTrue(browser.call_args.kwargs["use_partial_on_timeout"])


if __name__ == "__main__":
    unittest.main()
