import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from utils.article_reader import _rg_mirror_url, extract_article


class RgArticleReaderTests(unittest.TestCase):
    def test_builds_google_copy_url_without_original_query(self):
        result = _rg_mirror_url(
            "https://rg.ru/2026/08/11/test.html?utm_source=x"
        )

        self.assertEqual(
            result,
            "https://rg-ru.translate.goog/2026/08/11/test.html"
            "?_x_tr_sl=auto&_x_tr_tl=ru&_x_tr_hl=ru",
        )

    def test_reads_rg_article_only_through_google_copy(self):
        soup = BeautifulSoup(
            """
            <html><head>
                <script type="application/ld+json">
                {
                  "@type": "Article",
                  "headline": "Полный материал Российской газеты",
                  "articleBody": "Первый содержательный абзац публикации.\\n\\nВторой содержательный абзац публикации."
                }
                </script>
            </head><body>
                <h1>Полный материал Российской газеты</h1>
            </body></html>
            """,
            "html.parser",
        )
        original = "https://rg.ru/2026/08/11/test.html"

        with patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ) as fetch, patch(
            "utils.article_reader.fetch_soup_js",
        ) as browser:
            result = extract_article(
                original,
                "Полный материал Российской газеты",
            )

        requested_url = fetch.call_args.args[0]
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(requested_url.startswith("https://rg-ru.translate.goog/"))
        self.assertNotIn("https://rg.ru/", requested_url)
        self.assertEqual(fetch.call_args.kwargs["attempts"], 1)
        browser.assert_not_called()
        self.assertFalse(result["error"])
        article_text = " ".join(result["paragraphs"])
        self.assertIn("Первый содержательный абзац", article_text)
        self.assertIn("Второй содержательный абзац", article_text)


if __name__ == "__main__":
    unittest.main()
