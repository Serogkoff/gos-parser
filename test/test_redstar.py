import unittest

from bs4 import BeautifulSoup

from parsers.sites.redstar import (
    _latest_issue_from_rss,
    _parse_articles_rss,
    _parse_issue_page,
    _parse_issue_rss,
    _parse_issue_strips,
)


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

    def test_reads_only_articles_from_latest_issue(self):
        issue_feed = BeautifulSoup(
            """
            <rss><channel><item>
              <title>11 августа 2026 г.</title>
              <link>http://redstar.ru/11-avgusta-2026-g/</link>
              <pubDate>Mon, 10 Aug 2026 21:00:00 +0000</pubDate>
            </item></channel></rss>
            """,
            "xml",
        )
        articles_feed = BeautifulSoup(
            """
            <rss><channel>
              <item>
                <title>Статья из свежего номера газеты</title>
                <link>http://redstar.ru/statya-iz-svezhego-nomera/</link>
                <pubDate>Mon, 10 Aug 2026 21:00:00 +0000</pubDate>
                <category>11 августа 2026 г.</category>
                <description>Анонс отдельной статьи со второй полосы номера.</description>
              </item>
              <item>
                <title>Статья из предыдущего номера газеты</title>
                <link>http://redstar.ru/statya-iz-starogo-nomera/</link>
                <category>10 августа 2026 г.</category>
              </item>
            </channel></rss>
            """,
            "xml",
        )

        issue = _latest_issue_from_rss(issue_feed)
        result = _parse_articles_rss(
            articles_feed,
            issue_title=issue["title"],
            issue_date=issue["date"],
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Статья из свежего номера газеты")
        self.assertEqual(result[0]["date"], "2026-08-11")

    def test_expands_issue_into_separate_strips_as_fallback(self):
        soup = BeautifulSoup(
            """
            <div class="entry-content">
              <figure>
                <a href="http://redstar.ru/?attachment_id=101">
                  <img src="http://redstar.ru/148_Stranitsa_1.jpg" />
                </a>
                <figcaption>1 полоса</figcaption>
              </figure>
              <figure>
                <a href="http://redstar.ru/?attachment_id=102">
                  <img src="http://redstar.ru/148_Stranitsa_2.jpg" />
                </a>
                <figcaption>2 полоса</figcaption>
              </figure>
            </div>
            """,
            "html.parser",
        )
        issue = {
            "title": "11 августа 2026 г.",
            "url": "http://redstar.ru/11-avgusta-2026-g/",
            "date": "2026-08-11",
        }

        result = _parse_issue_strips(soup, issue)

        self.assertEqual(len(result), 2)
        self.assertEqual(result[1]["title"], "11 августа 2026 г. — 2 полоса")
        self.assertEqual(result[1]["url"], "http://redstar.ru/?attachment_id=102")


if __name__ == "__main__":
    unittest.main()
