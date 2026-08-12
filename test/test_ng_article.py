import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from utils.article_reader import _ng_mirror_url, extract_article


class NgArticleReaderTests(unittest.TestCase):
    def test_builds_google_copy_url_without_original_query(self):
        result = _ng_mirror_url(
            "https://www.ng.ru/world/2026-08-11/1_9557_story.html?utm_source=x"
        )

        self.assertEqual(
            result,
            "https://www-ng-ru.translate.goog/world/2026-08-11/1_9557_story.html"
            "?_x_tr_sl=auto&_x_tr_tl=ru&_x_tr_hl=ru",
        )

    def test_reads_ng_article_only_through_google_copy(self):
        soup = BeautifulSoup(
            """
            <html><head>
                <meta property="og:title" content="Полный материал свежего номера">
            </head><body>
                <h1>Полный материал свежего номера</h1>
                <article class="typical">
                    <p>Первый содержательный абзац публикации Независимой газеты.</p>
                    <p>Второй содержательный абзац публикации Независимой газеты.</p>
                </article>
            </body></html>
            """,
            "html.parser",
        )
        original = "https://www.ng.ru/world/2026-08-11/1_9557_story.html"

        with patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ) as fetch, patch(
            "utils.article_reader.fetch_soup_js",
        ) as browser:
            result = extract_article(original, "Полный материал свежего номера")

        requested_url = fetch.call_args.args[0]
        self.assertEqual(fetch.call_count, 1)
        self.assertTrue(requested_url.startswith("https://www-ng-ru.translate.goog/"))
        self.assertNotIn("https://www.ng.ru/", requested_url)
        self.assertEqual(fetch.call_args.kwargs["attempts"], 1)
        browser.assert_not_called()
        self.assertFalse(result["error"])
        self.assertEqual(len(result["paragraphs"]), 2)


if __name__ == "__main__":
    unittest.main()
