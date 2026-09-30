import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import carnegie


class CarnegieParserTests(unittest.TestCase):
    @staticmethod
    def _soup(html):
        return BeautifulSoup(html, "html.parser")

    def test_listing_keeps_only_unique_russian_center_publications(self):
        soup = self._soup(
            """
            <a href="/ru/russia-eurasia/politika/2026/09/test-story?utm_source=test">
              Первый материал Берлинского центра Карнеги
            </a>
            <a href="/ru/russia-eurasia/politika/2026/09/test-story">
              Первый материал Берлинского центра Карнеги — полный заголовок
            </a>
            <a href="https://carnegieendowment.org/ru/russia-eurasia/research/2026/08/research-story">
              Исследование о России и Евразии
            </a>
            <a href="https://example.org/ru/russia-eurasia/politika/2026/09/foreign">
              Материал с другого сайта
            </a>
            """
        )

        items = carnegie._parse_listing(soup)

        self.assertEqual(len(items), 2)
        self.assertEqual(items[0]["source"], carnegie.SOURCE_NAME)
        self.assertEqual(
            items[0]["url"],
            "https://carnegieendowment.org/ru/russia-eurasia/politika/2026/09/test-story",
        )
        self.assertEqual(items[0]["date"], "2026-09-01")
        self.assertEqual(items[0]["section"], "Carnegie Politika")
        self.assertIn("полный заголовок", items[0]["title"])
        self.assertEqual(items[1]["section"], "Исследования")

    def test_article_metadata_supplies_exact_date_and_summary(self):
        soup = self._soup(
            """
            <meta property="article:published_time" content="2026-09-29T12:00:00.000Z">
            <meta property="og:description" content="  Краткое   описание публикации. ">
            """
        )

        self.assertEqual(
            carnegie._parse_article_metadata(soup),
            {
                "date": "2026-09-29",
                "summary": "Краткое описание публикации.",
            },
        )

    def test_parse_enriches_listing_with_article_metadata(self):
        listing = self._soup(
            """
            <a href="/ru/russia-eurasia/politika/2026/09/test-story">
              Новый материал Берлинского центра Карнеги
            </a>
            """
        )
        article = self._soup(
            """
            <meta property="article:published_time" content="2026-09-30T08:15:00Z">
            <meta property="og:description" content="Описание нового материала.">
            """
        )

        with patch.object(carnegie, "fetch_soup", side_effect=[listing, article]):
            items = carnegie.parse()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-09-30")
        self.assertEqual(items[0]["summary"], "Описание нового материала.")

    def test_parse_uses_browser_when_static_listing_has_no_cards(self):
        static_listing = self._soup("<main>Карточки загружаются…</main>")
        rendered_listing = self._soup(
            """
            <a href="/ru/russia-eurasia/politika/2026/09/browser-story">
              Материал, загруженный браузером
            </a>
            """
        )
        article = self._soup(
            """
            <meta property="article:published_time" content="2026-09-30T09:00:00Z">
            """
        )

        with (
            patch.object(carnegie, "fetch_soup", side_effect=[static_listing, article]),
            patch.object(
                carnegie,
                "fetch_soup_js",
                return_value=rendered_listing,
            ) as browser_fetch,
        ):
            items = carnegie.parse()

        browser_fetch.assert_called_once_with(
            carnegie.LISTING_URL,
            carnegie.SOURCE_NAME,
            wait_ms=2500,
            timeout_ms=45000,
            wait_until="domcontentloaded",
            use_partial_on_timeout=True,
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Материал, загруженный браузером")
        self.assertEqual(items[0]["date"], "2026-09-30")


if __name__ == "__main__":
    unittest.main()
