import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites import carnegie
from utils.article_reader import extract_article


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

        proxy_url = "socks5h://user:password@203.0.113.7:1080"
        with (
            patch.object(carnegie, "kyodo_proxy_url", return_value=proxy_url),
            patch.object(carnegie, "fetch_soup", side_effect=[listing, article]) as fetch,
        ):
            items = carnegie.parse()

        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["date"], "2026-09-30")
        self.assertEqual(items[0]["summary"], "Описание нового материала.")
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].kwargs["proxy_url"], proxy_url)
        self.assertEqual(fetch.call_args_list[1].kwargs["proxy_url"], proxy_url)

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
            patch.object(carnegie, "kyodo_proxy_url", return_value="proxy-route"),
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
            proxy_url="proxy-route",
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Материал, загруженный браузером")
        self.assertEqual(items[0]["date"], "2026-09-30")

    def test_invalid_proxy_setting_falls_back_without_crashing(self):
        with (
            patch.object(
                carnegie,
                "kyodo_proxy_url",
                side_effect=ValueError("неверный адрес"),
            ),
            patch.object(carnegie.logger, "warning") as warning,
        ):
            self.assertEqual(carnegie._proxy_url(), "")

        warning.assert_called_once()

    def test_internal_reader_loads_carnegie_text_through_vpn(self):
        title = "Новый аналитический материал Берлинского центра Карнеги"
        article = self._soup(
            f"""
            <meta property="og:title" content="{title}">
            <main>
              <div class="cms-html payload-richtext">
                <p>Первый содержательный абзац публикации длиной больше сорока пяти символов.</p>
                <p>Второй содержательный абзац с продолжением анализа международной ситуации.</p>
              </div>
              <article>
                <p>Посторонняя карточка другого материала, которая не должна попасть в текст.</p>
              </article>
            </main>
            """
        )
        proxy_url = "socks5h://user:password@203.0.113.7:1080"

        with (
            patch(
                "utils.article_reader.kyodo_proxy_url",
                return_value=proxy_url,
            ),
            patch(
                "utils.article_reader.fetch_soup",
                return_value=article,
            ) as fetch,
        ):
            result = extract_article(
                "https://carnegieendowment.org/ru/russia-eurasia/"
                "politika/2026/09/test-story",
                title,
            )

        self.assertFalse(result["error"])
        self.assertEqual(len(result["paragraphs"]), 2)
        self.assertIn("Первый содержательный", result["paragraphs"][0])
        self.assertNotIn(
            "Посторонняя карточка",
            " ".join(result["paragraphs"]),
        )
        self.assertEqual(fetch.call_args.kwargs["proxy_url"], proxy_url)


if __name__ == "__main__":
    unittest.main()
