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

    def test_tass_opens_browser_after_challenge_and_reads_full_text(self):
        challenge = BeautifulSoup(
            """
            <html>
              <script src="https://servicepipe.tech/loader.js"></script>
              <body><js-challenge-loader></js-challenge-loader></body>
            </html>
            """,
            "html.parser",
        )
        article_page = BeautifulSoup(
            """
            <html>
              <head>
                <meta property="og:title"
                      content="ТАСС сообщил о важном событии">
              </head>
              <body>
                <div class="ContentPageContainer_container__abc">
                  <h1>ТАСС сообщил о важном событии</h1>
                  <p>МОСКВА, 30 июля. /ТАСС/. Первый полный абзац
                  публикации содержит важные подробности события.</p>
                  <p>Второй полный абзац содержит дополнительную информацию
                  и комментарий официального представителя.</p>
                  <p>Пострадавших нет.</p>
                </div>
              </body>
            </html>
            """,
            "html.parser",
        )

        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=challenge,
        ), mock.patch(
            "utils.article_reader.fetch_soup_js",
            return_value=article_page,
        ) as browser_fetch:
            article = extract_article(
                "https://tass.ru/obschestvo/27967349",
                "ТАСС сообщил о важном событии",
            )

        browser_fetch.assert_called_once()
        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 3)
        self.assertIn("Первый полный абзац", article["paragraphs"][0])
        self.assertEqual(article["paragraphs"][2], "Пострадавших нет.")


if __name__ == "__main__":
    unittest.main()
