from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class CloudflareProxyTests(unittest.TestCase):
    def test_worker_keeps_public_host_and_uses_fixed_funnel_origin(self):
        script = (
            ROOT / "deploy" / "cloudflare" / "news-monitor-proxy.js"
        ).read_text(encoding="utf-8")

        self.assertIn('UPSTREAM_ORIGIN = "https://ria.tail196372.ts.net"', script)
        self.assertIn('PUBLIC_HOST = "news-monitor.ru"', script)
        self.assertIn('redirect: "manual"', script)
        self.assertIn('responseHeaders.set("Location"', script)
        self.assertIn('headers.set("X-Forwarded-Host"', script)


if __name__ == "__main__":
    unittest.main()
