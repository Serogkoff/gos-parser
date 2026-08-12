import unittest

from bs4 import BeautifulSoup

from parsers.sites.kremlin import _parse_feed


class KremlinFeedTests(unittest.TestCase):
    def test_reads_atom_date_link_and_full_text(self):
        soup = BeautifulSoup(
            """
            <feed xmlns="http://www.w3.org/2005/Atom">
                <entry>
                    <title>Встреча Президента с руководителем региона</title>
                    <id>http://kremlin.ru/events/president/news/80509</id>
                    <published>2026-08-11T19:00:00+04:00</published>
                    <link href="http://kremlin.ru/events/president/news/80509"
                          rel="alternate" type="text/html" />
                    <summary type="html">&lt;p&gt;Краткий официальный анонс встречи.&lt;/p&gt;</summary>
                    <content type="html">
                        &lt;p&gt;Президент обсудил социально-экономическое развитие региона.&lt;/p&gt;
                        &lt;p&gt;В беседе также затронули реализацию новых проектов.&lt;/p&gt;
                    </content>
                </entry>
            </feed>
            """,
            "xml",
        )

        result = _parse_feed(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Президент России")
        self.assertEqual(result[0]["date"], "2026-08-11")
        self.assertEqual(
            result[0]["url"],
            "http://kremlin.ru/events/president/news/80509",
        )
        self.assertEqual(len(result[0]["article_paragraphs"]), 2)
        self.assertIn("официальный анонс", result[0]["summary"])


if __name__ == "__main__":
    unittest.main()
