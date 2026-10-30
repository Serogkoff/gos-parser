import unittest
from unittest import mock

from bs4 import BeautifulSoup

from utils.article_reader import extract_article


class AgencyArticleReaderTests(unittest.TestCase):
    def test_meduza_uses_reader_after_vpn_and_browser_fail(self):
        payload = {
            "data": {
                "title": "Редакция сообщила новые подробности события",
                "content": (
                    "Первый большой абзац публикации содержит важные "
                    "подробности произошедшего события.\n\n"
                    "Второй большой абзац [содержит ссылку]"
                    "(https://example.com/context) и дополнительный контекст."
                ),
            }
        }
        with (
            mock.patch("utils.article_reader.fetch_soup", return_value=None),
            mock.patch("utils.article_reader.fetch_soup_js", return_value=None),
            mock.patch("utils.article_reader.fetch_json", return_value=payload) as reader,
        ):
            article = extract_article(
                "https://meduza.io/news/2026/10/30/test?utm_source=rss",
                "Запасной заголовок",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 2)
        self.assertEqual(
            article["title"],
            "Редакция сообщила новые подробности события",
        )
        self.assertNotIn("](https://", " ".join(article["paragraphs"]))
        self.assertEqual(
            reader.call_args.args[0],
            "https://r.jina.ai/http://meduza.io/news/2026/10/30/test",
        )
        self.assertEqual(
            reader.call_args.kwargs["request_headers"],
            {"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
        )

    def test_belta_reads_only_verified_article_body(self):
        soup = BeautifulSoup(
            """
            <html><head>
              <meta property="og:title" content="Беларусь расширяет сотрудничество">
            </head><body>
              <h1>Беларусь расширяет сотрудничество</h1>
              <div itemprop="articleBody">
                <div>30 октября, Минск /Корр. БЕЛТА/. Стороны подписали новое соглашение о сотрудничестве.</div>
                <div>Документ предусматривает реализацию совместных проектов в промышленности и энергетике.</div>
                <div>Представители двух стран продолжат переговоры по новым проектам в следующем месяце.-0-</div>
              </div>
              <div class="rubricNews">Читайте также другие новости рубрики и подпишитесь на обновления сайта.</div>
            </body></html>
            """,
            "html.parser",
        )
        with mock.patch(
            "utils.article_reader.fetch_soup",
            return_value=soup,
        ):
            article = extract_article(
                "https://belta.by/economics/view/test-808536-2026/",
                "Беларусь расширяет сотрудничество",
            )

        self.assertFalse(article["error"])
        self.assertEqual(len(article["paragraphs"]), 3)
        self.assertIn("Корр. БЕЛТА", article["paragraphs"][0])
        self.assertNotIn("Читайте также", " ".join(article["paragraphs"]))

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
