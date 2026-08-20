import unittest
from unittest.mock import Mock, patch

import requests

from utils.http_client import fetch_json, fetch_soup
from utils.js_client import _is_transient_browser_error
from utils.proxy import kyodo_proxy_url, playwright_proxy


class HttpClientRetryTests(unittest.TestCase):
    @patch("utils.http_client.requests.get")
    def test_fetch_json_uses_shared_http_client(self, get):
        response = Mock()
        response.content = b'{"data": []}'
        response.json.return_value = {"data": []}
        response.raise_for_status.return_value = None
        get.return_value = response

        payload = fetch_json("https://example.com/api/news", "Тест")

        self.assertEqual(payload, {"data": []})
        self.assertEqual(
            get.call_args.kwargs["headers"]["Accept"],
            "application/json",
        )

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

    def test_playwright_proxy_separates_credentials_from_server(self):
        proxy = playwright_proxy(
            "socks5h://kyodo-user:secret%20pass@203.0.113.7:1080"
        )

        self.assertEqual(proxy["server"], "socks5://203.0.113.7:1080")
        self.assertEqual(proxy["username"], "kyodo-user")
        self.assertEqual(proxy["password"], "secret pass")


class HttpClientProxyTests(unittest.TestCase):
    @patch("utils.http_client.requests.get")
    def test_proxy_is_scoped_to_explicit_request(self, get):
        response = Mock()
        response.content = b"<html>Kyodo</html>"
        response.raise_for_status.return_value = None
        get.return_value = response

        proxy_url = "socks5h://user:password@203.0.113.7:1080"
        fetch_soup(
            "https://www.47news.jp/123.html",
            "Киодо",
            proxy_url=proxy_url,
        )

        self.assertEqual(
            get.call_args.kwargs["proxies"],
            {"http": proxy_url, "https": proxy_url},
        )

    @patch.dict(
        "os.environ",
        {
            "KYODO_PROXY_URL": "",
            "KYODO_PROXY_HOST": "203.0.113.7",
            "KYODO_PROXY_PORT": "1080",
            "KYODO_PROXY_USERNAME": "kyodo user",
            "KYODO_PROXY_PASSWORD": "p@ss:word",
        },
        clear=False,
    )
    def test_builds_safe_url_from_separate_settings(self):
        self.assertEqual(
            kyodo_proxy_url(),
            "socks5h://kyodo%20user:p%40ss%3Aword@203.0.113.7:1080",
        )


if __name__ == "__main__":
    unittest.main()
