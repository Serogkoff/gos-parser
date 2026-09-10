import gzip
import unittest
from unittest.mock import patch

from flask import Response

import web_app


class WebPerformanceTests(unittest.TestCase):
    def test_large_html_response_is_gzipped_for_supported_client(self):
        with web_app.app.test_request_context(
            "/", headers={"Accept-Encoding": "gzip, deflate"}
        ):
            response = Response("Монитор" * 1000, mimetype="text/html")
            result = web_app.add_security_headers(response)

        self.assertEqual(result.headers.get("Content-Encoding"), "gzip")
        self.assertIn("Accept-Encoding", result.headers.get("Vary", ""))
        self.assertEqual(
            gzip.decompress(result.get_data()).decode("utf-8"),
            "Монитор" * 1000,
        )

    def test_waitress_uses_larger_bounded_thread_pool(self):
        with patch.object(
            web_app, "environment_value", return_value="12"
        ):
            self.assertEqual(web_app._server_threads(), 12)
        with patch.object(
            web_app, "environment_value", return_value="1000"
        ):
            self.assertEqual(web_app._server_threads(), 32)
        with patch.object(
            web_app, "environment_value", return_value="broken"
        ):
            self.assertEqual(web_app._server_threads(), 12)


if __name__ == "__main__":
    unittest.main()
