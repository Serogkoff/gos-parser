import unittest

from bs4 import BeautifulSoup

from parsers.sites.sk import _date_from_sk_article


class SkPublicationDateTests(unittest.TestCase):
    def test_uses_date_displayed_on_article_page(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-27T18:20:00+03:00">
                </head>
                <body>
                    <div class="page-date">29 июля 2026</div>
                    <article>
                        <h1>Публикация Следственного комитета</h1>
                        <div class="news-item__date">28 Июля 2026</div>
                        <div class="news-item__time">18:20</div>
                    </article>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(soup),
            "2026-07-28",
        )

    def test_falls_back_to_publication_metadata(self):
        soup = BeautifulSoup(
            """
            <html>
                <head>
                    <meta property="article:published_time"
                          content="2026-07-29T10:15:00+03:00">
                </head>
                <body>
                    <h1>Другой шаблон страницы СК</h1>
                </body>
            </html>
            """,
            "html.parser",
        )

        self.assertEqual(
            _date_from_sk_article(soup),
            "2026-07-29",
        )

    def test_returns_empty_date_when_article_is_unavailable(self):
        self.assertEqual(_date_from_sk_article(None), "")


if __name__ == "__main__":
    unittest.main()
