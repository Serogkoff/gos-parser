import unittest
from unittest import mock

import requests

from utils import proxy


class KyodoProxyStatusTests(unittest.TestCase):
    def setUp(self):
        proxy._kyodo_status_cache.update({"checked_monotonic": 0.0, "value": None})

    def test_reports_working_channel_without_exposing_credentials(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(
            proxy,
            "kyodo_proxy_url",
            return_value="socks5h://secret-user:secret-password@203.0.113.7:1080",
        ), mock.patch.object(proxy.requests, "get", return_value=response) as request:
            result = proxy.kyodo_proxy_status(force=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["label"], "VPN работает")
        self.assertNotIn("secret", str(result))
        response.close.assert_called_once_with()
        self.assertIn("proxies", request.call_args.kwargs)

    def test_reports_unavailable_channel(self):
        with mock.patch.object(
            proxy,
            "kyodo_proxy_url",
            return_value="socks5h://203.0.113.7:1080",
        ), mock.patch.object(
            proxy.requests,
            "get",
            side_effect=requests.ConnectionError("offline"),
        ):
            result = proxy.kyodo_proxy_status(force=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["label"], "VPN недоступен")

    def test_reuses_short_lived_status_cache(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(
            proxy,
            "kyodo_proxy_url",
            return_value="socks5h://203.0.113.7:1080",
        ), mock.patch.object(proxy.requests, "get", return_value=response) as request:
            first = proxy.kyodo_proxy_status(force=True)
            second = proxy.kyodo_proxy_status()

        self.assertEqual(first, second)
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
