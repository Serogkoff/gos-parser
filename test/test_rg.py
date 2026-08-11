import unittest

from bs4 import BeautifulSoup

from parsers.sites.rg import _parse_fresh_issue


class RussianGazetteTests(unittest.TestCase):
    def test_reads_articles_and_issue_metadata(self):
        soup = BeautifulSoup(
            """
            <main>
              <h1>Российская газета 11 августа 2026 г. №10014</h1>
              <section>
                <span>10.08.2026</span>
                <a href="/2026/08/10/vladimir-putin-potreboval-navesti-poriadok.html">
                  Владимир Путин потребовал навести порядок в сфере транспорта
                </a>
              </section>
              <a href="/economics/">Экономика</a>
            </main>
            """,
            "html.parser",
        )

        result = _parse_fresh_issue(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Российская газета")
        self.assertEqual(result[0]["date"], "2026-08-10")
        self.assertEqual(result[0]["edition_date"], "2026-08-11")
        self.assertEqual(result[0]["edition_id"], "10014")


if __name__ == "__main__":
    unittest.main()
