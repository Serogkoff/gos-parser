import unittest

from bs4 import BeautifulSoup

from parsers.sites.redstar import _parse_issue_page, _parse_issue_rss


class RedStarTests(unittest.TestCase):
    def test_reads_issue_cards(self):
        soup = BeautifulSoup(
            """
            <main><article>
              <h2><a href="https://redstar.ru/voennye-ucheniya-proshli-uspeshno/">
                Военные учения завершились успешно
              </a></h2>
              <time datetime="2026-08-11T08:00:00+03:00">11.08.2026</time>
              <p>Подробный анонс материала текущего номера военной газеты.</p>
            </article></main>
            """,
            "html.parser",
        )

        result = _parse_issue_page(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Красная звезда")
        self.assertEqual(result[0]["date"], "2026-08-11")

    def test_reads_category_rss_fallback(self):
        soup = BeautifulSoup(
            """
            <rss><channel><item>
              <title>Материал номера Красной звезды</title>
              <link>https://redstar.ru/material-nomera-krasnoj-zvezdy/</link>
              <pubDate>Tue, 11 Aug 2026 09:00:00 +0300</pubDate>
            </item></channel></rss>
            """,
            "xml",
        )
        result = _parse_issue_rss(soup)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["date"], "2026-08-11")


if __name__ == "__main__":
    unittest.main()
