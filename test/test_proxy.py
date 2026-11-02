import unittest
from unittest import mock

import requests

from utils import proxy


class KyodoProxyStatusTests(unittest.TestCase):
    def setUp(self):
        proxy._kyodo_status_cache.update({
            "checked_monotonic": 0.0,
            "value": None,
            "proxy_url": "",
            "candidate_index": None,
        })

    def test_reports_working_channel_without_exposing_credentials(self):
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(
            proxy,
            "_configured_proxy_urls",
            return_value=[
                "socks5h://secret-user:secret-password@203.0.113.7:1080"
            ],
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
            "_configured_proxy_urls",
            return_value=["socks5h://203.0.113.7:1080"],
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
            "_configured_proxy_urls",
            return_value=["socks5h://203.0.113.7:1080"],
        ), mock.patch.object(proxy.requests, "get", return_value=response) as request:
            first = proxy.kyodo_proxy_status(force=True)
            second = proxy.kyodo_proxy_status()

        self.assertEqual(first, second)
        request.assert_called_once()

    def test_uses_backup_when_primary_is_unavailable(self):
        primary = "socks5h://primary.test:1080"
        backup = "socks5h://backup.test:1080"
        failed = requests.ConnectionError("primary offline")
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(
            proxy,
            "_configured_proxy_urls",
            return_value=[primary, backup],
        ), mock.patch.object(
            proxy.requests,
            "get",
            side_effect=[failed, response],
        ):
            result = proxy.kyodo_proxy_status(force=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["state"], "backup")
        self.assertEqual(result["label"], "Резервный VPN")
        self.assertNotIn("backup.test", str(result))

    def test_primary_is_checked_again_after_cache_expires(self):
        primary = "socks5h://primary.test:1080"
        backup = "socks5h://backup.test:1080"
        response = mock.Mock()
        response.raise_for_status.return_value = None
        with mock.patch.object(
            proxy,
            "_configured_proxy_urls",
            return_value=[primary, backup],
        ), mock.patch.object(
            proxy.requests,
            "get",
            side_effect=[requests.ConnectionError("offline"), response, response],
        ) as request:
            first = proxy.kyodo_proxy_status(force=True)
            second = proxy.kyodo_proxy_status(force=True)

        self.assertEqual(first["state"], "backup")
        self.assertEqual(second["state"], "ok")
        self.assertEqual(request.call_count, 3)

    @mock.patch.dict(
        "os.environ",
        {
            "KYODO_PROXY_URL": "socks5h://primary.test:1080",
            "KYODO_PROXY_BACKUP_URL": "socks5h://backup.test:1080",
        },
        clear=False,
    )
    def test_builds_ordered_primary_and_backup_candidates(self):
        self.assertEqual(
            proxy._configured_proxy_urls(),
            [
                "socks5h://primary.test:1080",
                "socks5h://backup.test:1080",
            ],
        )


if __name__ == "__main__":
    unittest.main()
