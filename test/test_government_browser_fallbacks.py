import unittest
from datetime import datetime
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import minselkhoz, minstroy


MINSTROY_HTML = """
<html><body>
  <article class="item-new">
    <div class="new-date">02.11.2026</div>
    <div class="new-text">
      <a href="/press/minstroy-provel-operativnoe-soveshchanie/">
        Минстрой России провел еженедельное оперативное совещание
      </a>
    </div>
  </article>
</body></html>
"""

MINSELKHOZ_HTML = """
<html><body>
  <article class="newsList__wrapContent">
    <div class="b-date">2 ноября 2026</div>
    <a class="newsList__title"
       href="/press-service/news/minselkhoz-rasskazal-o-razvitii-apk/">
      Минсельхоз России рассказал о развитии агропромышленного комплекса
    </a>
  </article>
</body></html>
"""


class GovernmentBrowserFallbackTests(unittest.TestCase):
    def test_minstroy_uses_non_www_url_and_browser_after_empty_http_page(self):
        empty = BeautifulSoup("<html></html>", "html.parser")
        rendered = BeautifulSoup(MINSTROY_HTML, "html.parser")

        with (
            patch.object(minstroy, "fetch_soup", return_value=empty) as direct,
            patch.object(
                minstroy,
                "fetch_soup_js",
                return_value=rendered,
            ) as browser,
            patch.object(minstroy, "datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = datetime(2026, 11, 2, 12, 0)
            mocked_datetime.strptime = datetime.strptime
            items = minstroy.parse()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-11-02")
        self.assertEqual(direct.call_args.args[0], minstroy.BASE_URL)
        self.assertNotIn("www.", direct.call_args.args[0])
        self.assertTrue(browser.call_args.kwargs["browser_like"])
        self.assertNotIn("browser_channel", browser.call_args.kwargs)

    def test_minselkhoz_uses_system_edge_after_direct_timeout(self):
        rendered = BeautifulSoup(MINSELKHOZ_HTML, "html.parser")

        with (
            patch.object(minselkhoz, "fetch_soup", return_value=None) as direct,
            patch.object(
                minselkhoz,
                "fetch_soup_js",
                return_value=rendered,
            ) as browser,
            patch.object(minselkhoz, "datetime") as mocked_datetime,
        ):
            mocked_datetime.now.return_value = datetime(2026, 11, 2, 12, 0)
            mocked_datetime.strptime = datetime.strptime
            items = minselkhoz.parse()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-11-02")
        self.assertEqual(direct.call_count, 1)
        self.assertEqual(browser.call_args.kwargs["browser_channel"], "msedge")
        self.assertTrue(browser.call_args.kwargs["reject_http_errors"])


if __name__ == "__main__":
    unittest.main()
