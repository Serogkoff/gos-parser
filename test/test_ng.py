import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup

from parsers.sites.ng import FRESH_ISSUE_URL, _parse_fresh_issue, parse


class NgFreshIssueTests(unittest.TestCase):
    def test_failed_run_makes_only_one_network_request(self):
        with patch("parsers.sites.ng.fetch_soup", return_value=None) as fetch:
            result = parse()

        self.assertEqual(result, [])
        fetch.assert_called_once_with(
            FRESH_ISSUE_URL,
            "Независимая газета",
            timeout=25,
            verify=True,
            attempts=1,
        )

    def test_reads_only_articles_from_current_issue(self):
        soup = BeautifulSoup(
            """
            <html><body>
                <div role="main">
                    <h1 class="htitle">Газета
                        <span class="num">2026-08-06 142 (9553)</span>
                    </h1>
                    <div class="anonce">
                        <h3><a href="/world/2026-08-05/1_9553_iran.html">
                            Ормузский пролив поделят на юг и север
                            <span class="numnpage">(5 полоса)</span>
                        </a></h3>
                    </div>
                    <div class="anonce">
                        <h3><a href="/world/2026-08-05/1_9553_iran.html">
                            Ормузский пролив поделят на юг и север
                        </a></h3>
                    </div>
                    <div class="anonce">
                        <h3><a href="/politics/2026-08-04/1_9552_old.html">
                            Материал предыдущего номера
                        </a></h3>
                    </div>
                </div>
            </body></html>
            """,
            "html.parser",
        )

        result = _parse_fresh_issue(soup)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["source"], "Независимая газета")
        self.assertEqual(
            result[0]["title"],
            "Ормузский пролив поделят на юг и север",
        )
        self.assertEqual(result[0]["date"], "2026-08-05")
        self.assertEqual(result[0]["edition_date"], "2026-08-06")


if __name__ == "__main__":
    unittest.main()
