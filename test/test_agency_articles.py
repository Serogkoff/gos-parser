import unittest
from unittest import mock

from bs4 import BeautifulSoup

from utils.article_reader import extract_article


class AgencyArticleReaderTests(unittest.TestCase):
    def test_ria_reads_only_full_text_blocks(self):
        soup = BeautifulSoup(
            """
            <html>
              <head>
                <meta property="og:title"
                      content="В аэропорту сняли временные ограничения">
              </head>
              <body>
                <h1 class="article__title">
                  В аэропорту сняли временные ограничения
                </h1>
                <div class="article__body">
                  <div class="article__summary">
                    Краткий пересказ от РИА ИИ с сокращённым описанием.
                  </div>
                  <div class="article__block" data-type="text">
                    <div class="article__text">
                      МОСКВА, 30 июл — РИА Новости. Ограничения на приём
                      и выпуск воздушных судов были полностью сняты.
                    </div>
                  </div>
                  <div class="article__block" data-type="text">
                    <div class="article__text">
                      Пострадавших нет.
                    </div>
                  </div>
                  <div class="media__description">
                    Пассажирский самолёт. Архивное фото.
                  </div>
                </div>
              </body>
            </html>
            """,
            "html.parser",
        )
        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ):
            article = extract_article(
                "https://ria.ru/20260730/airport-123456.html",
                "В аэропорту сняли временные ограничения",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertIn("РИА Новости", article["paragraphs"][0])
        self.assertEqual(article["paragraphs"][1], "Пострадавших нет.")
        self.assertNotIn(
            "Краткий пересказ",
            " ".join(article["paragraphs"]),
        )
        self.assertNotIn(
            "Архивное фото",
            " ".join(article["paragraphs"]),
        )

if __name__ == "__main__":
    unittest.main()
