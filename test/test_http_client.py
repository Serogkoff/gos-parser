import unittest
from unittest.mock import Mock, patch

import requests

from utils.http_client import fetch_soup
from utils.js_client import _is_transient_browser_error


class HttpClientRetryTests(unittest.TestCase):
    @patch("utils.http_client.time.sleep")
    @patch("utils.http_client.requests.get")
    def test_retries_one_transient_timeout(self, get, sleep):
        response = Mock()
        response.content = b"<html><h1>News</h1></html>"
        response.raise_for_status.return_value = None
        get.side_effect = [requests.exceptions.Timeout(), response]

        soup = fetch_soup("https://example.com/news", "Тест")

        self.assertEqual(get.call_count, 2)
        sleep.assert_called_once()
        self.assertEqual(soup.select_one("h1").get_text(), "News")

    @patch("utils.http_client.time.sleep")
    @patch("utils.http_client.requests.get")
    def test_does_not_retry_permanent_403(self, get, sleep):
        response = Mock()
        response.status_code = 403
        response.raise_for_status.side_effect = requests.exceptions.HTTPError()
        get.return_value = response

        soup = fetch_soup("https://example.com/closed", "Тест")

        self.assertIsNone(soup)
        self.assertEqual(get.call_count, 1)
        sleep.assert_not_called()

    @patch("utils.http_client.time.sleep")
    @patch("utils.http_client.requests.get")
    def test_respects_retry_after_for_429(self, get, sleep):
        limited = Mock()
        limited.status_code = 429
        limited.headers = {"Retry-After": "4"}
        limited.raise_for_status.side_effect = requests.exceptions.HTTPError()
        response = Mock()
        response.content = b"<html>OK</html>"
        response.raise_for_status.return_value = None
        get.side_effect = [limited, response]

        soup = fetch_soup("https://example.com/news", "Тест")

        self.assertIsNotNone(soup)
        sleep.assert_called_once_with(4)


class BrowserRetryTests(unittest.TestCase):
    def test_retries_only_temporary_browser_network_errors(self):
        self.assertTrue(_is_transient_browser_error(
            "Page.goto: net::ERR_NETWORK_CHANGED"
        ))
        self.assertTrue(_is_transient_browser_error(
            "Page.goto: net::ERR_CONNECTION_RESET"
        ))
        self.assertFalse(_is_transient_browser_error(
            "Page.goto: net::ERR_CERT_AUTHORITY_INVALID"
        ))


if __name__ == "__main__":
    unittest.main()
